"""Streaming LoRA merge for any Qwen3.5 base (round-1 merge_lora.py with the base as an argument; 4B and 2B).
  python merge_any.py <base_dir> <adapter_dir> <out_dir>"""
import json, os, re, shutil, sys
import torch
from safetensors import safe_open
from safetensors.torch import save_file, load_file
M, ad, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
cfg = json.load(open(os.path.join(ad, "adapter_config.json")))
scale = cfg["lora_alpha"] / cfg["r"]
lw = load_file(os.path.join(ad, "adapter_model.safetensors"))
pairs = {}
for k, v in lw.items():
    m = re.search(r"(layers\.\d+\..*)\.lora_([AB])\.weight$", k)
    if m:
        pairs.setdefault(m.group(1), {})[m.group(2)] = v.float()
idx = json.load(open(os.path.join(M, "model.safetensors.index.json")))
done, part, buf, size, wmap = 0, 0, {}, 0, {}


def flush():
    global part, buf, size
    if not buf:
        return
    part += 1
    fn = "model-part-%05d.safetensors" % part
    save_file(buf, os.path.join(out, fn), metadata={"format": "pt"})
    for k in buf:
        wmap[k] = fn
    buf, size = {}, 0


for shard in sorted(set(idx["weight_map"].values())):
    with safe_open(os.path.join(M, shard), "pt") as f:
        for k in f.keys():
            t = f.get_tensor(k)
            m = re.search(r"(layers\.\d+\..*)\.weight$", k)
            if m and "visual" not in k and "mtp" not in k and m.group(1) in pairs:
                p = pairs[m.group(1)]
                t = (t.float() + scale * (p["B"] @ p["A"])).to(t.dtype)
                done += 1
            buf[k] = t.contiguous()
            size += t.numel() * t.element_size()
            if size > 2 ** 30:
                flush()
flush()
json.dump({"metadata": {}, "weight_map": wmap}, open(os.path.join(out, "model.safetensors.index.json"), "w"))
for fn in os.listdir(M):
    if not fn.endswith(".safetensors") and fn != "model.safetensors.index.json" and os.path.isfile(os.path.join(M, fn)):
        shutil.copy(os.path.join(M, fn), out)
print("merged %d/%d LoRA modules (scale %.2f) -> %s" % (done, len(pairs), scale, out))
assert done == len(pairs), "unmatched LoRA modules"
