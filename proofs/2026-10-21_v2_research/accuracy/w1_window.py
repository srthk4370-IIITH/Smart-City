"""Window-length study for the dynamic ladder (device Q4_0 outputs only, no new calls).
A. placement_v2 (paired: same event at n = 48/96/144, d = 4..36): pattern accuracy / flag / clean false alarm by
   n x d x true pattern, n x d x runtime severity (the early call's status, what LadderN sees), n x d x early
   predicted pattern family (also visible at runtime). Paired McNemar n=48 vs 96 vs 144.
   Policy search: choose n per (stage, early status, early pattern family) by leave-one-case-out CV.
B. device test rows (host400 + partial test split; unpaired, every role/family): pattern / status / cause /
   false alarm by window bucket x age x gold status x family, and onset inside vs outside the window (d > n).
Writes window_study.md and window_policy.json."""
import json, math
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = HERE.parents[1] / "2026-10-20_v2_post" / "device"
TEST = Path(r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\data\sft_v2\test.jsonl")
rows = json.load(open(HERE / "a1_rows.json"))
R = {(r["id"], r["d"], r["n"]): r for r in rows}
ev = sorted({r["id"] for r in rows if not r["clean"]}); cl = sorted({r["id"] for r in rows if r["clean"]})
T = {r["id"]: r["truth"] for r in rows}
NS = (48, 96, 144); DS = (4, 8, 12, 18, 24, 36)
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}
FAM = {"spike": "transient", "dip": "transient", "step_increase": "step", "step_decrease": "step",
       "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
       "oscillation": "noisy", "erratic": "noisy", "flatline": "flat", "stable": "stable", "throttling": "step"}
fam = lambda p: FAM.get(p, "invalid")


def wil(k, n, z=1.96):
    if n == 0: return None
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(k / n, 3), round((c - h) / d, 3), round((c + h) / d, 3), n]


def mcn(b, c):
    n = b + c
    if n == 0: return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def fmt(w): return "-" if not w else f"{w[0]*100:.0f} [{w[1]*100:.0f}-{w[2]*100:.0f}] n={w[3]}"


out, J = [], {"source": "device Q4_0 htpd outputs: proofs/2026-10-20_v2_post/device/{placement_v2,host400,test_all}"}
ok = lambda i, d, n: R[(i, d, n)]["pred"] == T[i]

# ---------------------------------------------------------------- A1 n x d (all events) + paired tests
out.append("## A. placement_v2 (paired across window length; 183 events, 100 clean)\n")
out.append("### A1 pattern accuracy by window n x readings since onset d (all events)")
out.append("| d | n=48 | n=96 | n=144 | McNemar 48 vs 144 (48-only/144-only, p) | 48 vs 96 |\n|---|---|---|---|---|---|")
for d in DS:
    w = {n: wil(sum(ok(i, d, n) for i in ev), len(ev)) for n in NS}
    b = sum(ok(i, d, 48) and not ok(i, d, 144) for i in ev); c = sum(ok(i, d, 144) and not ok(i, d, 48) for i in ev)
    b2 = sum(ok(i, d, 48) and not ok(i, d, 96) for i in ev); c2 = sum(ok(i, d, 96) and not ok(i, d, 48) for i in ev)
    out.append(f"| {d} ({d*5} min) | {fmt(w[48])} | {fmt(w[96])} | {fmt(w[144])} | {b}/{c}, p={mcn(b,c):.3f} | {b2}/{c2}, p={mcn(b2,c2):.3f} |")
# clean
out.append("\nclean windows (no event): " + "; ".join(
    f"n={n}: false alarm (status!=normal) {fmt(wil(sum(R[(i,0,n)]['status']!='normal' for i in cl), len(cl)))}, pattern!=stable {fmt(wil(sum(R[(i,0,n)]['pred']!='stable' for i in cl), len(cl)))}" for n in NS))
