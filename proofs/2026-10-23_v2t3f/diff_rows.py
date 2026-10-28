"""Per-row diff of two host-eval sample sets (status/pattern) on chosen slices."""
import json, sys, collections
from pathlib import Path
E = Path.home()/"smartcity_runs/agents_v2_topup3e/eval/eval"
ref, cand = sys.argv[1], sys.argv[2]
L = lambda t: {s["id"]: s for s in map(json.loads, open(E/t/"samples.jsonl"))}
a, b = L(ref), L(cand)
rows = {r["id"]: r for r in map(json.loads, open(E.parent/"eval3e.jsonl"))}
print(list(next(iter(a.values())).keys()))
cnt = collections.Counter()
for i in a:
    if i not in b: continue
    for k in ("pattern", "status"):
        if a[i].get(k) != b[i].get(k):
            g = rows[i]
            m = "W" if b[i].get(k) else "L"
            cnt[(k, m)] += 1
            if k == "status" and m == "L" or (len(sys.argv) > 3 and sys.argv[3] in a[i]["slices"]):
                print(k, m, i, g.get("role"), g.get("topup_bucket"), "| gold", a[i]["gold_pattern"], a[i]["gold_status"],
                      "| ref:", a[i]["text"][:110].replace("\n"," "), "| cand:", b[i]["text"][:110].replace("\n", " "))
print(cnt)
