"""Recompute per-channel 4-bit weight scales for the LoRA-merged weights, minimising quantisation error.

Why not just keep Qualcomm's published scales, or plain min-max?  Measured on this fine-tune
(40 random tensors, relative RMS weight quantisation error, lower is better):

    published base scales      0.1331   (max 0.2368)
    max(published, min-max)    0.1732   (max 0.2718)   <- first export used this; it was the worst
    exact min-max              0.1731   (max 0.2718)
    tighter of both            0.1330   (max 0.2355)
    MSE-optimal clipping       0.1201   (max 0.1715)   <- this script

Plain min-max is dragged out by a few LoRA-induced outliers, which coarsens every other weight in the
channel. Deliberately clipping those outliers (scale = alpha * min-max, alpha chosen per channel to
minimise squared error) is the standard fix and wins on both mean and worst case.

Activation encodings are left exactly as published: recomputing them needs calibration data, and at
16 bits they tolerate the weight shift far better than the 4-bit weights do.

Usage: python refresh_param_scales.py <ckpt_dir> [published_encodings.json]
       (the published file is restored first, so the script is safe to re-run)
       SCALE_MODE=widen|mse|published   (default widen)

UPDATE after measuring on the device (46 held-out examples, w4a16):
    widen  (max(published, min-max))   pattern 54.3 %   <- best on device
    mse    (MSE-optimal clipping)      pattern 39.1 %   <- lowest weight RMS error, yet worse
Clipping removes the few large-magnitude weights that LLMs depend on most (the "salient weight"
effect behind AWQ), so weight RMS error is a misleading proxy here. Default is therefore widen.
"""
import os
import json, shutil, sys, numpy as np, onnx
from pathlib import Path

ck = Path(sys.argv[1])
if len(sys.argv) > 2:
    shutil.copy(sys.argv[2], ck / "model.encodings")
    print(f"restored published encodings from {sys.argv[2]}")

MODE = os.environ.get("SCALE_MODE", "widen")
ALPHAS = np.arange(0.45, 1.001, 0.05)   # fraction of the min-max range to keep (mse mode)
STRIDE = 4                              # subsample when searching alpha (then apply it exactly)

m = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)
consumer = {i: n.op_type for n in m.graph.node for i in n.input}
inits = {t.name: t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL}
enc = json.load(open(ck / "model.encodings"))
done = skipped = 0
pe = enc["param_encodings"]
if MODE == "published":
    print("SCALE_MODE=published: keeping published weight scales unchanged")
    pe = []
for p in pe:
    t = inits.get(p["name"])
    if p.get("enc_type") != "PER_CHANNEL" or t is None or t.data_type != onnx.TensorProto.FLOAT:
        skipped += 1
        continue
    info = {e.key: e.value for e in t.external_data}
    dims = tuple(t.dims)
    w = np.memmap(ck / info["location"], np.float32, "r", int(info.get("offset", 0)),
                  (int(info["length"]) // 4,)).reshape(dims)
    ax = len(dims) - 1 if consumer.get(p["name"]) in ("MatMul", "Gemm") else 0
    if dims[ax] != len(p["scale"]):
        skipped += 1
        continue
    if MODE == "widen":
        red = tuple(i for i in range(len(dims)) if i != ax)
        q = 2 ** (p["bw"] - 1)
        need = np.maximum(w.max(axis=red) / (q - 1), -w.min(axis=red) / q)
        p["scale"] = np.maximum(np.asarray(p["scale"], dtype=np.float64), need).tolist()
        done += 1
        continue
    # move the channel axis first, flatten the rest, subsample for the search
    wm = np.moveaxis(np.asarray(w, dtype=np.float32), ax, 0).reshape(dims[ax], -1)
    sub = wm[:, ::STRIDE]
    q = 2 ** (p["bw"] - 1)
    need = np.maximum(sub.max(axis=1) / (q - 1), -sub.min(axis=1) / q)
    need = np.maximum(need, 1e-12)
    best_s = need.copy()
    best_e = None
    for alpha in ALPHAS:
        cand = np.maximum(need * alpha, 1e-12)[:, None]
        deq = np.clip(np.round(sub / cand), -q, q - 1) * cand
        e = ((sub - deq) ** 2).mean(axis=1)
        if best_e is None:
            best_e = e
        else:
            take = e < best_e
            best_s[take] = cand[take, 0]
            best_e[take] = e[take]
    p["scale"] = best_s.astype(np.float64).tolist()
    done += 1
    if done % 200 == 0:
        print(f"  {done} tensors rescaled", flush=True)
json.dump(enc, open(ck / "model.encodings", "w"))
print(f"rescale ({MODE}) done: {done} tensors, {skipped} entries skipped")
