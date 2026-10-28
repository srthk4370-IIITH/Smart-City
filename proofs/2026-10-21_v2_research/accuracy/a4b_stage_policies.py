"""Stage-aware post-hoc fixes: applied ONLY at the 1.5 h / 3 h refinements (the early 40 min call is untouched), using
the rule detector on the LAST 4 h (rule48 = rules.go on 48 points, its design length) whatever the ladder window is.
Writes stage_policies.md."""
import json, random
from collections import Counter, defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
rows = json.load(open(HERE / "a1_rows.json"))
F = {(f["id"], f["d"], f["n"]): f for f in json.load(open(HERE / "a3_series_feats.json"))}
R = {(r["id"], r["d"], r["n"]): {**r, "rule48": F[(r["id"], r["d"], r["n"])]["rule48"], "tail": F[(r["id"], r["d"], r["n"])]["tail_frac"]} for r in rows}
LAB = {"stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase", "step_decrease", "exponential_increase", "oscillation", "throttling", "flatline", "erratic"}
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}
ev = sorted({r["id"] for r in rows if not r["clean"]}); cl = sorted({r["id"] for r in rows if r["clean"]})
T = {r["id"]: r["truth"] for r in rows}
conf = lambda r: r["conf"] if isinstance(r["conf"], (int, float)) else 0.0

def fx_invalid(r, p):   # off-label / garbage -> (retry would be the real fix) fall back to the rule's label
    return p if p in LAB else r["rule48"]
def fx_flat(r, p):      # 4 h rules say flatline (>= 16 identical readings) and the model reads a trend/step
    return "flatline" if r["rule48"] == "flatline" and p in ("gradual_decrease", "gradual_increase", "step_decrease", "step_increase") else p
def fx_exp(r, p):       # low-confidence gradual_increase but the 4 h rules say exponential
    return "exponential_increase" if p == "gradual_increase" and r["rule48"] == "exponential_increase" and conf(r) <= 0.5 else p
FIX = {"none": [], "invalid": [fx_invalid], "invalid+flat": [fx_invalid, fx_flat], "invalid+flat+exp": [fx_invalid, fx_flat, fx_exp]}

def apply(r, fixes, stage_refine):
    p = r["pred"]
    if fixes and fixes[0] is fx_invalid: p = fx_invalid(r, p)
    if stage_refine:
        for f in fixes[1:]: p = f(r, p)
    return p

def chain(fixes, i, fixed=None):
    e = R[(i, 8, 48)]; ep = apply(e, fixes, False)
    n1 = fixed or LAD.get(e["status"], 48); r1 = R[(i, 18, n1)]; p1 = apply(r1, fixes, True)
    if ep in ("spike", "dip") and p1 == "stable": p1 = ep
    n2 = fixed or max(LAD.get(e["status"], 48), LAD.get(r1["status"], 48)); r2 = R[(i, 36, n2)]; p2 = apply(r2, fixes, True)
    if ep in ("spike", "dip") and p2 == "stable": p2 = ep
    return ep, p1, p2

out = ["| fixes | 40 min (early, n=48) | 1.5 h chain | 3 h chain (app ladder) | 3 h plain n=48 | 3 h plain n=96 | 3 h plain n=144 | clean: refine-stage pattern != stable n=48/96/144 |", "|---|---|---|---|---|---|---|---|"]
res = {}
for name, fx in FIX.items():
    c = [chain(fx, i) for i in ev]
    a40 = sum(c[k][0] == T[i] for k, i in enumerate(ev)) / len(ev)
    a90 = sum(c[k][1] == T[i] for k, i in enumerate(ev)) / len(ev)
    a3 = sum(c[k][2] == T[i] for k, i in enumerate(ev)) / len(ev)
    pl = {n: sum(apply(R[(i, 36, n)], fx, True) == T[i] for i in ev) / len(ev) for n in (48, 96, 144)}
    fl = [sum(apply(R[(i, 0, n)], fx, True) != "stable" for i in cl) for n in (48, 96, 144)]
    res[name] = dict(a40=a40, a90=a90, a3_chain=a3, a3_plain=pl, clean_flag=fl)
    out.append(f"| {name} | {a40:.3f} | {a90:.3f} | {a3:.3f} | {pl[48]:.3f} | {pl[96]:.3f} | {pl[144]:.3f} | {fl} |")
# per pattern at 3 h chain for best
best = FIX["invalid+flat+exp"]; base = FIX["none"]
pp = defaultdict(lambda: [0, 0, 0])
for i in ev:
    pp[T[i]][0] += chain(base, i)[2] == T[i]; pp[T[i]][1] += chain(best, i)[2] == T[i]; pp[T[i]][2] += 1
out.append("\n3 h chain per pattern, baseline -> invalid+flat+exp: " + ", ".join(f"{p} {a}->{b}/{n}" for p, (a, b, n) in sorted(pp.items())))
# what changed where (to spot harm)
ch = Counter()
for i in ev:
    for k, (a, b) in enumerate(zip(chain(base, i), chain(best, i))):
        if a != b: ch[(("40m", "1.5h", "3h")[k], T[i], a, b)] += 1
out.append("\nchanged labels (stage, truth, before, after): " + "; ".join(f"{k}: {v}" for k, v in ch.most_common()))
rnd = random.Random(7); ds = []
cb = {i: chain(base, i)[2] == T[i] for i in ev}; cf = {i: chain(best, i)[2] == T[i] for i in ev}
for _ in range(4000):
    s = [rnd.choice(ev) for _ in ev]; ds.append(sum(cf[i] - cb[i] for i in s) / len(s))
ds.sort(); out.append(f"\nbootstrap 95% CI of the 3 h chain gain: [{ds[100]:+.3f}, {ds[3900]:+.3f}]  (in-sample: thresholds chosen on this set; confirm on a fresh seed)")
(HERE / "stage_policies.md").write_text("# Stage-aware post-hoc fixes (simulated on device outputs)\n\n" + "\n".join(out), encoding="utf-8")
json.dump(res, open(HERE / "a4b_results.json", "w"), indent=1)
print("\n".join(out))
