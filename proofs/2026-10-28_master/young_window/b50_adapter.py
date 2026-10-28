"""Exact PEFT LoRA form of B50 = m50 + 0.5 v21 - 0.5 v2 (concatenated ranks, sign folded into B), so training can start
from B50 (train_3e --init-adapter). delta = sum_i w_i s_i B_i A_i == s B A with A = [sqrt(|w_i| s_i/s) A_i], B = [sign(w_i) sqrt(|w_i| s_i/s) B_i].
  python b50_adapter.py OUT_DIR"""
import json, math, shutil, sys
from pathlib import Path
import torch
from safetensors import safe_open
from safetensors.torch import save_file
H = Path.home() / "smartcity_runs"
MIX = [(H / "agents_v2_topup3f/m50_adapter", 1.0), (H / "agents_v21/run1/checkpoints/checkpoint-621", 0.5), (H / "agents_v2/adapter", -0.5)]
o = Path(sys.argv[1]); o.mkdir(parents=True, exist_ok=True)
cfgs = [json.loads((d / "adapter_config.json").read_text()) for d, _ in MIX]
s_i = [c["lora_alpha"] / c["r"] for c in cfgs]; s = 1.0
T = []
for d, _ in MIX:
    with safe_open(str(d / "adapter_model.safetensors"), "pt") as f:
        T.append({k: f.get_tensor(k) for k in f.keys()})
out, chk = {}, {}
for k in T[0]:
    if not k.endswith("lora_A.weight"):
        continue
    kb = k.replace("lora_A", "lora_B")
    f = [math.sqrt(abs(w) * si / s) for (_, w), si in zip(MIX, s_i)]
    out[k] = torch.cat([fi * t[k].float() for fi, t in zip(f, T)], 0).float()
    out[kb] = torch.cat([math.copysign(fi, w) * t[kb].float() for fi, (_, w), t in zip(f, MIX, T)], 1).float()
for k in [x for x in out if x.endswith("lora_A.weight")][:4]:
    kb = k.replace("lora_A", "lora_B")
    ref = sum(w * si * (t[kb].float() @ t[k].float()) for (_, w), si, t in zip(MIX, s_i, T))
    new = s * (out[kb].float() @ out[k].float())
    chk[k] = float((ref - new).abs().max() / ref.abs().max())
R = sum(c["r"] for c in cfgs)
save_file(out, str(o / "adapter_model.safetensors"), metadata={"format": "pt"})
c = dict(cfgs[0]); c.update(r=R, lora_alpha=float(R))
(o / "adapter_config.json").write_text(json.dumps(c, indent=1))
for fn in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
    if (MIX[0][0] / fn).exists():
        shutil.copy(MIX[0][0] / fn, o / fn)
(o / "b50_adapter.json").write_text(json.dumps({"mix": [[str(d), w] for d, w in MIX], "r": R, "rel_max_diff_delta": chk}, indent=1))
print("b50 adapter r", R, "rel diff (bf16)", max(chk.values()))
