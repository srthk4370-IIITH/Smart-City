"""ke_gendev.py K2B  -> K2B/mixdata/gendev.jsonl: the continuation's fixed tool+hard dev set (rows of gen_dev5 = dev split, seed 5151, disjoint from the
eval sets): 30 tool turn-1 call rows, 15 direct rows (dyn windows 18/36 pts), 15 tool final rows, 40 hard/weak rows; 'turn' kept (patched trainer scores them)."""
import json
import sys

K = sys.argv[1]
rows = [json.loads(l) for l in open(K + "/gen_dev5/new_full.jsonl") if l.strip()]
keep = ("id", "prompt", "completion", "gold", "family", "role", "stage", "slices", "synthetic", "source", "turn")
call = [r for r in rows if r.get("turn") == "call"][:30]
final = [r for r in rows if r.get("turn") == "final"][:15]
direct = [dict(r, turn="direct") for r in rows if r["family"].startswith("dyn_") and r.get("n") in (18, 36) and not r.get("turn")][:15]
hard = [r for r in rows if r["family"].startswith(("hard_", "weak_"))][:40]
with open(K + "/mixdata/gendev.jsonl", "w", newline="\n") as f:
    for r in call + direct + final + hard:
        f.write(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False) + "\n")
print("gendev: %d call, %d direct, %d final, %d hard" % (len(call), len(direct), len(final), len(hard)))
