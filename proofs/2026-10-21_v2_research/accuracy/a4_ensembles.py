"""Cheap post-hoc fixes simulated on the device outputs (no new model calls):
  - app-chain simulation (early 4 h at d=8 -> refine 1.5 h d=18 -> refine 3 h d=36, ladder window by severity,
    refine.go eventOver keep-early-spike/dip rule)
  - rule detector accuracy (v1 rule_pattern = app rules.go) and rule/model override policies, confidence-gated
  - multi-window vote at the 3 h refinement
Every policy is scored on the 3 h events (primary), the 40 min events (must not drop) and the 100 clean windows
(pattern flag must not rise). Writes ensembles.md + a4_results.json."""
import json, random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = json.load(open(HERE / "a1_rows.json"))
feats = {(f["id"], f["d"], f["n"]): f for f in json.load(open(HERE / "a3_series_feats.json"))}
R = {(r["id"], r["d"], r["n"]): {**r, **{k: v for k, v in feats[(r["id"], r["d"], r["n"])].items() if k in ("rule", "rule48", "tail_frac", "rnoise", "zc", "s0")}} for r in rows}
QUIET = {"stable"}
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}
ids_ev = sorted({r["id"] for r in rows if not r["clean"]})
ids_cl = sorted({r["id"] for r in rows if r["clean"]})
truth = {r["id"]: r["truth"] for r in rows}
out = []


def acc(pred, ids):
    return sum(pred[i] == truth[i] for i in ids) / len(ids)


def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** .5
    return (round((c - h) / d, 3), round((c + h) / d, 3))


# ---------------------------------------------------------------- 1. app chain
def app_chain(policy, ids, fixed_n=None):
    """returns {id: (pattern_at_3h, n_used)}; policy(row)->pattern (post-hoc fix applied to each call)."""
    res = {}
    for i in ids:
        e = R[(i, 8, 48)]; ep = policy(e); es = e["status"]
        n1 = fixed_n or LAD.get(es, 48)
        r1 = R[(i, 18, n1)]; p1 = policy(r1); s1 = r1["status"]
        if ep in ("spike", "dip") and p1 == "stable": p1 = ep
        worse = max(LAD.get(es, 48), LAD.get(s1, 48))
        n2 = fixed_n or worse
        r2 = R[(i, 36, n2)]; p2 = policy(r2)
        if ep in ("spike", "dip") and p2 == "stable": p2 = ep
        res[i] = (p2, n2)
    return res


base = lambda r: r["pred"]
ch = app_chain(base, ids_ev)
k = sum(ch[i][0] == truth[i] for i in ids_ev)
out.append("## 1. What the app would actually show at 3 h (ladder + keep-early-spike/dip rule), baseline model")
out.append(f"app-chain 3 h pattern accuracy: {k}/{len(ids_ev)} = {k/len(ids_ev):.3f} CI {wilson(k, len(ids_ev))}; ladder n used: {Counter(v[1] for v in ch.values())}")
for fn in (48, 96, 144):
    chf = app_chain(base, ids_ev, fixed_n=fn); kf = sum(chf[i][0] == truth[i] for i in ids_ev)
    out.append(f"  same chain, window fixed n={fn}: {kf/len(ids_ev):.3f}")
plain = {n: sum(R[(i, 36, n)]["pred"] == truth[i] for i in ids_ev) / len(ids_ev) for n in (48, 96, 144)}
out.append(f"plain d=36 (no keep rule): {plain}")
keep48 = sum((R[(i, 36, 48)]["pred"] if not (R[(i, 8, 48)]["pred"] in ('spike', 'dip') and R[(i, 36, 48)]["pred"] == 'stable') else R[(i, 8, 48)]["pred"]) == truth[i] for i in ids_ev)
out.append(f"n=48 at 3 h + keep-early rule only: {keep48}/{len(ids_ev)} = {keep48/len(ids_ev):.3f}")
pp = defaultdict(list)
for i in ids_ev: pp[truth[i]].append(ch[i][0] == truth[i])
out.append("app-chain per pattern: " + ", ".join(f"{p} {sum(v)}/{len(v)}" for p, v in sorted(pp.items())))

# ---------------------------------------------------------------- 2. rules
out.append("\n## 2. Deterministic rule detector (v1 rule_pattern = app rules.go) accuracy")
for d, n in ((8, 48), (36, 48), (36, 96), (36, 144)):
    pp = defaultdict(list)
    for i in ids_ev: pp[truth[i]].append(R[(i, d, n)]["rule"] == truth[i])
    tot = sum(sum(v) for v in pp.values())
    out.append(f"d={d} n={n}: rules {tot}/{len(ids_ev)} = {tot/len(ids_ev):.3f} | " + ", ".join(f"{p} {sum(v)}/{len(v)}" for p, v in sorted(pp.items())))
