"""Combine Kaggle's AIMET-calibrated ACTIVATION encodings with our exact GPTQ WEIGHT encodings.

AIMET recomputed every activation range on the fine-tuned (GPTQ) model with our own agent prompts. Its
weight encodings are discarded: the GPTQ checkpoint's per-channel scales are exact for the integers
GPTQ chose (AIMET's min-max would re-round them).

Usage: python merge_calibrated.py <kaggle_model.encodings> <gptq_ckpt_dir> <out_ckpt_dir>
The out dir gets model.data hard-linked from the GPTQ checkpoint (no 14 GB copy).
"""
import json, os, shutil, sys
from pathlib import Path

kag, src, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
dst.mkdir(parents=True, exist_ok=True)
for f in ("model_dynamic.onnx", "config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "args.json"):
    shutil.copy(src / f, dst / f)
if not (dst / "model.data").exists():
    os.link(src / "model.data", dst / "model.data")

k = json.load(open(kag))
g = json.load(open(src / "model.encodings"))


def as_list(x):
    return x if isinstance(x, list) else [dict(v, name=n) if "name" not in v else v for n, v in x.items()]


ka, ga = as_list(k["activation_encodings"]), as_list(g["activation_encodings"])
kn, gn = {a["name"] for a in ka}, {a["name"] for a in ga}
print(f"activation encodings: kaggle {len(ka)}, gptq/published {len(ga)}, common {len(kn & gn)}")
missing = gn - kn
if missing:
    # keep the published range for any tensor AIMET did not report (should be none)
    print(f"  {len(missing)} tensors kept from published encodings, e.g. {sorted(missing)[:3]}")
    ka = ka + [a for a in ga if a["name"] in missing]
extra = kn - gn
if extra:
    print(f"  {len(extra)} extra kaggle tensors dropped, e.g. {sorted(extra)[:3]}")
    ka = [a for a in ka if a["name"] in gn]

# how much did calibration move the ranges? (scale ratio new/old, int tensors only)
old = {a["name"]: a for a in ga}
ratios = []
for a in ka:
    o = old.get(a["name"])
    if o and a.get("dtype") == "INT" and o.get("scale") and a.get("scale"):
        so, sn = o["scale"], a["scale"]
        so = so[0] if isinstance(so, list) else so
        sn = sn[0] if isinstance(sn, list) else sn
        if so:
            ratios.append(sn / so)
if ratios:
    ratios.sort()
    q = lambda p: ratios[int(p * (len(ratios) - 1))]
    print(f"  activation scale new/old: median {q(0.5):.3f}, p5 {q(0.05):.3f}, p95 {q(0.95):.3f} over {len(ratios)} tensors")

g["activation_encodings"] = ka
json.dump(g, open(dst / "model.encodings", "w"))
(dst / ".ready").touch()
print("merged checkpoint ready:", dst)
