"""Severity agreement between two runs of the same items (owner priority: consistency). py sev_agree.py tagA tagB"""
import json, os, sys
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import score_v3 as S
S.REPAIR = True
a, b = sys.argv[1], sys.argv[2]
for suite in ("rw6", "rwh"):
    if not (os.path.exists(os.path.join(H, "results", a, suite + ".jsonl")) and os.path.exists(os.path.join(H, "results", b, suite + ".jsonl"))):
        continue
    A = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(H, "results", a, suite + ".jsonl"))}
    B = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(H, "results", b, suite + ".jsonl"))}
    same = tot = 0
    for i in A.keys() & B.keys():
        x, y = S.parse((A[i]["final"] or {}).get("content")), S.parse((B[i]["final"] or {}).get("content"))
        if isinstance(x, dict) and isinstance(y, dict):
            tot += 1
            same += x.get("severity") == y.get("severity")
    print("%s vs %s %s severity agreement %d/%d = %.3f" % (a, b, suite, same, tot, same / max(1, tot)))
