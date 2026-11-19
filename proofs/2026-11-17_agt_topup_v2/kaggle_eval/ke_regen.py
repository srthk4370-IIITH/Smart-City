"""ke_regen.py ERRORS.json OUT_MULT.json OUT_DOC.md  -> family multipliers for gen_run.py (FAM_MULT) from the Kaggle eval failures of the latest snapshot.
fail rate per PLAN key (weighted over t1/t2/hard rows of its families): mult = 1 + 2*rate (cap 2.5), 0.8 for keys with >= 5 eval rows and < 10 % failures,
then every multiplier is rescaled so the planned NEW row count stays that of v2 (3965): replay fraction / step count stay as in v2."""
import json
import sys

sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2")
PLAN = {"dyn": 800, "hard_standby": 280, "hard_leak": 280, "hard_night": 240, "hard_plateau": 300, "hard_limits": 360, "hard_ph": 180, "weak": 560,
        "tool_history": 250, "tool_neighbors": 130, "tool_card": 50, "tool_card_neighbors": 35}
ROWS_PER = {k: (2.1 if k.startswith("tool_") else 1.0) for k in PLAN}


def key(f):
    if f.startswith("tool_card_neighbors"):
        return "tool_card_neighbors"
    if f.startswith("tool_card"):
        return "tool_card"
    if f.startswith("tool_neighbors"):
        return "tool_neighbors"
    if f.startswith("tool_history"):
        return "tool_history"
    if f.startswith("dyn"):
        return "dyn"
    if f.startswith("weak"):
        return "weak"
    return f if f in PLAN else None


E = json.load(open(sys.argv[1]))
agg = {}
for sname, fams in E["errors"].items():
    if sname == "val":
        continue
    for f, d in fams.items():
        k = key(f.split("|")[0])
        if k:
            a = agg.setdefault(k, [0, 0])
            a[0] += d["n"]
            a[1] += d["fail"]
mult = {}
for k in PLAN:
    n, b = agg.get(k, (0, 0))
    r = b / n if n else None
    mult[k] = 1.0 if r is None else (0.8 if (n >= 5 and r < 0.10) else min(2.5, 1 + 2 * r))
tot = sum(PLAN[k] * mult[k] * ROWS_PER[k] for k in PLAN)
base = sum(PLAN[k] * ROWS_PER[k] for k in PLAN)
s = base / tot
final = {k: round(mult[k] * s, 3) for k in PLAN}
json.dump(final, open(sys.argv[2], "w"))
L = ["# DATASET_V2B: error-driven top-up data (generated %s)" % __import__("time").strftime("%F %T"), "",
     "Why: the Kaggle eval of the v2 snapshots (latest: %s) was NOT GOOD (see ../data/kaggle_eval/DECISION.md). Failure rates per generator key come from the failed rows of "
     "tool turn 1 (missed or unneeded calls, wrong tool/args), tool final answers and the hard-case slice, by family." % E["latest"], "",
     "| generator key | eval rows | failed | rate | multiplier (raw) | multiplier (rescaled to the v2 new-row total) |", "|---|---|---|---|---|---|"]
for k in PLAN:
    n, b = agg.get(k, (0, 0))
    L.append("| %s | %d | %d | %s | %.2f | %.2f |" % (k, n, b, ("%.2f" % (b / n)) if n else "-", mult[k], final[k]))
L += ["", "What changed vs v2 data: (1) gen_run.py PLAN counts x the multipliers above (env FAM_MULT), more and more varied scenarios of the failing kinds "
      "(new generator seed 2117 -> different random scenarios, windows, values, neighbours; dyn_* rows are the clear 'no call needed' negatives so they are "
      "up-weighted when direct_ok fails); (2) families with < 10 % failures are down-weighted to 0.8 before the rescale; (3) replay stays ~55-58 % of the mix "
      "(real val protection); (4) all checks re-run (check_data_v2.py: schema, tool protocol, gold consistency, leakage, 904+240+136 <= 1280 tokens)."]
open(sys.argv[3], "w", newline="\n").write("\n".join(L) + "\n")
print(json.dumps(final))
