"""Rebuild qai-hub-models' model.data (fp32 external weights of model_dynamic.onnx) from an HF checkpoint.

Lets us ship the 33 MB graph + 6 GB HF safetensors to Kaggle instead of the 14 GB model.data, while
keeping the EXACT same graph (and therefore the exact same activation-encoding tensor names) as the
local checkpoint we compile on AI Hub.

Layout (verified value-for-value on this model):
  model.model.layers.N.self_attn.{q,k,v}_proj_sha.H.weight [128,3072,1,1] <- HF rows H*128:(H+1)*128
  model.model.layers.N.self_attn.o_proj_conv.weight        [3072,3072,1,1] <- o_proj
  model.model.layers.N.mlp.down_proj.weight                [3072,8192,1,1] <- down_proj
  val_XXXX                                                 [3072,8192]     <- gate/up transposed (map file)
  model.lm_head.weight                                     [V,3072,1,1]    <- lm_head (or tied embed)
  model.model.<anything else>                                              <- HF "model.<anything else>"

Usage: python rebuild_model_data.py <model_dynamic.onnx> <hf_dir> <gateup_map.json> <out_model.data>
"""
import json, re, sys
from pathlib import Path

import numpy as np
import onnx
import torch
from safetensors import safe_open

onnx_path, hf_dir, map_path, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
gmap = json.load(open(map_path))
idx = hf_dir / "model.safetensors.index.json"
if idx.is_file():
    where = json.load(open(idx))["weight_map"]
else:
    where = {}
    for f in hf_dir.glob("*.safetensors"):
        with safe_open(str(f), framework="pt") as fh:
            where.update({k: f.name for k in fh.keys()})


def hf(name):
    if name == "lm_head.weight" and name not in where:
        name = "model.embed_tokens.weight"
    with safe_open(str(hf_dir / where[name]), framework="pt") as fh:
        return fh.get_tensor(name).float().numpy()


cache = {}
def hf_cached(name):
    if name not in cache:
        cache.clear()
        cache[name] = hf(name)
    return cache[name]


m = onnx.load(str(onnx_path), load_external_data=False)
ext = [t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL]
size = max(int({e.key: e.value for e in t.external_data}.get("offset", 0)) +
           int({e.key: e.value for e in t.external_data}["length"]) for t in ext)
out = np.memmap(out_path, np.float32, "w+", shape=(size // 4,))
heads = re.compile(r"model\.model\.layers\.(\d+)\.self_attn\.([qkv])_proj_sha\.(\d+)\.weight")
for i, t in enumerate(ext):
    info = {e.key: e.value for e in t.external_data}
    off, ln, dims = int(info.get("offset", 0)) // 4, int(info["length"]) // 4, tuple(t.dims)
    n = t.name
    if (mm := heads.fullmatch(n)):
        L, p, h = mm.groups()
        w = hf_cached(f"model.layers.{L}.self_attn.{p}_proj.weight")[int(h) * 128:(int(h) + 1) * 128]
    elif n.endswith("self_attn.o_proj_conv.weight"):
        w = hf(n[len("model."):].replace("o_proj_conv", "o_proj"))
    elif n in gmap:
        w = hf(gmap[n]).T
    elif n == "model.lm_head.weight":
        w = hf("lm_head.weight")
    elif n.startswith("model.model."):
        w = hf(n[len("model."):])
    else:
        raise KeyError(n)
    out[off:off + ln] = np.ascontiguousarray(w, dtype=np.float32).reshape(-1)
    if i % 200 == 0:
        print(f"  {i}/{len(ext)}", flush=True)
out.flush()
print(f"rebuilt {len(ext)} tensors -> {out_path} ({size} bytes)")
