"""Tiny Qwen3.5 (same architecture/config keys as ~/models/qwen3.5-4b, hidden 64, 4 layers, random bf16 weights, real
tokenizer files) + a fake finished run dir (status.json early_stop, best.json, ckpt_best_0300 with an r32/a64 LoRA on the
trainer's target modules, ckpt_best_0200 missing on purpose) for the post_chain dry run.  python3 make_tiny.py <outdir>"""
import json
import os
import shutil
import sys

import torch
from safetensors.torch import save_file

O = sys.argv[1]
SRC = os.path.expanduser("~/models/qwen3.5-4b")
B, R = os.path.join(O, "base"), os.path.join(O, "run")
for d in (B, R):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
cfg = json.load(open(os.path.join(SRC, "config.json")))
t = cfg["text_config"]
t.update(hidden_size=64, intermediate_size=128, num_hidden_layers=4, layer_types=["linear_attention"] * 3 + ["full_attention"],
         head_dim=32, num_attention_heads=2, num_key_value_heads=1, linear_key_head_dim=16, linear_num_key_heads=2,
         linear_num_value_heads=4, linear_value_head_dim=16, mtp_num_hidden_layers=1)
v = cfg["vision_config"]
v.update(depth=1, hidden_size=64, intermediate_size=128, num_heads=2, out_hidden_size=64)
json.dump(cfg, open(os.path.join(B, "config.json"), "w"), indent=1)
for f in os.listdir(SRC):
    if not f.endswith(".safetensors") and f not in ("config.json", "model.safetensors.index.json", "SHA256SUMS") and os.path.isfile(os.path.join(SRC, f)):
        shutil.copy(os.path.join(SRC, f), B)
from transformers import AutoConfig, AutoModelForImageTextToText  # noqa: E402
torch.manual_seed(0)
m = AutoModelForImageTextToText.from_config(AutoConfig.from_pretrained(B), torch_dtype=torch.bfloat16)
sd = {k: v.contiguous() for k, v in m.state_dict().items() if k != "lm_head.weight"}   # tied embeddings, as the real base
H, I = t["hidden_size"], t["intermediate_size"]
for k in ("fc.weight",):
    sd["mtp." + k] = torch.randn(H, 2 * H, dtype=torch.bfloat16) * 0.02
for k in ("norm.weight", "pre_fc_norm_embedding.weight", "pre_fc_norm_hidden.weight", "layers.0.input_layernorm.weight",
          "layers.0.post_attention_layernorm.weight", "layers.0.self_attn.q_norm.weight", "layers.0.self_attn.k_norm.weight"):
    sd["mtp." + k] = torch.ones(t["head_dim"] if "q_norm" in k or "k_norm" in k else H, dtype=torch.bfloat16)
ref = "model.language_model.layers.3.self_attn."
for k in ("q_proj", "k_proj", "v_proj", "o_proj"):
    sd["mtp.layers.0.self_attn.%s.weight" % k] = sd[ref + k + ".weight"].clone()
for k in ("gate_proj", "up_proj", "down_proj"):
    sd["mtp.layers.0.mlp.%s.weight" % k] = sd["model.language_model.layers.0.mlp.%s.weight" % k].clone()
keys = sorted(sd)
half = len(keys) // 2
wm = {}
for i, part in enumerate((keys[:half], keys[half:])):
    fn = "model.safetensors-%05d-of-00002.safetensors" % (i + 1)
    save_file({k: sd[k] for k in part}, os.path.join(B, fn), metadata={"format": "pt"})
    wm.update({k: fn for k in part})
json.dump({"metadata": {}, "weight_map": wm}, open(os.path.join(B, "model.safetensors.index.json"), "w"), indent=1)
# ---- fake run: LoRA r32/a64 on the trainer's targets, keys as PEFT saves them
TG = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "out_proj")
lw = {}
for k in keys:
    if k.startswith("model.language_model.layers.") and k.endswith(".weight") and k.split(".")[-2] in TG:
        w = sd[k]
        base = "base_model.model." + k[:-len(".weight")]
        lw[base + ".lora_A.weight"] = torch.randn(32, w.shape[1]) * 0.05
        lw[base + ".lora_B.weight"] = torch.randn(w.shape[0], 32) * 0.05
ck = os.path.join(R, "ckpt_best_0300")
os.makedirs(ck)
save_file(lw, os.path.join(ck, "adapter_model.safetensors"))
json.dump({"r": 32, "lora_alpha": 64, "use_rslora": False, "use_dora": False, "peft_type": "LORA", "target_modules": list(TG)},
          open(os.path.join(ck, "adapter_config.json"), "w"))
json.dump({"top": [[0.62, 200], [0.61, 300], [0.55, 100]], "best": 0.62, "since_best": 3, "evals": 5}, open(os.path.join(R, "best.json"), "w"))
json.dump({"step": 320, "stopped": "early_stop", "done": False}, open(os.path.join(R, "status.json"), "w"))
open(os.path.join(R, "gen_eval.jsonl"), "w").write(json.dumps({"step": 300, "dev": {"score": 0.61}}) + "\n")
open(os.path.join(R, "train.log"), "w").write("step 320/4297 ...\n")
print("tiny base %s (%d tensors, %.1f MB), run %s (%d LoRA modules)" % (B, len(keys), sum(x.numel() * 2 for x in sd.values()) / 1e6, R, len(lw) // 2))