J["clean_false_alarm"] = {n: wil(sum(R[(i, 0, n)]["status"] != "normal" for i in cl), len(cl)) for n in NS}
J["clean_false_alarm_by_role"] = {f"{ro}|n={n}": wil(sum(R[(i, 0, n)]["status"] != "normal" for i in cl if R[(i, 0, n)]["role"] == ro), sum(1 for i in cl if R[(i, 0, n)]["role"] == ro)) for ro in ("air_quality", "water", "power") for n in NS}

# ---------------------------------------------------------------- A2 n x d x true pattern
out.append("\n### A2 pattern accuracy by true pattern x d x n (best n bold when it beats the others by >= 10 pts)")
pats = sorted({T[i] for i in ev})
J["by_true_pattern"] = {}
out.append("| pattern | d | n=48 | n=96 | n=144 |\n|---|---|---|---|---|")
for p in pats:
    ids = [i for i in ev if T[i] == p]
    for d in DS:
        w = {n: wil(sum(ok(i, d, n) for i in ids), len(ids)) for n in NS}
        J["by_true_pattern"][f"{p}|d={d}"] = w
        best = max(NS, key=lambda n: w[n][0]); lead = w[best][0] - max(w[n][0] for n in NS if n != best)
        cells = [("**" + fmt(w[n]) + "**") if (n == best and lead >= 0.10) else fmt(w[n]) for n in NS]
        out.append(f"| {p} | {d} | " + " | ".join(cells) + " |")

# ---------------------------------------------------------------- A3 runtime signals: early status / early pattern family
def early(i): return R[(i, 8, 48)]
out.append("\n### A3 by runtime severity (status of the EARLY 4 h call, what LadderN sees) at the refinement stages")
out.append("| stage | early status | n events | n=48 | n=96 | n=144 | clean windows with that early status: false alarm at 48/96/144 |\n|---|---|---|---|---|---|---|")
J["by_early_status"] = {}
for d in (18, 24, 36):
    for st in ("normal", "warning", "critical", "sensor_fault"):
        ids = [i for i in ev if early(i)["status"] == st]
        if not ids: continue
        w = {n: wil(sum(ok(i, d, n) for i in ids), len(ids)) for n in NS}
        J["by_early_status"][f"d={d}|{st}"] = w
        cids = [i for i in cl if R[(i, 0, 48)]["status"] == st]
        fa = [sum(R[(i, 0, n)]["status"] != "normal" for i in cids) for n in NS]
        out.append(f"| d={d} | {st} | {len(ids)} | {fmt(w[48])} | {fmt(w[96])} | {fmt(w[144])} | {fa} of {len(cids)} |")
out.append("\n### A4 by EARLY predicted pattern family (runtime-visible) at the refinement stages")
out.append("| stage | early family | n | n=48 | n=96 | n=144 |\n|---|---|---|---|---|---|")
J["by_early_family"] = {}
for d in (18, 36):
    for f in ("transient", "step", "trend", "noisy", "flat", "stable", "invalid"):
        ids = [i for i in ev if fam(early(i)["pred"]) == f]
        if not ids: continue
        w = {n: wil(sum(ok(i, d, n) for i in ids), len(ids)) for n in NS}
        J["by_early_family"][f"d={d}|{f}"] = w
        out.append(f"| d={d} | {f} | {len(ids)} | {fmt(w[48])} | {fmt(w[96])} | {fmt(w[144])} |")
out.append("\nnumber of flagged sensors: NOT derivable from these data (every placement case and test row is one sensor);"
           " needs an app-level multi-sensor run.")

# ---------------------------------------------------------------- A5 policy search with leave-one-out CV
def chain(i, pick):
    """app chain: early n=48 at d=8; refine at d=18 and d=36 with n = pick(stage, early row, prev row)."""
    e = R[(i, 8, 48)]; ep = e["pred"]
    n1 = pick(18, e, e); r1 = R[(i, 18, n1)]; p1 = r1["pred"]
    if ep in ("spike", "dip") and p1 == "stable": p1 = ep
    n2 = pick(36, e, r1); r2 = R[(i, 36, n2)]; p2 = r2["pred"]
    if ep in ("spike", "dip") and p2 == "stable": p2 = ep
    return p1, p2, n1, n2


