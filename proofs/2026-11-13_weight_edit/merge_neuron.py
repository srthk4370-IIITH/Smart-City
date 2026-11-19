#!/usr/bin/env python3
"""Merge r3-2800 (base + LoRA) and apply neuron tweaks to the merged bf16 weights, streamed per tensor (CPU, low RAM).
  python merge_neuron.py BASE ADAPTER OUT tweaks1.json[,tweaks2.json] DIR_NPY
Tweak {"L","i","f"}: down_proj column i *= f (== the eval hook scaling input feature i).
Tweak {"L","i","add","ref","dir":"grad"}: down_proj column i += d * add / (ref * |d|^2)   (d = DIR_NPY), as the eval hook.
Writes OUT/NEURON_EDIT.json (tweaks, per-column change)."""
import json, os, re, shutil, sys
import numpy as np, torch
from safetensors import safe_open
from safetensors.torch import save_file, load_file
B, A, O, TW, DN = sys.argv[1:6]
os.makedirs(O, exist_ok=True)
cfg = json.load(open(os.path.join(A, "adapter_config.json"))); scale = cfg["lora_alpha"] / cfg["r"]
lw = load_file(os.path.join(A, "adapter_model.safetensors")); pairs = {}
for k, v in lw.items():
    m = re.search(r"(layers\.\d+\..*)\.lora_([AB])\.weight$", k)
    if m:
        pairs.setdefault(m.group(1), {})[m.group(2)] = v.float()
tw = []
for f in TW.split(","):
    tw += json.load(open(f))
by = {}
for t in tw:
    by.setdefault(t["L"], []).append(t)
d = torch.tensor(np.load(DN), dtype=torch.float32)
idx = json.load(open(os.path.join(B, "model.safetensors.index.json")))
part, buf, size, wmap, merged, log = 0, {}, 0, {}, 0, []


def flush():
    global part, buf, size
    if not buf:
        return
    part += 1; fn = "model-neuron-%05d.safetensors" % part
    save_file(buf, os.path.join(O, fn + ".part"), metadata={"format": "pt"}); os.replace(os.path.join(O, fn + ".part"), os.path.join(O, fn))
    for k in buf:
        wmap[k] = fn
    buf, size = {}, 0


for shard in sorted(set(idx["weight_map"].values())):
    with safe_open(os.path.join(B, shard), "pt") as f:
        for k in f.keys():
            t = f.get_tensor(k); dt = t.dtype
            m = re.search(r"(layers\.(\d+)\..*)\.weight$", k)
            if m and "visual" not in k and "mtp" not in k and m.group(1) in pairs:
                p = pairs[m.group(1)]; t = t.float() + scale * (p["B"] @ p["A"]); merged += 1
                L = int(m.group(2))
                if k.endswith("mlp.down_proj.weight") and L in by:
                    for x in by[L]:
                        i = x["i"]; before = t[:, i].clone()
                        if "add" in x:
                            t[:, i] += d * (x["add"] / (x["ref"] * float(d @ d)))
                        else:
                            t[:, i] *= x["f"]
                        log.append({"key": k, "i": i, "tweak": x, "rel_change": float((t[:, i] - before).norm() / (before.norm() + 1e-9))})
                t = t.to(dt)
            buf[k] = t.contiguous(); size += t.numel() * t.element_size()
            if size > 2 ** 30:
                flush()
flush()
json.dump({"metadata": {}, "weight_map": wmap}, open(os.path.join(O, "model.safetensors.index.json"), "w"))
for fn in os.listdir(B):
    if not fn.endswith(".safetensors") and fn != "model.safetensors.index.json" and os.path.isfile(os.path.join(B, fn)):
        shutil.copy(os.path.join(B, fn), O)
json.dump({"base": B, "adapter": A, "tweak_files": TW, "dir": DN, "lora_merged": merged, "tweaks_applied": len(log), "tweaks_wanted": len(tw),
           "log": log}, open(os.path.join(O, "NEURON_EDIT.json"), "w"), indent=1)
print("merged %d LoRA modules, %d/%d neuron tweaks -> %s" % (merged, len(log), len(tw), O))
assert merged == len(pairs) and len(log) == len(tw)
