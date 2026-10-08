"""Write GPTQ int4 weights + their exact per-channel scales into a qai-hub-models ONNX checkpoint.

The Qualcomm graph stores (verified value-for-value against the merged HF weights):
  q/k/v_proj   -> model.model.layers.N.self_attn.{q,k,v}_proj_sha.H.weight   [128, 3072, 1, 1]  (one per head)
  o_proj       -> model.model.layers.N.self_attn.o_proj_conv.weight          [3072, 3072, 1, 1]
  down_proj    -> model.model.layers.N.mlp.down_proj.weight                  [3072, 8192, 1, 1]
  gate/up_proj -> val_XXXX                                                   [3072, 8192]  (transposed, MatMul)
Every tensor is quantised per output channel, so each head/transposed slice keeps its rows' scales.

Weights are written as s*q in float32 and the encoding scale is set to s, so AI Hub's quantiser
reproduces q exactly. lm_head / embedding / norms are left untouched.

Usage: python gptq_to_ckpt.py --q <gptq_out>/q --src <ckpt_w4a16> --dst <new_ckpt> --precision w4|w4a16
"""
import argparse, json, re, shutil
from pathlib import Path

import numpy as np
import onnx
from safetensors.numpy import load_file

ap = argparse.ArgumentParser()
ap.add_argument("--q", required=True)
ap.add_argument("--src", required=True)
ap.add_argument("--dst", required=True)
ap.add_argument("--precision", choices=["w4", "w4a16"], default="w4")
ap.add_argument("--encodings", required=True, help="published model.encodings for that precision")
a = ap.parse_args()
qdir, src, dst = Path(a.q), Path(a.src), Path(a.dst)
dst.mkdir(parents=True, exist_ok=True)

for f in ("model_dynamic.onnx", "config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"):
    shutil.copy(src / f, dst / f)
if not (dst / "model.data").is_file() or (dst / "model.data").stat().st_size != (src / "model.data").stat().st_size:
    print("copying model.data (14 GB) ...", flush=True)
    shutil.copy(src / "model.data", dst / "model.data")

m = onnx.load(str(dst / "model_dynamic.onnx"), load_external_data=False)
inits = {t.name: t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL}
data = np.memmap(dst / "model.data", np.float32, "r+")


def view(name):
    t = inits[name]
    info = {e.key: e.value for e in t.external_data}
    off, ln = int(info.get("offset", 0)) // 4, int(info["length"]) // 4
    return data[off:off + ln].reshape(tuple(t.dims))


enc = json.load(open(a.encodings))
penc = {p["name"]: p for p in enc["param_encodings"]}

# gate/up live in anonymous MatMul initialisers: pair them to layers in graph order, then tell gate
# from up by exact value match against the ORIGINAL (pre-GPTQ) weights still in the source data.
vals = sorted((n for n in inits if re.fullmatch(r"val_\d+", n) and tuple(inits[n].dims) == (3072, 8192)),
              key=lambda n: int(n[4:]))
assert len(vals) == 56, len(vals)
src_data = np.memmap(src / "model.data", np.float32, "r")


def src_view(name):
    t = inits[name]
    info = {e.key: e.value for e in t.external_data}
    off, ln = int(info.get("offset", 0)) // 4, int(info["length"]) // 4
    return src_data[off:off + ln].reshape(tuple(t.dims))


def put(name, w_rows, s_rows, transpose=False):
    """w_rows [out, in] float32 already on the grid; s_rows [out]."""
    v = view(name)
    v[...] = (w_rows.T if transpose else w_rows).reshape(v.shape)
    p = penc[name]
    assert len(p["scale"]) == len(s_rows), (name, len(p["scale"]), len(s_rows))
    p["scale"] = [float(x) for x in s_rows]
    p["offset"] = [-8.0] * len(s_rows)


heads = {"q_proj": 24, "k_proj": 8, "v_proj": 8}
done = 0
for li in range(28):
    qs = load_file(str(qdir / f"layer_{li:02d}.safetensors"))
    def W(mod):
        q = qs[f"model.layers.{li}.{mod}.weight.q"].astype(np.float32)
        s = qs[f"model.layers.{li}.{mod}.weight.s"].astype(np.float32)
        return q * s[:, None], s, q
    for proj, nh in heads.items():
        w, s, _ = W(f"self_attn.{proj}")
        for h in range(nh):
            put(f"model.model.layers.{li}.self_attn.{proj}_sha.{h}.weight", w[h * 128:(h + 1) * 128], s[h * 128:(h + 1) * 128])
            done += 1
    w, s, _ = W("self_attn.o_proj"); put(f"model.model.layers.{li}.self_attn.o_proj_conv.weight", w, s); done += 1
    w, s, _ = W("mlp.down_proj"); put(f"model.model.layers.{li}.mlp.down_proj.weight", w, s); done += 1
    pair = vals[2 * li:2 * li + 2]
    for mod in ("gate_proj", "up_proj"):
        w, s, q = W(f"mlp.{mod}")
        # identify by sign pattern agreement with the original weights (GPTQ keeps it overwhelmingly)
        agree = [float((np.sign(src_view(n)[:256, :64]) == np.sign(w.T[:256, :64])).mean()) for n in pair]
        name = pair[int(np.argmax(agree))]
        assert max(agree) > 0.6 and max(agree) - min(agree) > 0.2, (li, mod, agree)
        put(name, w, s, transpose=True)
        done += 1
    if li % 7 == 0:
        print(f"layer {li} written", flush=True)
data.flush()

# verify: AI Hub's rounding with our scales must give back the GPTQ integers exactly
bad = 0
for name in (f"model.model.layers.{li}.self_attn.q_proj_sha.3.weight" for li in (0, 13, 27)):
    v = view(name).reshape(128, -1).astype(np.float64)
    s = np.asarray(penc[name]["scale"])[:, None]
    q = np.round(v / s)
    bad += int((np.abs(v - q * s) > 1e-6 * np.abs(v).max()).sum()) + int(((q < -8) | (q > 7)).sum())
print(f"tensors written: {done}; grid check mismatches: {bad}")
assert bad == 0
json.dump(enc, open(dst / "model.encodings", "w"))
json.dump({"precision": a.precision}, open(dst / "args.json", "w"))
(dst / ".ready").touch()
print("checkpoint ready:", dst)
