"""Exact LoRA form of a delta-space weight mix (merge_mix.py), so training can CONTINUE from the mix.
  mix W0 + sum_i w_i s_i B_i A_i  ==  W0 + s * B A   with  B = [sqrt(w_i s_i / s) B_i]_i (columns), A = [sqrt(w_i s_i / s) A_i]_i (rows),
  rank r = sum r_i, s = lora_alpha / r (kept = s_1). Checked numerically on a few modules (max abs diff of the deltas).
  python mix_to_lora.py --choice <post/TAG/choice.json> --out <adapter dir>
"""
import argparse, json, math, shutil
from pathlib import Path
import torch
from safetensors import safe_open
from safetensors.torch import save_file

ap = argparse.ArgumentParser(); ap.add_argument("--choice", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
mix = json.loads(Path(a.choice).read_text())["mix"]
cfgs, ts = [], []
for ad, w in mix:
    cfgs.append(json.loads((Path(ad) / "adapter_config.json").read_text()))
    with safe_open(str(Path(ad) / "adapter_model.safetensors"), "pt") as f:
        ts.append({k: f.get_tensor(k) for k in f.keys()})
s_i = [c["lora_alpha"] / c["r"] for c in cfgs]
R = sum(c["r"] for c in cfgs); s = s_i[0]
out = {}
for k in ts[0]:
    if not k.endswith("lora_A.weight"):
        continue
    kb = k.replace("lora_A", "lora_B")
    f = [math.sqrt(w * si / s) for (_, w), si in zip(mix, s_i)]
    out[k] = torch.cat([fi * t[k].float() for fi, t in zip(f, ts)], 0).to(ts[0][k].dtype)
    out[kb] = torch.cat([fi * t[kb].float() for fi, t in zip(f, ts)], 1).to(ts[0][kb].dtype)
chk = {}
for k in [x for x in out if x.endswith("lora_A.weight")][:4]:
    kb = k.replace("lora_A", "lora_B")
    ref = sum(w * si * (t[kb].float() @ t[k].float()) for (_, w), si, t in zip(mix, s_i, ts))
    new = s * (out[kb].float() @ out[k].float())
    chk[k] = float((ref - new).abs().max() / ref.abs().max())
o = Path(a.out); o.mkdir(parents=True, exist_ok=True)
save_file(out, str(o / "adapter_model.safetensors"), metadata={"format": "pt"})
cfg = dict(cfgs[0]); cfg["r"] = R; cfg["lora_alpha"] = s * R
(o / "adapter_config.json").write_text(json.dumps(cfg, indent=1))
for fn in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
    if (Path(mix[0][0]) / fn).exists():
        shutil.copy(Path(mix[0][0]) / fn, o / fn)
(o / "mix_to_lora.json").write_text(json.dumps({"mix": mix, "r": R, "scale": s, "rel_max_diff_delta": chk}, indent=1))
print(json.dumps({"r": R, "scale": s, "rel_max_diff_delta": chk}))
