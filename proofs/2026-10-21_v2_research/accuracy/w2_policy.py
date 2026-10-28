"""Hand-simplified window policy (from w1 A2/A4/A5) evaluated through the app chain on events AND on clean windows
(false alarms at refinement), vs the current LadderN. Writes window_policy.json (the recommendation)."""
import json, math
from pathlib import Path
from collections import Counter
HERE = Path(__file__).resolve().parent
rows = json.load(open(HERE / "a1_rows.json")); R = {(r["id"], r["d"], r["n"]): r for r in rows}
ev = sorted({r["id"] for r in rows if not r["clean"]}); cl = sorted({r["id"] for r in rows if r["clean"]})
T = {r["id"]: r["truth"] for r in rows}
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}
FAM = {"spike": "transient", "dip": "transient", "step_increase": "step", "step_decrease": "step", "throttling": "step",
       "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
       "oscillation": "noisy", "erratic": "noisy", "flatline": "flat", "stable": "stable"}
def wil(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)); return [round(p,3), round((c-h)/d,3), round((c+h)/d,3), n]
def ladder(d, e, prev): return max(LAD.get(e["status"], 48), LAD.get(prev["status"], 48))
POLICY = {   # stage -> early-call pattern family -> n ; sensor_fault status overrides to 144
    18: {"transient": 96, "step": 48, "trend": 48, "noisy": 48, "flat": 144, "stable": 48, "invalid": 96},
    36: {"transient": 96, "step": 96, "trend": 48, "noisy": 144, "flat": 144, "stable": 48, "invalid": 96}}
def simple(d, e, prev):
    f = FAM.get(e["pred"], "invalid")
    if e["status"] == "sensor_fault" or prev["status"] == "sensor_fault":
        return 144 if f in ("flat", "noisy") else 96
    return POLICY[d][f]
def chain(i, pick):
    e = R[(i, 8, 48)]; ep = e["pred"]
    n1 = pick(18, e, e); r1 = R[(i, 18, n1)]; p1, s1 = r1["pred"], r1["status"]
    if ep in ("spike", "dip") and p1 == "stable": p1 = ep
    n2 = pick(36, e, r1); r2 = R[(i, 36, n2)]; p2, s2 = r2["pred"], r2["status"]
    if ep in ("spike", "dip") and p2 == "stable": p2 = ep
    return p1, p2, n1, n2, s1, s2
def chain_clean(i, pick):   # a clean sensor stays calm: every stage reads the same calm window (d=0) at length n
    e = R[(i, 0, 48)]
    n1 = pick(18, e, e); r1 = R[(i, 0, n1)]; n2 = pick(36, e, r1); r2 = R[(i, 0, n2)]
    return r1["status"], r2["status"], r1["pred"], r2["pred"], e["status"]
res = {}
for name, pk in (("current LadderN", ladder), ("recommended (family x stage)", simple), ("fixed 4 h", lambda d, e, p: 48)):
    c = [chain(i, pk) for i in ev]
    a1 = sum(x[0] == T[i] for x, i in zip(c, ev)); a2 = sum(x[1] == T[i] for x, i in zip(c, ev))
    cc = [chain_clean(i, pk) for i in cl]
    alarmed = [x for x in cc if x[4] != "normal"]          # only early-alarmed clean windows get refined in the app
    fa3 = sum(x[1] != "normal" for x in alarmed)
    res[name] = {"pattern_1_5h": wil(a1, len(ev)), "pattern_3h": wil(a2, len(ev)), "mean_n_3h": round(sum(x[3] for x in c)/len(c)),
                 "clean_early_false_alarms_still_alarming_at_3h": f"{fa3}/{len(alarmed)}",
                 "clean_all_status_not_normal_3h": f"{sum(x[1] != 'normal' for x in cc)}/{len(cc)}"}
    per = Counter(); tot = Counter()
    for x, i in zip(c, ev): tot[T[i]] += 1; per[T[i]] += x[1] == T[i]
    res[name]["per_pattern_3h"] = {p: f"{per[p]}/{tot[p]}" for p in sorted(tot)}
# paired McNemar recommended vs ladder at 3 h and 1.5 h
def mcn(b, c):
    n = b + c; return 1.0 if n == 0 else min(1.0, 2*sum(math.comb(n, k) for k in range(min(b, c)+1))/2**n)
for st, idx in (("1.5h", 0), ("3h", 1)):
    A = [chain(i, ladder)[idx] == T[i] for i in ev]; B = [chain(i, simple)[idx] == T[i] for i in ev]
    b = sum(a and not bb for a, bb in zip(A, B)); c = sum(bb and not a for a, bb in zip(A, B))
    res[f"mcnemar_recommended_vs_ladder_{st}"] = {"ladder_only_right": b, "recommended_only_right": c, "p": round(mcn(b, c), 3)}
pol = {
  "status": "RECOMMENDATION from device data (placement_v2, Q4_0 htpd); policy partly tuned on the same 183 events (CV estimate in window_study.md A5) -> confirm on a fresh placement seed before shipping",
  "inputs_at_runtime": "stage (early / refine 1.5 h / refine 3 h), the EARLY call's pattern family and status, the previous stage's status",
  "early": {"n": 48, "all_cases": True, "why": "40 min: 4 h 74% vs 8 h 75% vs 12 h 70% (ns); 4 h has the fewest clean false alarms (18% vs 29%/27%)"},
  "refine_1_5h": {"by_early_family": POLICY[18], "sensor_fault": "144 if early family flat/noisy else 96"},
  "refine_3h": {"by_early_family": POLICY[36], "sensor_fault": "144 if early family flat/noisy else 96"},
  "families": {k: sorted(p for p, f in FAM.items() if f == k) for k in set(FAM.values())},
  "constraints": [
    "window must contain the onset plus >= 1 h of pre-onset baseline: n >= d + 12. Training never shows an event family whose onset is older than the window (sample_d <= n); only old_shift/long_drift/recurring reach outside, and only via the E9/E10 12 h lines (they score 94-100% there). With the stage times used (d <= 36) every n >= 48 satisfies it; if refinements are ever later than 3 h, raise n.",
    "do not escalate to 12 h by severity alone: critical/warning early status did NOT do better at 12 h (A3: warning 3 h 89/84/73% for 4/8/12 h; critical 76/79/82% ns)",
    "trend family (gradual/exponential): keep 4 h at every stage (3 h: 90/80/72% for 4/8/12 h; 1.5 h 86/72/76%)",
    "transient (spike/dip) at refinement: 8 h (3 h: 80/93/89%) - the 3 h-old spike sits at the edge of a 4 h window",
    "flat / sensor_fault: 12 h (3 h: 90/95/100%)",
    "noisy (erratic/oscillation): 12 h at 3 h (n=11, 82/82/100%) - weak evidence; erratic by true class 57/86/81%",
    "number of flagged sensors: not derivable from these single-sensor data; no evidence either way - do not use it until an app-level multi-sensor run measures it"],
  "evaluation_through_app_chain": res}
json.dump(pol, open(HERE / "window_policy.json", "w"), indent=1)
print(json.dumps(res, indent=1))
