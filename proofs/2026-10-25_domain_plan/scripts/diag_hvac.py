import sys; sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
from collections import Counter
import dp_lib as D, p1_rules as P
d = D.L.SETS["dev"]; rw = D.load_rows(d / "eval3e.jsonl"); P.regold(rw); R = D.expand("ALL_P1")
ref = {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / "eval/mixA50/samples.jsonl"), R).items()}
c = {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / "eval/P3W06/samples.jsonl"), R).items()}
lost, won, roles = Counter(), Counter(), Counter()
for i in ref:
    a, b = ref[i], c[i]; n = sum(bool(b[k]) - bool(a[k]) for k in ("pattern", "status", "cause"))
    if n: roles[(rw[i]["role"], "win" if n > 0 else "loss")] += 1
    if rw[i]["role"] != "hvac" or n == 0: continue
    key = f"gold {a['gold_pattern']}/{a['gold_status']}: ref {a['pred'].get('pattern')} -> p3 {b['pred'].get('pattern')}/{b['pred'].get('status')}"
    (lost if n < 0 else won)[key] += 1
print("by role", dict(roles)); print("HVAC losses", lost.most_common(8)); print("HVAC wins", won.most_common(4))
print("hvac n", sum(1 for r in rw.values() if r["role"] == "hvac"), "gold mix", Counter(r["pattern"] for r in rw.values() if r["role"] == "hvac").most_common(8))
