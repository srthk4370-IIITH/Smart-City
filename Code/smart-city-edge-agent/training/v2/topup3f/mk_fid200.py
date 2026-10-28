"""fid200: 200 random rows (seed 3) of the 1,148-row test set, for the LoRA-scaling fidelity check; v2cuda and the old
merged-mixA50 samples on those rows are copied as references (v2cuda / mixA50_old)."""
import json, random
from pathlib import Path
R = Path.home() / "smartcity_runs/agents_v2_topup3f"; T = R / "eval_test"; F = R / "eval_fid200"
rows = [json.loads(l) for l in open(T / "eval3e.jsonl", encoding="utf-8")]
ids = set(r["id"] for r in random.Random(3).sample(rows, 200))
(F / "eval").mkdir(parents=True, exist_ok=True)
with open(F / "eval3e.jsonl", "w", encoding="utf-8") as fh:
    for r in rows:
        if r["id"] in ids:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
for src, dst in (("v2cuda", "v2cuda"), ("mixA50", "mixA50_old")):
    (F / "eval" / dst).mkdir(exist_ok=True)
    with open(F / "eval" / dst / "samples.jsonl", "w", encoding="utf-8") as fh:
        for l in open(T / "eval" / src / "samples.jsonl", encoding="utf-8"):
            if json.loads(l)["id"] in ids:
                fh.write(l)
print(len(ids), sum(1 for _ in open(F / "eval/v2cuda/samples.jsonl")), sum(1 for _ in open(F / "eval/mixA50_old/samples.jsonl")))
