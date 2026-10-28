"""Young-window comparison on the gate-study windows: CAND vs REF (same 440 events), live P1 rules. Paired all-3 difference
for young windows (k = 3..7) and for k = 8, bootstrap 95% CI over events.  python yw_compare.py REF CAND OUT.json -> 1 line
Improves = young-window diff > 0 with CI lower bound > 0, and k=8 diff CI upper bound >= 0 (not significantly worse)."""
import json, random, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import dp_lib as D  # noqa: E402
import p1_rules as P  # noqa: E402
G = Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study")
ref_t, cand_t, out = sys.argv[1:4]
rows = D.load_rows(G / "eval3e.jsonl"); P.regold(rows)
R = D.expand("ALL_P1")
A = {i: v[0] for i, v in D.ruled(rows, D.load_samples(G / "eval" / ref_t / "samples.jsonl"), R).items()}
B = {i: v[0] for i, v in D.ruled(rows, D.load_samples(G / "eval" / cand_t / "samples.jsonl"), R).items()}
ok = lambda s: bool(s["pattern"] and s["status"] and s["cause"])
young, old = defaultdict(list), defaultdict(list)
for i in A:
    if i in B:
        (young if rows[i]["k"] <= 7 else old)[rows[i]["group"]].append(ok(B[i]) - ok(A[i]))
rng = random.Random(5)


def stat(dd):
    gs = list(dd)
    per = [sum(dd[g]) / len(dd[g]) for g in gs]
    bs = sorted(sum(per[rng.randrange(len(per))] for _ in per) / len(per) for _ in range(2000))
    return round(100 * sum(per) / len(per), 2), round(100 * bs[50], 2), round(100 * bs[1949], 2)


y, k8 = stat(young), stat(old)
res = {"ref": ref_t, "cand": cand_t, "young_k3_7_pts": y, "k8_pts": k8, "improves": y[1] > 0 and k8[2] >= 0}
json.dump(res, open(out, "w"), indent=1)
print(f"{cand_t} vs {ref_t}: young k3-7 {y[0]:+.1f} pts CI[{y[1]:+.1f},{y[2]:+.1f}] | k8 {k8[0]:+.1f} CI[{k8[1]:+.1f},{k8[2]:+.1f}] -> {'IMPROVES' if res['improves'] else 'no'}")
