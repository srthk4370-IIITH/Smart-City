#!/usr/bin/env python3
"""Write the think-gating edit into real weights (owner 2026-11-13).

  python edit_weights.py BASE_DIR ADAPTER_DIR DIRS_NPZ OUT_DIR --layers 24-31 --alpha 1.0

For every writer matrix (self_attn.o_proj, linear_attn.out_proj, mlp.down_proj) in the chosen layers, with r3's LoRA folded
in for the direction maths:   W_eff = W0 + s*B@A   (s = lora_alpha / r)
                              W0'   = W0 - a * u (u^T W_eff)
so that W0' + s*B@A = (I - a u u^T) W_eff: exactly the hook edit of the sweep, applied to the weights. The r3 adapter stays
separate (training continues from it with --init-adapter); the output dir is a full bf16 base (other tensors copied byte for
byte), streamed one tensor at a time (WSL RAM cap). Writes OUT_DIR/EDIT.json (layers, alpha, per-matrix |dW|/|W|, md5 of u).
"""
import argparse
import hashlib
import json
import os
import re
import shutil

import numpy as np
import torch
from safetensors import safe_open
from safetensors.torch import load_file, save_file

ap = argparse.ArgumentParser()
ap.add_argument("base"); ap.add_argument("adapter"); ap.add_argument("dirs"); ap.add_argument("out")
ap.add_argument("--layers", default="", help="projection mode: e.g. 24-31 or 16,18,20")
ap.add_argument("--alpha", type=float, default=0.0)
ap.add_argument("--dw", default="", help="MEMIT mode: we_memit.py dW file; down_proj W0' = W0 + dW (output delta is additive, LoRA stays separate)")
a = ap.parse_args()
L = set()
DW = torch.load(a.dw)["dW"] if a.dw else {}
for part in (a.layers.split(",") if a.layers else []):
    lo, _, hi = part.partition("-")
    L.update(range(int(lo), int(hi or lo) + 1))
U = np.load(a.dirs)["u"]
os.makedirs(a.out, exist_ok=True)
cfg = json.load(open(os.path.join(a.adapter, "adapter_config.json")))
s = cfg["lora_alpha"] / cfg["r"]
lw = load_file(os.path.join(a.adapter, "adapter_model.safetensors"))
pairs = {}
for k, v in lw.items():
    m = re.search(r"(layers\.\d+\..*)\.lora_([AB])\.weight$", k)
    if m:
        pairs.setdefault(m.group(1), {})[m.group(2)] = v.float()
idx = json.load(open(os.path.join(a.base, "model.safetensors.index.json")))
WR = re.compile(r"(?:^|\.)(layers\.(\d+)\.(?:self_attn\.o_proj|linear_attn\.out_proj|mlp\.down_proj))\.weight$")
part, buf, size, wmap, log = 0, {}, 0, {}, []


def flush():
    global part, buf, size
    if not buf:
        return
    part += 1
    fn = "model-edit-%05d.safetensors" % part
    save_file(buf, os.path.join(a.out, fn + ".part"), metadata={"format": "pt"})
    os.replace(os.path.join(a.out, fn + ".part"), os.path.join(a.out, fn))
    for k in buf:
        wmap[k] = fn
    buf, size = {}, 0


for shard in sorted(set(idx["weight_map"].values())):
    with safe_open(os.path.join(a.base, shard), "pt") as f:
        for k in f.keys():
            t = f.get_tensor(k)
            m = WR.search(k)
            if DW and m and "visual" not in k and "mtp" not in k and k.endswith("mlp.down_proj.weight") and int(m.group(2)) in DW:
                d = DW[int(m.group(2))].float()
                assert d.shape == t.shape, (k, d.shape, t.shape)
                log.append({"key": k, "mode": "memit", "rel_change": float(d.norm() / t.float().norm())})
                t = (t.float() + d).to(t.dtype)
            elif m and "visual" not in k and "mtp" not in k and int(m.group(2)) in L:
                W0 = t.float()
                p = pairs.get(m.group(1))
                Weff = W0 + s * (p["B"] @ p["A"]) if p else W0
                u = torch.tensor(U[int(m.group(2))], dtype=torch.float32)
                assert u.shape[0] == W0.shape[0], (k, W0.shape)
                dW = -a.alpha * torch.outer(u, u @ Weff)
                t = (W0 + dW).to(t.dtype)
                log.append({"key": k, "lora": bool(p), "rel_change": float(dW.norm() / Weff.norm())})
            buf[k] = t.contiguous()
            size += t.numel() * t.element_size()
            if size > 2 ** 30:
                flush()
flush()
json.dump({"metadata": {}, "weight_map": wmap}, open(os.path.join(a.out, "model.safetensors.index.json"), "w"))
for fn in os.listdir(a.base):
    if not fn.endswith(".safetensors") and fn != "model.safetensors.index.json" and os.path.isfile(os.path.join(a.base, fn)):
        shutil.copy(os.path.join(a.base, fn), a.out)
want = sum(1 for _ in L) * 2 + len(DW)  # projection: o_proj/out_proj + down_proj per layer; memit: one down_proj per layer
info = {"layers": sorted(L), "alpha": a.alpha, "dw": a.dw, "dw_layers": sorted(DW), "lora_scale": s, "edited": len(log), "expected": want,
        "u_md5": hashlib.md5(U.tobytes()).hexdigest(), "base": a.base, "adapter": a.adapter, "matrices": log}
json.dump(info, open(os.path.join(a.out, "EDIT.json"), "w"), indent=1)
print("edited %d matrices (expected %d), mean rel change %.4f -> %s" % (len(log), want, np.mean([x["rel_change"] for x in log]), a.out))
assert len(log) == want, "writer matrices not all found"
