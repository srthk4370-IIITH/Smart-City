"""Extract the QIDK model's exact weights (the w4a16 checkpoint the NPU bundle was compiled from)
into an HF-layout folder, so llama.cpp can run the SAME model on the Adreno GPU.

The checkpoint's model.data holds float32 weights that GPTQ placed exactly on the int4 grid
(w = s * q, q in [-8, 7], one scale s per output row), plus model.encodings with those scales and the
8-bit per-row scales of lm_head. This is the inverse of kaggle/rebuild_model_data.py:

  model.model.layers.N.self_attn.{q,k,v}_proj_sha.H.weight [128,3072,1,1] -> HF rows H*128:(H+1)*128
  model.model.layers.N.self_attn.o_proj_conv.weight        [3072,3072,1,1] -> o_proj
  model.model.layers.N.mlp.down_proj.weight                [3072,8192,1,1] -> down_proj
  val_XXXX                                                 [3072,8192]     -> gate/up, transposed (gateup_map.json)
  model.lm_head.weight                                     [V,3072,1,1]    -> lm_head
  model.model.<rest>                                                       -> HF model.<rest>

Writes <out>/model-XXXXX.safetensors (float32), model.safetensors.index.json, config.json
(tie_word_embeddings=false so lm_head is kept as its own tensor), tokenizer files, and
<out>/device_scales.npz: per-row scale vectors keyed by HF tensor name, used by pack_exact_gguf.py.

Usage: python extract_device_weights.py <ckpt_dir> <gateup_map.json> <out_dir>
"""
import json, re, shutil, sys
from pathlib import Path

import numpy as np
import onnx
from safetensors.numpy import save_file

ckpt, map_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
gmap = json.load(open(map_path))
enc = {p["name"]: p for p in json.load(open(ckpt / "model.encodings"))["param_encodings"]}

m = onnx.load(str(ckpt / "model_dynamic.onnx"), load_external_data=False)
ext = {t.name: t for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL}
data = np.memmap(ckpt / "model.data", np.float32, "r")


def view(name):
    t = ext[name]
    info = {e.key: e.value for e in t.external_data}
    off, ln = int(info.get("offset", 0)) // 4, int(info["length"]) // 4
    return np.asarray(data[off:off + ln]).reshape(tuple(t.dims))


def scale(name):
    return np.asarray(enc[name]["scale"], np.float64)


heads = {"q": 24, "k": 8, "v": 8}
inv_gate = {v: k for k, v in gmap.items()}
scales, index, shard = {}, {}, {}
n_shard = 0


def flush():
    global shard, n_shard
    if not shard:
        return
    n_shard += 1
    fn = f"model-{n_shard:05d}.safetensors"
    save_file(shard, str(out / fn))
    for k in shard:
        index[k] = fn
    shard = {}


for li in range(28):
    p = f"model.model.layers.{li}"
    for proj, nh in heads.items():
        names = [f"{p}.self_attn.{proj}_proj_sha.{h}.weight" for h in range(nh)]
        w = np.concatenate([view(n).reshape(128, 3072) for n in names], 0)
        hf = f"model.layers.{li}.self_attn.{proj}_proj.weight"
        shard[hf], scales[hf] = w, np.concatenate([scale(n) for n in names])
    for src, hf in ((f"{p}.self_attn.o_proj_conv.weight", f"model.layers.{li}.self_attn.o_proj.weight"),
                    (f"{p}.mlp.down_proj.weight", f"model.layers.{li}.mlp.down_proj.weight")):
        v = view(src)
        shard[hf], scales[hf] = v.reshape(v.shape[0], v.shape[1]), scale(src)
    for mod in ("gate_proj", "up_proj"):
        hf = f"model.layers.{li}.mlp.{mod}.weight"
        src = inv_gate[hf]
        shard[hf], scales[hf] = np.ascontiguousarray(view(src).T), scale(src)
    for nm in ("input_layernorm", "post_attention_layernorm"):
        shard[f"model.layers.{li}.{nm}.weight"] = view(f"{p}.{nm}.weight")
    if li % 4 == 3:
        flush()
        print(f"layers 0..{li} extracted", flush=True)

v = view("model.lm_head.weight")
shard["lm_head.weight"], scales["lm_head.weight"] = v.reshape(v.shape[0], v.shape[1]), scale("model.lm_head.weight")
flush()
shard["model.embed_tokens.weight"] = view("model.model.embed_tokens.weight")
shard["model.norm.weight"] = view("model.model.norm.weight")
flush()

# (grid exactness is verified in pack_exact_gguf.py, where the integers are recovered)
json.dump({"metadata": {}, "weight_map": index}, open(out / "model.safetensors.index.json", "w"), indent=1)
np.savez(out / "device_scales.npz", **{k.replace(".", "|"): v for k, v in scales.items()})
cfg = json.load(open(ckpt / "config.json"))
cfg["tie_word_embeddings"] = False
cfg["torch_dtype"] = "float32"
json.dump(cfg, open(out / "config.json", "w"), indent=2)
for f in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
    shutil.copy(ckpt / f, out / f)
print(f"done: {len(index)} tensors, {n_shard} shards -> {out}")