ladder = lambda d, e, prev: max(LAD.get(e["status"], 48), LAD.get(prev["status"], 48))
fixed = lambda n: (lambda d, e, prev: n)


def key_of(d, e): return (d, e["status"] if e["status"] in LAD else "normal", fam(e["pred"]))


def fit(ids):
    """table key -> n maximising refinement accuracy on ids; ties / small cells (<5) fall back to the ladder."""
    acc = defaultdict(lambda: Counter()); cnt = Counter()
    for i in ids:
        e = R[(i, 8, 48)]
        for d in (18, 36):
            k = key_of(d, e); cnt[k] += 1
            for n in NS:
                p = R[(i, d, n)]["pred"]
                if e["pred"] in ("spike", "dip") and p == "stable": p = e["pred"]
                acc[k][n] += p == T[i]
    tab = {}
    for k in cnt:
        lad = LAD.get(k[1], 48)
        best = max(NS, key=lambda n: (acc[k][n], n == lad))
        tab[k] = best if cnt[k] >= 5 and acc[k][best] > acc[k][lad] else lad
    return tab, acc, cnt


def table_pick(tab):
    return lambda d, e, prev: tab.get(key_of(d, e), ladder(d, e, prev))


res = {}
for name, pk in (("ladder (current LadderN)", ladder), ("fixed 4 h", fixed(48)), ("fixed 8 h", fixed(96)), ("fixed 12 h", fixed(144))):
    c = [chain(i, pk) for i in ev]
    res[name] = (sum(c[k][0] == T[i] for k, i in enumerate(ev)) / len(ev), sum(c[k][1] == T[i] for k, i in enumerate(ev)) / len(ev),
                 sum(c[k][3] for k in range(len(ev))) / len(ev))
# oracle-free CV: leave one case out
cvok1 = cvok2 = 0; nsum = 0
for i in ev:
    tab, _, _ = fit([j for j in ev if j != i])
    p1, p2, n1, n2 = chain(i, table_pick(tab)); cvok1 += p1 == T[i]; cvok2 += p2 == T[i]; nsum += n2
res["learned table (leave-one-case-out CV)"] = (cvok1 / len(ev), cvok2 / len(ev), nsum / len(ev))
tab, acc, cnt = fit(ev)
c = [chain(i, table_pick(tab)) for i in ev]
res["learned table (in-sample, optimistic)"] = (sum(c[k][0] == T[i] for k, i in enumerate(ev)) / len(ev), sum(c[k][1] == T[i] for k, i in enumerate(ev)) / len(ev), sum(c[k][3] for k in range(len(ev))) / len(ev))
out.append("\n### A5 window-selection policies through the app chain (early 4 h -> 1.5 h -> 3 h, keep-early-spike/dip rule)")
out.append("| policy | 1.5 h pattern acc | 3 h pattern acc | mean n at 3 h |\n|---|---|---|---|")
for k, v in res.items():
    out.append(f"| {k} | {v[0]:.3f} | {v[1]:.3f} | {v[2]:.0f} |")
# clean windows: what each policy does to false alarms at refinement (if a clean window were refined)
out.append("\nlearned cells (stage, early status, early family) -> n [acc 48/96/144 of cnt]: " + "; ".join(
    f"{k}: {tab[k]} [{acc[k][48]}/{acc[k][96]}/{acc[k][144]} of {cnt[k]}]" for k in sorted(cnt)))
J["policy_eval_placement"] = {k: {"pattern_1_5h": round(v[0], 3), "pattern_3h": round(v[1], 3), "mean_n_3h": round(v[2])} for k, v in res.items()}

# ---------------------------------------------------------------- B. test rows (all roles), unpaired
out.append("\n## B. device test rows (host400 + partial test split, dedup; unpaired, all six roles)")
gold = {}
for l in open(TEST, encoding="utf-8"):
    g = json.loads(l); gold[g["id"]] = {"d": g.get("d"), "n": g["n"], "fault_kind": g.get("fault_kind"), "sub": g.get("sub")}
