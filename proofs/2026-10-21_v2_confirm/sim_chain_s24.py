"""App-chain simulation of the refinement window policy on the fresh seed-24 placement set (device outputs).
Early call d=8 (40 min) at 4 h; 1.5 h refine d=18 and 3 h refine d=36 at the window each policy picks; the app's
keep rule (early spike/dip kept when the refined call says stable). Policies: old severity ladder, fixed 4 h,
WindowN (features_v2.go, 2026-10-21: shape family x stage, stable-yet-abnormal -> unrecognised). Onset age at
d <= 36 needs <= 48 readings, so the onset rule never lengthens a window here.
  py -3 sim_chain_s24.py"""
import json, math
from collections import Counter, defaultdict
from pathlib import Path
H = Path(__file__).resolve().parent / "placement_s24"
truth = {}
for l in open(H / "prompts.jsonl"):
    r = json.loads(l); truth[r["id"]] = r["truth"]
S = {}
for l in open(H / "samples.jsonl"):
    r = json.loads(l)
    try:
        o = json.loads(r["text"]); p, s = o.get("pattern"), o.get("status")
    except Exception:
        p = s = None
    S[(r["id"], r["d"], r["n"])] = (p, s)
FAM = {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
       "stable": "stable", "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
       "step_increase": "step", "step_decrease": "step", "throttling": "step"}
RANK = {"critical": 3, "warning": 2, "sensor_fault": 1, "normal": 0}
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}

def windown(stage, early_p, status):
    f = FAM.get(early_p, "invalid")
    if f == "stable" and RANK.get(status, 0) >= 2:
        f = "invalid"
    if status == "sensor_fault":
        return 144 if f in ("flat", "noisy") else 96
    if f == "flat": return 144
    if f in ("transient", "invalid"): return 96
    if f == "step" and stage == "3h": return 96
    if f == "noisy" and stage == "3h": return 144
    return 48

POL = {
    "old severity ladder": lambda st, e, prev: max(LAD.get(e[1], 48), LAD.get(prev[1], 48)),
    "fixed 4 h": lambda st, e, prev: 48,
    "WindowN (new)": lambda st, e, prev: windown(st, e[0], "sensor_fault" if prev[1] == "sensor_fault" else prev[1]),
}
def wil(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return f"{100*p:.1f}% [{100*(c-h)/d:.0f}-{100*(c+h)/d:.0f}] n={n}"
ids = sorted(i for i, t in truth.items() if not t.get("clean"))
out = {}
for name, pick in POL.items():
    ok1 = ok2 = 0; per = defaultdict(lambda: [0, 0]); ns = []
    for i in ids:
        e = S.get((i, 8, 48))
        if not e: continue
        n1 = pick("1.5h", e, e); r1 = S.get((i, 18, n1), (None, None)); p1 = r1[0]
        if e[0] in ("spike", "dip") and p1 == "stable": p1 = e[0]
        n2 = pick("3h", e, r1); r2 = S.get((i, 36, n2), (None, None)); p2 = r2[0]
        if e[0] in ("spike", "dip") and p2 == "stable": p2 = e[0]
        t = truth[i]["pattern"]
        ok1 += p1 == t; ok2 += p2 == t; per[t][0] += p2 == t; per[t][1] += 1; ns.append(n2)
    N = len(ns)
    out[name] = {"1.5h": wil(ok1, N), "3h": wil(ok2, N), "mean_n_3h": round(sum(ns)/N, 1),
                 "per_pattern_3h": {k: f"{a}/{b}" for k, (a, b) in sorted(per.items())}}
    print(f"{name:22} 1.5h {out[name]['1.5h']:28} 3h {out[name]['3h']:28} mean n@3h {out[name]['mean_n_3h']}")
# paired: new vs old ladder at 3 h
def res(pick):
    r = {}
    for i in ids:
        e = S.get((i, 8, 48)); r1 = S.get((i, 18, pick("1.5h", e, e)), (None, None))
        p2 = S.get((i, 36, pick("3h", e, r1)), (None, None))[0]
        if e[0] in ("spike", "dip") and p2 == "stable": p2 = e[0]
        r[i] = p2 == truth[i]["pattern"]
    return r
a, b = res(POL["WindowN (new)"]), res(POL["old severity ladder"])
nb, bn = sum(a[i] and not b[i] for i in ids), sum(b[i] and not a[i] for i in ids)
from math import comb
k, n = min(nb, bn), nb + bn
p = min(1, 2 * sum(comb(n, j) for j in range(k + 1)) / 2**n) if n else 1
print(f"paired 3 h, new-only right {nb}, old-only right {bn}, exact McNemar p={p:.3f}")
out["paired_3h_new_vs_old"] = {"new_only": nb, "old_only": bn, "p": round(p, 4)}
json.dump(out, open(H.parent / "sim_chain_s24.json", "w"), indent=1)
for k in out:
    if "per_pattern_3h" in out[k]: print(k, out[k]["per_pattern_3h"])
