"""Pick the phase-1 checkpoint that phase 2 starts from: among phase-1 evaluated steps that pass
(original dev loss <= 1.02 x baseline AND targeted dev loss < baseline), the LOWEST ORIGINAL dev loss.
Writes <run2>/init_choice.json and <run2>/train_args.txt = train_args.base + --init-adapter <dir>.
Keeps an existing --init-adapter (a resumed run must not change its start point).

  python pick_init.py agents_v2_topup2 agents_v2_topup3
"""
import json
import sys
from pathlib import Path

R = Path.home() / "smartcity_runs"
src, dst = R / sys.argv[1], R / sys.argv[2]
ta = dst / "train_args.txt"
if ta.exists() and "--init-adapter" in ta.read_text():
    print("keeping", ta.read_text().strip())
    sys.exit(0)
base = json.loads((src / "baseline.json").read_text())
plan = json.loads((src / "plan.json").read_text())
rows = [json.loads(l) for l in open(src / "evals.jsonl")]
rows = [r for r in rows if r["step"] > 0 and "eval_orig_loss" in r and "eval_target_loss" in r]
ok = [r for r in rows if r["eval_orig_loss"] <= 1.02 * base["eval_orig_loss"] and r["eval_target_loss"] < base["eval_target_loss"]]
if not ok:
    sys.exit("no passing phase-1 step")
pick = min(ok, key=lambda r: (r["eval_orig_loss"], r["eval_target_loss"]))
s = pick["step"]
d = src / "checkpoints" / f"checkpoint-{s}"
if not (d / "adapter_model.safetensors").exists():
    d = src / "adapter"
assert (d / "adapter_model.safetensors").exists(), d
res = {"from_run": str(src), "step": s, "adapter_dir": str(d), "picked": pick, "baseline": base, "candidates": rows,
       "rule": "phase-1 passing steps (orig <= +2 %, targeted improved); lowest original dev loss"}
(dst / "init_choice.json").write_text(json.dumps(res, indent=1))
extra = (dst / "train_args.base").read_text().strip()
ta.write_text(f"{extra} --init-adapter {d} --init-step {4494 + s}\n")  # 4494 v2 steps + phase-1 steps
print(json.dumps({"step": s, "adapter_dir": str(d), "orig": pick["eval_orig_loss"], "target": pick["eval_target_loss"]}))
