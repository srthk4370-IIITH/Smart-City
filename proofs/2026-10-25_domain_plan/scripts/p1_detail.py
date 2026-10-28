import sys, json
from collections import Counter
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import dp_lib as D, p1_rules as P
out = {}
for ds in ("dev", "rw5dev", "test", "rw5test"):
    d = D.L.SETS[ds]; rows = D.load_rows(d / "eval3e.jsonl"); ids = P.regold(rows)
    S = D.load_samples(d / "eval/mixA50/samples.jsonl")
    A = D.ruled(rows, S, D.expand("ALL")); B = D.ruled(rows, S, D.expand("ALL_P1"))
    rc = Counter(c[0] for i, (s, ch) in B.items() for c in ch if c[0] in ("rel_level_p1", "water_cause_p1", "hvac_rule") and c not in A[i][1])
    diff = [(i, rows[i].get("family"), rows[i].get("sub"), A[i][0]["pred"].get("status") if A[i][0].get("pred") else None, B[i][0]["pred"].get("status"), B[i][0]["gold_status"], B[i][0]["status"]) for i in B if A[i][0].get("pred") != B[i][0].get("pred")]
    out[ds] = {"regold": [(i, rows[i].get("family"), rows[i].get("sub")) for i in ids], "rule_changes": rc, "diff": diff}
    print(ds, "regold", [(rows[i].get("family"), rows[i].get("sub")) for i in ids], "| changes", dict(rc), "| diff rows", len(diff), [x[1:] for x in diff][:8])
json.dump(out, open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e2/p1_detail.json", "w"), indent=1, default=str)