for n in (48, 96, 144):
    c = Counter(R[(i, 0, n)]["rule"] for i in ids_cl)
    out.append(f"clean n={n}: rules call {c.most_common()}")
# rule precision per predicted label at d=36 (all n pooled) and in clean
out.append("\nrule precision by called label (events d in {18,24,36}, all n; clean counted as wrong if not stable):")
prec = defaultdict(lambda: [0, 0])
for (i, d, n), r in R.items():
    if d in (18, 24, 36) or d == 0:
        prec[r["rule"]][0] += r["rule"] == r["truth"]; prec[r["rule"]][1] += 1
out.append(", ".join(f"{p} {a}/{b}={a/b:.2f}" for p, (a, b) in sorted(prec.items())))
mprec = defaultdict(lambda: [0, 0])
for (i, d, n), r in R.items():
    if d in (18, 24, 36) or d == 0:
        mprec[r["pred"]][0] += r["pred"] == r["truth"]; mprec[r["pred"]][1] += 1
out.append("model precision by called label (same rows): " + ", ".join(f"{p} {a}/{b}={a/b:.2f}" for p, (a, b) in sorted(mprec.items()) if b >= 5))

# confidence as error signal
out.append("\n## 3. Model confidence vs correctness (events, d=36, all n)")
cc = defaultdict(lambda: [0, 0])
for (i, d, n), r in R.items():
    if d == 36 and not r["clean"] and r["conf"] is not None:
        cc[round(float(r["conf"]), 2)][0] += r["pred"] == r["truth"]; cc[round(float(r["conf"]), 2)][1] += 1
out.append(", ".join(f"conf {c}: {a}/{b}" for c, (a, b) in sorted(cc.items())))


# ---------------------------------------------------------------- 4. override policies
VALID = {"stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase", "step_decrease",
         "exponential_increase", "oscillation", "throttling", "flatline", "erratic"}


def P_invalid_to_rule(r):
    return r["pred"] if r["pred"] in VALID else r["rule"]


def P_flat(r):
    p = P_invalid_to_rule(r)
    if r["rule"] == "flatline" and p not in ("flatline", "stable"):
        return "flatline"
    return p


def P_lowconf_rule(th):
    def f(r):
        p = P_flat(r)
        c = r["conf"] if isinstance(r["conf"], (int, float)) else 0
        if c <= th and r["rule"] not in ("stable",) and r["rule"] != p and p != "flatline":
            return r["rule"]
        return p
    return f


def P_exp(r):
    """gradual_increase at low confidence + rule exponential -> exponential (the one systematic confusion)"""
    p = P_flat(r)
    c = r["conf"] if isinstance(r["conf"], (int, float)) else 0
    if p == "gradual_increase" and r["rule"] == "exponential_increase" and c <= 0.5:
        return "exponential_increase"
    return p


def P_exp2(r):
    """gradual_increase at low confidence -> exponential when the last hour holds most of the rise"""
    p = P_flat(r)
    c = r["conf"] if isinstance(r["conf"], (int, float)) else 0
    if p == "gradual_increase" and c <= 0.5 and (r["rule"] == "exponential_increase" or r.get("tail_frac", 0) > 0.5):
        return "exponential_increase"
    return p


pols = {"baseline": base, "invalid->rule": P_invalid_to_rule, "+flatline rule": P_flat,
        "+exp(rule, conf<=.5)": P_exp, "+exp(rule|tail, conf<=.5)": P_exp2,
        "+lowconf<=.3 -> rule": P_lowconf_rule(0.3), "+lowconf<=.5 -> rule": P_lowconf_rule(0.5)}
out.append("\n## 4. Post-hoc override policies (no extra NPU calls)")
out.append("| policy | 3h n=48 | 3h n=96 | 3h n=144 | app-chain 3h | 40min n=48 | 90min n=48 | clean flag n=48/96/144 (pattern!=stable) |\n|---|---|---|---|---|---|---|---|")
res = {}
for name, f in pols.items():
    a = {n: sum(f(R[(i, 36, n)]) == truth[i] for i in ids_ev) / len(ids_ev) for n in (48, 96, 144)}
    chn = app_chain(f, ids_ev); ac = sum(chn[i][0] == truth[i] for i in ids_ev) / len(ids_ev)
    a8 = sum(f(R[(i, 8, 48)]) == truth[i] for i in ids_ev) / len(ids_ev)
    a18 = sum(f(R[(i, 18, 48)]) == truth[i] for i in ids_ev) / len(ids_ev)
    cl = [sum(f(R[(i, 0, n)]) != "stable" for i in ids_cl) for n in (48, 96, 144)]
    res[name] = {"3h": a, "chain": ac, "40min": a8, "90min": a18, "clean_flag": cl}
    out.append(f"| {name} | {a[48]:.3f} | {a[96]:.3f} | {a[144]:.3f} | {ac:.3f} | {a8:.3f} | {a18:.3f} | {cl} |")

