"""Per-layer / per-module mixing for LoRA-scaling screens: split one PEFT adapter into groups (each a PEFT adapter dir
holding only its tensors), so each group gets its own --lora-scaled weight (HMA-style per-layer alpha).
  python split_lora.py ADAPTER OUTPREFIX --groups lo:0-9 mid:10-18 hi:19-27 [attn mlp]
  group "a-b" = decoder layers a..b (all modules); "attn" / "mlp" = all layers, attention / MLP projections only.
"""
import argparse, json, re, shutil
from pathlib import Path
from safetensors import safe_open
from safetensors.torch import save_file
ap = argparse.ArgumentParser(); ap.add_argument("adapter"); ap.add_argument("outprefix"); ap.add_argument("--groups", nargs="+", required=True)
a = ap.parse_args()
src = Path(a.adapter)
with safe_open(str(src / "adapter_model.safetensors"), "pt") as f:
    T = {k: f.get_tensor(k) for k in f.keys()}
for g in a.groups:
    name, spec = g.split(":") if ":" in g else (g, g)
    if spec in ("attn", "mlp"):
        keep = lambda k: (".self_attn." in k) == (spec == "attn")
    else:
        lo, hi = map(int, spec.split("-"))
        keep = lambda k, lo=lo, hi=hi: lo <= int(re.search(r"\.layers\.(\d+)\.", k).group(1)) <= hi
    out = Path(f"{a.outprefix}_{name}"); out.mkdir(parents=True, exist_ok=True)
    sub = {k: v for k, v in T.items() if keep(k)}
    save_file(sub, str(out / "adapter_model.safetensors"), metadata={"format": "pt"})
    shutil.copy(src / "adapter_config.json", out / "adapter_config.json")
    (out / "split.json").write_text(json.dumps({"from": str(src), "group": g, "n_tensors": len(sub)}))
    print(out, len(sub))
