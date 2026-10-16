"""Paired McNemar tests (same cases at each length): does length X flag/answer differently from 48 pts?"""
import json, math, sys
from collections import defaultdict
sys.path.insert(0, r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\training\window_study")
import window_study as W
cases = {c["id"]: c for c in map(json.loads, open("cases.jsonl", encoding="utf-8"))}
rows = [json.loads(l) for l in open("samples.jsonl", encoding="utf-8")]
by = defaultdict(dict)
for r in rows:
    p = W.parse(r["text"]); c = cases[r["id"]]
    t = c["truth"]
    by[r["id"]][r["n"]] = {"flag": W.flagged(p), "pat": bool(p and t and p["pattern"] == t["pattern"])}
def mcnemar(b, c):
    n = b + c
    if n == 0: return 1.0
    k = min(b, c)  # exact two-sided binomial
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
out = []
groups = {"step_old": "flag", "drift_long": "flag", "subthr_spikes": "flag",
          "classic_*": "pat", "clean(truth normal)": "flag"}
for g, key in groups.items():
    ids = [i for i, c in cases.items() if (c["family"].startswith("classic") if g == "classic_*" else
           (c["family"] == "clean" and c["truth"]["status"] == "normal") if g.startswith("clean") else c["family"] == g)]
    for n in (24, 96, 144):
        b = sum(1 for i in ids if by[i][48][key] and not by[i][n][key])
        c_ = sum(1 for i in ids if by[i][n][key] and not by[i][48][key])
        out.append(f"{g:22s} {key:4s} 48 vs {n:3d}: only48={b:3d} only{n}={c_:3d}  n={len(ids)}  p={mcnemar(b, c_):.4f}")
print("\n".join(out)); open("paired_tests.txt", "w").write("\n".join(out) + "\n")