tr = {}
for f in ("host400", "test_all"):
    for r in map(json.loads, open(P / f / "samples.jsonl", encoding="utf-8")):
        tr.setdefault(r["id"], r)
tr = [dict(r, **gold.get(r["id"], {})) for r in tr.values()]
wb = lambda n: "<=3h" if n <= 36 else "4h" if n <= 48 else "4-8h" if n <= 96 else "8-12h"
def agg(sel):
    m = {}
    for k in ("pattern", "status", "cause"):
        v = [bool(r[k]) for r in sel if r.get(k) is not None]; m[k] = wil(sum(v), len(v))
    v = [bool(r["false_alarm"]) for r in sel if r.get("false_alarm") is not None]; m["false_alarm"] = wil(sum(v), len(v))
    return m
J["test_rows"] = {}
out.append("| slice | n | pattern | status | cause | false alarm (negatives) |\n|---|---|---|---|---|---|")
def emit(name, sel):
    if len(sel) < 8: return
    m = agg(sel); J["test_rows"][name] = m
    out.append(f"| {name} | {len(sel)} | {fmt(m['pattern'])} | {fmt(m['status'])} | {fmt(m['cause'])} | {fmt(m['false_alarm'])} |")
for w in ("<=3h", "4h", "4-8h", "8-12h"):
    emit(f"window {w}", [r for r in tr if wb(r["n"]) == w])
for a in ("a<=40min", "b<=1.5h", "c<=3h", "d>3h", "no_event"):
    for w in ("<=3h", "4h", "4-8h", "8-12h"):
        emit(f"age {a} x window {w}", [r for r in tr if r["age"] == a and wb(r["n"]) == w])
for s in ("normal", "warning", "critical", "sensor_fault"):
    for w in ("<=3h", "4h", "4-8h", "8-12h"):
        emit(f"gold status {s} x window {w}", [r for r in tr if r["gold_status"] == s and wb(r["n"]) == w])
for fm in ("event", "fault", "compound", "old_shift", "long_drift", "recurring", "routine", "real_routine", "stable"):
    for w in ("4h", "4-8h", "8-12h"):
        emit(f"family {fm} x window {w}", [r for r in tr if r["family"] == fm and wb(r["n"]) == w])
fk = Counter(r.get("fault_kind") for r in tr if r.get("fault_kind"))
for k in fk:
    emit(f"fault {k} (all windows)", [r for r in tr if r.get("fault_kind") == k])
# onset inside / outside window
ins = [r for r in tr if r.get("d") is not None and r["d"] <= r["n"]]
outs = [r for r in tr if r.get("d") is not None and r["d"] > r["n"]]
emit("onset inside window (d <= n)", ins); emit("onset OLDER than window (d > n)", outs)
out.append("\nonset older than window, by family: " + str(Counter(r["family"] for r in outs)) + "; by window: " + str(Counter(wb(r["n"]) for r in outs)))
for fm in sorted({r["family"] for r in outs}):
    a = [r for r in outs if r["family"] == fm]; b = [r for r in ins if r["family"] == fm]
    if a and b:
        out.append(f"  {fm}: outside {fmt(wil(sum(bool(r['pattern']) for r in a), len(a)))} vs inside {fmt(wil(sum(bool(r['pattern']) for r in b), len(b)))}")

# ---------------------------------------------------------------- recommended table
rec = {
    "basis": "placement_v2 paired study (183 events x 6 ages x 3 lengths, 100 clean) + device test rows; device Q4_0 htpd; n per cell 14-21, so differences < ~15 pts are not significant",
    "stage_early": {"n": 48, "why": "40 min after onset 4 h is as good as 8/12 h (A1) and has the lowest clean false-alarm rate (A1 clean); the onset is always inside 4 h"},
    "refine_rules": [],
    "do_not": [],
}
J["recommendation"] = rec
(HERE / "window_study.md").write_text("# Window length study (device outputs)\n\n" + "\n".join(out), encoding="utf-8")
json.dump(J, open(HERE / "window_policy_raw.json", "w"), indent=1)
print("\n".join(out))
