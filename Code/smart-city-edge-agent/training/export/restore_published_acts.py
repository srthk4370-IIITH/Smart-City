"""Reconstruct the w4a16 checkpoint that produced the bundle currently on the QIDK.

Background: three checkpoints were used historically.
  ftgptq_ckpt    precision w4      (does not load on 8 Gen 3)
  ftgptq16_ckpt  precision w4a16   <- produced the LIVE bundle, since deleted in a disk cleanup
  ftcal_ckpt     precision w4a16   same GPTQ weights, Kaggle-recalibrated ACTIVATION ranges

merge_calibrated.py built ftcal_ckpt from ftgptq16_ckpt by replacing only `activation_encodings`
and hard-linking model.data. So the inverse rebuilds the original exactly:

    GPTQ param_encodings (from ftcal_ckpt)  +  published activation_encodings (from the qaihm cache)

model.data is hard-linked, so this costs no disk and cannot alter a single weight.

Usage:
  python restore_published_acts.py <src_ckpt> <published.encodings> <out_ckpt>

The result must be proven by exporting it and running compare_bundles.py against the live bundle:
every generated string has to match byte for byte.
"""
import json
import os
import shutil
import sys
from pathlib import Path

src, pub, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
dst.mkdir(parents=True, exist_ok=True)

for f in ("model_dynamic.onnx", "config.json", "special_tokens_map.json",
          "tokenizer.json", "tokenizer_config.json", "args.json"):
    shutil.copy(src / f, dst / f)
if not (dst / "model.data").exists():
    os.link(src / "model.data", dst / "model.data")  # hard link: same inode, same weights

args = json.load(open(dst / "args.json"))
if args.get("precision") != "w4a16":
    args["precision"] = "w4a16"
    json.dump(args, open(dst / "args.json", "w"))
print("precision:", args["precision"])

g = json.load(open(src / "model.encodings"))   # GPTQ params + recalibrated activations
p = json.load(open(pub))                       # published w4a16 reference


def as_list(x):
    return x if isinstance(x, list) else [dict(v, name=n) if "name" not in v else v for n, v in x.items()]


ga, pa = as_list(g["activation_encodings"]), as_list(p["activation_encodings"])
gn, pn = {a["name"] for a in ga}, {a["name"] for a in pa}
print(f"activation encodings: current {len(ga)}, published {len(pa)}, common {len(gn & pn)}")

keep = [a for a in pa if a["name"] in gn]           # published ranges for tensors this graph has
missing = gn - pn
if missing:
    print(f"  {len(missing)} tensors absent from published, retained as-is e.g. {sorted(missing)[:3]}")
    keep += [a for a in ga if a["name"] in missing]
extra = pn - gn
if extra:
    print(f"  {len(extra)} published tensors not in this graph, dropped e.g. {sorted(extra)[:3]}")

# report how far the restore moves the ranges (should mirror merge_calibrated's reported drift)
old = {a["name"]: a for a in ga}
ratios = []
for a in keep:
    o = old.get(a["name"])
    if o and a.get("dtype") == "INT" and o.get("scale") and a.get("scale"):
        so = o["scale"][0] if isinstance(o["scale"], list) else o["scale"]
        sn = a["scale"][0] if isinstance(a["scale"], list) else a["scale"]
        if so:
            ratios.append(sn / so)
if ratios:
    ratios.sort()
    q = lambda f: ratios[int(f * (len(ratios) - 1))]
    print(f"  activation scale published/current: median {q(.5):.3f}, p5 {q(.05):.3f}, p95 {q(.95):.3f} "
          f"over {len(ratios)} tensors")

g["activation_encodings"] = keep
# param_encodings are left untouched: they are the exact GPTQ per-channel scales.
json.dump(g, open(dst / "model.encodings", "w"))
(dst / ".ready").touch()
print("reconstructed checkpoint:", dst)