# ---------------------------------------------------------------- 5. multi-window vote at 3 h
out.append("\n## 5. Multi-window self-consistency at the 3 h refinement (extra NPU calls)")
def vote(i, d, lens, f=base, tie=None):
    ps = [f(R[(i, d, n)]) for n in lens]
    c = Counter(ps).most_common()
    if c[0][1] >= 2: return c[0][0]
    return f(R[(i, d, tie or lens[0])])
for lens in ((48, 96), (48, 96, 144), (96, 48, 144), (144, 96, 48)):
    for f, nm in ((base, "baseline"), (P_exp2, "+exp/flat fixes")):
        a = sum(vote(i, 36, lens, f) == truth[i] for i in ids_ev) / len(ids_ev)
        a8 = None
        cl = sum(vote(i, 0, lens, f) != "stable" for i in ids_cl)
        out.append(f"vote over {lens} (tie -> {lens[0]}) [{nm}]: 3h {a:.3f}; clean flag {cl}/100")
# confidence-weighted vote
def cvote(i, d, lens, f=base):
    s = Counter()
    for n in lens:
        r = R[(i, d, n)]; c = r["conf"] if isinstance(r["conf"], (int, float)) else 0.1
        s[f(r)] += c
    return s.most_common(1)[0][0]
for f, nm in ((base, "baseline"), (P_exp2, "+exp/flat fixes")):
    a = sum(cvote(i, 36, (48, 96, 144), f) == truth[i] for i in ids_ev) / len(ids_ev)
    cl = sum(cvote(i, 0, (48, 96, 144), f) != "stable" for i in ids_cl)
    out.append(f"confidence-weighted vote 48/96/144 [{nm}]: 3h {a:.3f}; clean flag {cl}/100")
# 1.5h also has 3 lengths: vote at 90 min
a = sum(vote(i, 18, (48, 96, 144)) == truth[i] for i in ids_ev) / len(ids_ev)
out.append(f"vote at 1.5 h (48/96/144): {a:.3f} vs n=48 alone {sum(R[(i,18,48)]['pred']==truth[i] for i in ids_ev)/len(ids_ev):.3f}")
# temporal vote: 2h + 3h?
a = sum((Counter([R[(i, 36, 48)]['pred'], R[(i, 24, 48)]['pred'], R[(i, 18, 48)]['pred']]).most_common(1)[0][0]) == truth[i] for i in ids_ev) / len(ids_ev)
out.append(f"temporal vote d=18/24/36 at n=48 (no extra calls if the app kept 1.5 h + an added 2 h refinement): {a:.3f}")

# bootstrap CI of the best policy delta vs baseline at n=48 3h
def boot(fa, fb, d=36, n=48, B=2000):
    rnd = random.Random(1); ds = []
    for _ in range(B):
        s = [rnd.choice(ids_ev) for _ in ids_ev]
        ds.append(sum((fa(i) == truth[i]) - (fb(i) == truth[i]) for i in s) / len(s))
    ds.sort(); return round(ds[int(.025 * B)], 3), round(ds[int(.975 * B)], 3)
ci = boot(lambda i: vote(i, 36, (48, 96, 144), P_exp2), lambda i: R[(i, 36, 48)]["pred"])
out.append(f"\nbootstrap 95% CI of delta (vote48/96/144 + fixes) - (n=48 baseline) at 3 h: {ci}")
ci = boot(lambda i: P_exp2(R[(i, 36, 48)]), lambda i: R[(i, 36, 48)]["pred"])
out.append(f"bootstrap 95% CI of delta (exp/flat/invalid fixes) - baseline at 3 h n=48: {ci}")
(HERE / "ensembles.md").write_text("# Cheap post-hoc fixes simulated on device outputs (placement_v2)\n\n" + "\n".join(out), encoding="utf-8")
json.dump(res, open(HERE / "a4_results.json", "w"), indent=1)
print("\n".join(out))
