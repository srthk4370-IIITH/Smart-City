"""Write the exact prompt sets for the host GGUF run (Windows, py -3):
  prompts_host400.jsonl   frozen host400 eval set (proofs/2026-10-20_v2_post/eval_set.json, data/sft_v2/test.jsonl)
  prompts_place.jsonl     seed-24 placement rows used by the app chain: (d,n) in {(0,48),(4,48),(8,48)} + d in {18,36} x n in {48,96,144}
Each line: {"key", "set", "prompt"} (+ id/d/n). The generator (gen_host.py, WSL) appends C.PREFILL itself."""
import json, sys
from pathlib import Path
Q = Path(r"C:\Users\hp\Desktop\qidk")
sys.path.insert(0, str(Q / "Code/smart-city-edge-agent/training/v2/post"))
import common_v2 as C
out = Path(__file__).resolve().parent
ids = json.loads((Q / "proofs/2026-10-20_v2_post/eval_set.json").read_text())["ids"]
by = {r["id"]: r for r in C.read_jsonl(C.DATA / "test.jsonl")}
with open(out / "prompts_host400.jsonl", "w", encoding="utf-8") as f:
    for i in ids:
        f.write(json.dumps({"key": f"h|{i}", "set": "host400", "id": i, "prompt": by[i]["prompt"]}) + "\n")
keep = lambda d, n: (d, n) in {(0, 48), (4, 48), (8, 48)} or d in (18, 36)
n = 0
with open(out / "prompts_place.jsonl", "w", encoding="utf-8") as f:
    for l in open(Q / "proofs/2026-10-21_v2_confirm/placement_s24/prompts.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if keep(p["d"], p["n"]):
            f.write(json.dumps({"key": f"p|{p['id']}|{p['d']}|{p['n']}", "set": "place", "id": p["id"], "d": p["d"], "n": p["n"],
                                "prompt": p["prompt"]}) + "\n"); n += 1
print(len(ids), n)
