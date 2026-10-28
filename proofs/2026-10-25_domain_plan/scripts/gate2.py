"""Sound gate (2026-10-28, replaces the old E2 slice gate, which fails equal models 70-80% of the time):
  per candidate vs mixA50 (+P1 rules, new leak gold): dev3f total net (pattern+status+cause wins - losses) > 0, severity-weighted
  net >= 0, no fixed slice significantly worse (exact sign test, Holm alpha 0.05); E1: net >= 0, safety stories not lower, no
  Holm-worse slice. Winner = best (dev net + E1 net) among passers.  python gate2.py OUT.json TAG...   (prints one line per tag)"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D  # noqa: E402
import diag  # noqa: E402
import pick  # noqa: E402  (E1 safety)
args = sys.argv[2:]
REF_DEV, REF_E1 = "mixA50", "mixA50cuda"
while args and args[0].startswith("--ref-"):
    if args[0] == "--ref-dev":
        REF_DEV = args[1]
    else:
        REF_E1 = args[1]
    args = args[2:]
res, best = {"ref_dev": REF_DEV, "ref_e1": REF_E1}, None
ref = pick.e1(REF_E1)
for t in args:
    r = {}
    try:
        r["dev"] = diag.analyse("dev", D.L.SETS["dev"], REF_DEV, t)
        r["e1"] = diag.analyse("e1", diag.E1, REF_E1, t)
        r["e1_score"] = pick.e1(t)
    except FileNotFoundError as e:
        r["error"] = str(e); res[t] = r; print(t, "missing", e); continue
    dv, e1 = r["dev"], r["e1"]
    ok = (dv["total_net"][0] > 0 and dv["sev_net"][0] >= 0 and not dv["holm_worse_slices"] and e1["total_net"][0] >= 0
          and not e1["holm_worse_slices"] and r["e1_score"] and r["e1_score"]["safety"] >= ref["safety"])
    r["pass"] = ok; res[t] = r
    print(f"{t}: dev net {dv['total_net'][0]:+d} CI[{dv['total_net'][1]:+d},{dv['total_net'][2]:+d}] sev {dv['sev_net'][0]:+d} | E1 net {e1['total_net'][0]:+d} "
          f"safety {r['e1_score']['safety'] if r['e1_score'] else '-'}/{ref['safety']} | Holm-worse {dv['holm_worse_slices'] + e1['holm_worse_slices']} -> {'PASS' if ok else 'FAIL'}", flush=True)
    if ok and (best is None or dv["total_net"][0] + e1["total_net"][0] > best[0]):
        best = (dv["total_net"][0] + e1["total_net"][0], t)
res["winner"] = best[1] if best else None
json.dump(res, open(sys.argv[1], "w"), indent=1, default=str)
print("WINNER", res["winner"])
