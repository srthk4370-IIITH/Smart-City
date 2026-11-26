"""test_cheap_arm.py: the Python port of Go isolatedReport against the Go-produced reports stored in proofs/2026-10-16_hw_grid/workload_*.json
(sensors + domain-agent calls in, Go 'deterministic (related domains verified steady)' report out). Exit 1 on any difference."""
import glob, json, sys
import pcase as P
ok = bad = 0
for f in sorted(glob.glob(P.C.Q + "/proofs/2026-10-16_hw_grid/workload_*.json")):
    d = json.load(open(f))
    fin = d["final"]
    if not fin or not str(fin.get("model", "")).startswith("deterministic (related domains verified steady)"):
        continue
    calls_by = {a["ref"]: a for a in d["agents"]}
    sens, calls = [], []
    for s in d["sensors"]:
        sens.append(dict(ref=s["ref"], role=s["role"], metric=s["metric"], node=s["node"], loc=s["location"], context=s.get("context", False), rule=s["rule_finding"]))
        a = calls_by.get(s["ref"])
        calls.append((a["parsed"] if a and a.get("parsed") else None, bool(a and a.get("valid"))))
    # Go indexes calls like sensors; the agent list holds only the sensors that had an NPU agent call
    calls = [(None, False) if (c[0] is None) else c for c in calls]
    mine = P.isolated_report(sens, calls)
    g = fin["parsed"]
    diffs = [k for k in ("root_cause", "label", "affected_domains", "evidence", "confidence", "action", "explanation") if mine[k] != g.get(k)]
    print(f.split("/")[-1], "OK" if not diffs else "DIFF %s" % diffs)
    if diffs:
        for k in diffs:
            print("  go  :", g.get(k)); print("  mine:", mine[k])
        bad += 1
    else:
        ok += 1
print("matched", ok, "differed", bad)
sys.exit(1 if bad or not ok else 0)
