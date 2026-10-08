"""Measure weight quantisation error of the fine-tuned weights under three scale choices.

(a) published  : Qualcomm's base-model scales, unchanged
(b) widened    : max(published, min-max)   <- what the first export used
(c) exact      : per-channel min-max on the merged weights  <- the fix

Prints relative RMS error per scheme over a sample of tensors. Lower is better.
Usage: python compare_scales.py <ckpt_dir> <published_encodings.json> [n_tensors]
"""
import json, sys, numpy as np, onnx
from pathlib import Path

ck, pub_path = Path(sys.argv[1]), Path(sys.argv[2])
n_sample = int(sys.argv[3]) if len(sys.argv) > 3 else 40
m = onnx.load(str(ck / "model_dynamic.onnx"), load_external_data=False)
consumer = {i: n.op_type for n in m.graph.node for i in n.input}
inits = {t.name: t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL}
pub = {p["name"]: p for p in json.load(open(pub_path))["param_encodings"]}

names = [n for n in pub if n in inits]
rng = np.random.default_rng(0)
names = list(rng.choice(names, size=min(n_sample, len(names)), replace=False))

def qerr(w, scale, bw, ax):
    q = 2 ** (bw - 1)
    shape = [1] * w.ndim
    shape[ax] = -1
    s = np.maximum(scale.reshape(shape), 1e-12)
    deq = np.clip(np.round(w / s), -q, q - 1) * s
    return float(np.sqrt(((w - deq) ** 2).mean()) / (np.sqrt((w ** 2).mean()) + 1e-12))

tot = {"published": [], "widened": [], "exact": [], "tighter_of_both": [], "mse_optimal": []}
for name in names:
    p = pub[name]
    t = inits[name]
    if p.get("enc_type") != "PER_CHANNEL" or t.data_type != onnx.TensorProto.FLOAT:
        continue
    info = {e.key: e.value for e in t.external_data}
    dims = tuple(t.dims)
    w = np.array(np.memmap(ck / info["location"], np.float32, "r", int(info.get("offset", 0)),
                           (int(info["length"]) // 4,)).reshape(dims), dtype=np.float32)
    ax = len(dims) - 1 if consumer.get(name) in ("MatMul", "Gemm") else 0
    if dims[ax] != len(p["scale"]):
        continue
    red = tuple(i for i in range(len(dims)) if i != ax)
    q = 2 ** (p["bw"] - 1)
    need = np.maximum(w.max(axis=red) / (q - 1), -w.min(axis=red) / q)
    old = np.asarray(p["scale"], dtype=np.float64)
    tot["published"].append(qerr(w, old, p["bw"], ax))
    tot["widened"].append(qerr(w, np.maximum(old, need), p["bw"], ax))
    tot["exact"].append(qerr(w, np.maximum(need, 1e-12), p["bw"], ax))
    tot["tighter_of_both"].append(qerr(w, np.maximum(np.minimum(old, need), 1e-12), p["bw"], ax))
    # MSE-optimal clipping: per channel pick the alpha*min-max scale with lowest squared error
    best_s, best_e = None, None
    for alpha in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        cand = np.maximum(need * alpha, 1e-12)
        shape = [1] * w.ndim; shape[ax] = -1
        sc = cand.reshape(shape)
        deq = np.clip(np.round(w / sc), -q, q - 1) * sc
        e = ((w - deq) ** 2).mean(axis=red)
        if best_e is None:
            best_s, best_e = cand.copy(), e
        else:
            take = e < best_e
            best_s[take], best_e[take] = cand[take], e[take]
    tot["mse_optimal"].append(qerr(w, best_s, p["bw"], ax))

print(f"tensors compared: {len(tot['exact'])}")
for k, v in tot.items():
    print(f"  {k:10} relative RMS quantisation error: mean {np.mean(v):.4f}  max {np.max(v):.4f}")
best = min(tot, key=lambda k: np.mean(tot[k]))
print(f"best: {best}")
