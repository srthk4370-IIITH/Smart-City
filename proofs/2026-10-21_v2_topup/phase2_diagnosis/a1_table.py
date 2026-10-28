import json, sys
P = sys.argv[1]
rows = [json.loads(l) for l in open(P + "/decision_metrics.jsonl")]
order = ["v2_4494", "p1_ckpt500", "p2_ckpt25", "p2_ckpt50", "p2_ckpt100", "p2_ckpt150"]
sets = ["orig", "early", "s15h", "s3h", "other"]
M = {(r["adapter"], r["set"]): r for r in rows}
L = ["# A1 decision-level metrics (teacher-forced: pattern = exact greedy first decision; status conditioned on gold pattern; cause/event_active conditioned on gold observations)\n"]
for k in ("loss_all", "loss_decision", "acc_pattern", "acc_status", "acc_likely_cause", "acc_event_active"):
    L.append(f"\n## {k}\n| adapter | " + " | ".join(sets) + " |\n|---|" + "---|" * len(sets) + "\n")
    for a in order:
        L.append(f"| {a} | " + " | ".join(str(M[(a, s)][k]) if (a, s) in M else "" for s in sets) + " |\n")
open(P + "/a1_decision_metrics.md", "w").write("".join(L))
print("".join(L))
