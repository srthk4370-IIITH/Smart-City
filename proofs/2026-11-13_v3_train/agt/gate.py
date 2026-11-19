"""gate.py CONFIG GATE_DIR SAMPLES_DIR OUT_MD OUT_JSON CAND_NAME
STRICT agt_v3 gate vs B50 from host-GPU sample files (hosteval.py output): SAMPLES_DIR/<set>_v3.jsonl (candidate) and
SAMPLES_DIR/<set>_b50.jsonl (B50 on its v2 prompts of the same windows). Rows (for slices / pairing) from GATE_DIR.
ALL checks must pass; a missing file is a FAIL. Exit 0 PASS, 1 FAIL."""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kaggle"))
import rows as RW  # noqa: E402

cfg_p, gdir, sdir, out_md, out_js, cand = sys.argv[1:7]
CFG = json.load(open(cfg_p))
TH = CFG["thresholds"]
checks, info = [], {}


def chk(name, ok, detail):
    checks.append({"check": name, "pass": bool(ok), "detail": detail})


def load(set_name, which):
    spec = CFG["sets"][set_name]
    rp, sp = os.path.join(gdir, spec[which]), os.path.join(sdir, "%s_%s.jsonl" % (set_name, which))
    if not (os.path.exists(rp) and os.path.exists(sp)):
        return None
    rows = {}
    for r in RW.read_jsonl(rp):
        n = RW.norm(r)
        raw = n["raw"]
        n["pair"] = str(raw.get("pair_id") or raw.get("base_id") or n["id"])
        sl = set(n["slices"])
        sl |= {"ALL", "role_%s" % n["role"], "fam_%s" % n["family"], "gold_status_%s" % RW.fields(n["gold"])["status"],
               "gold_pat_%s" % RW.fields(n["gold"])["pattern"]}
        if n["stage"]:
            sl.add("stage_%s" % n["stage"])
        n["sl"] = sl
        rows[n["id"]] = n
    smp = {}
    for l in open(sp):
        s = json.loads(l)
        if s["id"] in rows:
            smp[s["id"]] = dict(s, row=rows[s["id"]])
    missing = len(rows) - len(smp)
    return {"rows": rows, "s": smp, "missing": missing}


def acc(ss, k):
    v = [bool(s[k]) for s in ss if s.get(k) is not None]
    return (sum(v) / len(v)) if v else None, len(v)


def pct(x):
    return "-" if x is None else "%.1f" % (100 * x)


def is_calm(s):
    return bool(s["row"]["sl"] & set(CFG["calm_markers"])) or s["row"]["family"] in CFG["calm_markers"]


def alarm_rate(ss):
    calm = [s for s in ss if is_calm(s) and s["gold_status"] == "normal"]
    return (sum(s["pred_status"] not in ("normal",) for s in calm) / len(calm)) if calm else None, len(calm)


def paired(set_name):
    a, b = load(set_name, "v3"), load(set_name, "b50")
    if a is None or b is None:
        return None
    bp = {s["row"]["pair"]: s for s in b["s"].values()}
    pairs = [(s, bp[s["row"]["pair"]]) for s in a["s"].values() if s["row"]["pair"] in bp]
    return a, b, pairs


def tot(s):
    return sum(bool(s[k]) for k in ("pattern", "status", "cause"))


# ---------------------------------------------------------------- JSON validity on every candidate set
alls = []
for nm in CFG["sets"]:
    x = load(nm, "v3")
    if x is None:
        chk("%s: files present" % nm, False, "missing %s rows or %s_v3 samples" % (CFG["sets"][nm]["v3"], nm))
        continue
    if x["missing"]:
        chk("%s: all rows evaluated" % nm, False, "%d rows without a sample" % x["missing"])
    alls += list(x["s"].values())
    if "b50" in CFG["sets"][nm] and load(nm, "b50") is None:
        chk("%s: B50 files present" % nm, False, "missing %s or %s_b50 samples" % (CFG["sets"][nm]["b50"], nm))
if alls:
    j = sum(s["json"] for s in alls)
    chk("JSON validity 100 % (all sets)", j == len(alls), "%d/%d" % (j, len(alls)))

# ---------------------------------------------------------------- dev_paired (gate2-style + absolute)
P = paired("dev_paired")
if P:
    a, b, pairs = P
    va, vb = [p[0] for p in pairs], [p[1] for p in pairs]
    chk("dev: every v3 row paired with a B50 row", len(pairs) == len(a["s"]), "%d/%d paired" % (len(pairs), len(a["s"])))
    net = sum(tot(x) - tot(y) for x, y in pairs)
    W = {"critical": 3, "warning": 2}
    sev = sum(W.get(x["gold_status"], 1) * (int(x["status"]) - int(y["status"])) for x, y in pairs)
    chk("dev: net (pattern+status+cause wins - losses) > 0", net > 0, "net %+d over %d pairs" % (net, len(pairs)))
    chk("dev: severity-weighted status net >= 0", sev >= 0, "%+d" % sev)
    # slices: exact sign test, Holm over every (slice, metric) where the candidate loses more than it wins
    sl = collections.defaultdict(list)
    for x, y in pairs:
        for k in x["row"]["sl"]:
            sl[k].append((x, y))
    pv, tab = {}, {}
    for k, pp in sl.items():
        if len(pp) < TH["slice_min_n"]:
            continue
        for m in ("pattern", "status", "cause"):
            w = sum(bool(x[m]) and not bool(y[m]) for x, y in pp)
            l_ = sum(bool(y[m]) and not bool(x[m]) for x, y in pp)
            ra, rb = sum(bool(x[m]) for x, _ in pp) / len(pp), sum(bool(y[m]) for _, y in pp) / len(pp)
            tab["%s.%s" % (k, m)] = {"n": len(pp), "b50": round(rb, 4), "v3": round(ra, 4), "w": w, "l": l_}
            if l_ > w:
                pv["%s.%s" % (k, m)] = RW.binom_two_sided(w, l_)
    rej = RW.holm(pv, TH["holm_alpha"])
    chk("dev: no Holm-worse slice (exact sign test, alpha %.2f)" % TH["holm_alpha"], not rej,
        "worse: %s" % (", ".join("%s %s->%s (%d/%d)" % (k, pct(tab[k]["b50"]), pct(tab[k]["v3"]), tab[k]["w"], tab[k]["l"]) for k in sorted(rej)) or "none"))
    down = sorted(k for k, v in tab.items() if v["v3"] < v["b50"] - 0.01)
    info["dev slices down > 1 pt (not significant)"] = ["%s %s->%s" % (k, pct(tab[k]["b50"]), pct(tab[k]["v3"])) for k in down]
    info["dev_slices"] = tab
    ca, cb = [x for x, _ in pairs if is_calm(x)], [y for x, y in pairs if is_calm(x)]
    a1, b1 = acc(ca, "status")[0], acc(cb, "status")[0]
    chk("dev: calm/routine status not worse", a1 is not None and a1 >= b1, "B50 %s -> v3 %s (n %d)" % (pct(b1), pct(a1), len(ca)))
    for dom, key in (("power", "power_status"), ("water", "water_status")):
        x = acc([s for s in va if s["row"]["role"] == dom], "status")
        chk("dev: %s status >= %d" % (dom, round(100 * TH[key])), x[0] is not None and x[0] >= TH[key], "%s (n %d)" % (pct(x[0]), x[1]))
    doms = sorted({s["row"]["role"] for s in va})
    worst = []
    for d in doms:
        x, y = acc([p[0] for p in pairs if p[0]["row"]["role"] == d], "status")[0], acc([p[1] for p in pairs if p[0]["row"]["role"] == d], "status")[0]
        worst.append((d, x, y))
    bad = [(d, x, y) for d, x, y in worst if x < y - TH["domain_max_drop_vs_b50"]]
    chk("dev: no domain status > 1 pt below B50", not bad, "; ".join("%s %s->%s" % (d, pct(y), pct(x)) for d, x, y in worst))
    cr = [s for s in va if s["gold_status"] == "critical"]
    r_ = sum(s["pred_status"] == "critical" for s in cr) / len(cr) if cr else None
    chk("dev: critical recall >= %d" % round(100 * TH["critical_recall"]), r_ is not None and r_ >= TH["critical_recall"],
        "%s (n %d; B50 %s)" % (pct(r_), len(cr), pct(sum(y["pred_status"] == "critical" for x, y in pairs if x["gold_status"] == "critical") / max(1, len(cr)))))
    fa, nfa = alarm_rate(va)
    fb, _ = alarm_rate(vb)
    chk("dev: calm false alarms <= %d %%" % round(100 * TH["calm_false_alarm_max"]), fa is not None and fa <= TH["calm_false_alarm_max"],
        "%s %% of %d calm normal rows (B50 %s %%)" % (pct(fa), nfa, pct(fb)))
    for st in CFG["stages"]:
        pp = [(x, y) for x, y in pairs if st in x["row"]["sl"]]
        x, y = acc([p[0] for p in pp], "pattern")[0], acc([p[1] for p in pp], "pattern")[0]
        chk("dev: %s pattern >= B50" % st, pp and x >= y, "B50 %s -> v3 %s (n %d)" % (pct(y), pct(x), len(pp)))
    pp = [(x, y) for x, y in pairs if x["row"]["sl"] & set(CFG["young_markers"])]
    x, y = acc([p[0] for p in pp], "pattern")[0], acc([p[1] for p in pp], "pattern")[0]
    chk("dev: young k=3-7 pattern >= B50", pp and x >= y, "B50 %s -> v3 %s (n %d)" % (pct(y), pct(x), len(pp)))
    info["dev_overall"] = {m: {"v3": pct(acc(va, m)[0]), "b50": pct(acc(vb, m)[0])} for m in ("pattern", "status", "cause", "dq")}

# ---------------------------------------------------------------- E1
P = paired("e1")
if P:
    a, b, pairs = P
    net = sum(tot(x) - tot(y) for x, y in pairs)
    chk("E1: net >= 0", net >= 0, "net %+d over %d stories" % (net, len(pairs)))
    saf = [s for s in a["s"].values() if s["row"]["sl"] & set(CFG["safety_markers"]) or s["row"]["raw"].get("safety")]
    ok = sum(bool(s["status"]) and bool(s["pattern"]) for s in saf)
    chk("E1: safety %d/%d" % (TH["e1_safety_n"], TH["e1_safety_n"]), len(saf) == TH["e1_safety_n"] and ok == len(saf), "%d/%d correct" % (ok, len(saf)))

# ---------------------------------------------------------------- rename agreement >= noise floor
x = load("rename", "v3")
if x:
    by = collections.defaultdict(dict)
    for s in x["s"].values():
        by[s["row"]["pair"]][s["row"]["variant"] or "orig"] = s

    def agree(v):
        pp = [(d["orig"], d[v]) for d in by.values() if "orig" in d and v in d]
        k = ("pred_pattern", "pred_status")
        return (sum(all(p[0][f] == p[1][f] for f in k) for p in pp) / len(pp)) if pp else None, len(pp)
    ren, rep = agree("ren"), agree("rep")
    floor = rep[0] if rep[0] is not None else TH["rename_min_if_no_noise_rows"]
    chk("rename agreement >= noise floor", ren[0] is not None and ren[0] >= floor,
        "orig vs renamed %s (n %d); noise floor %s (n %d)" % (pct(ren[0]), ren[1], pct(floor), rep[1]))

# ---------------------------------------------------------------- unseen metric / unseen layout / campus / calm faults
x = load("unseen_metric", "v3")
if x:
    ss = list(x["s"].values())
    for m, key in (("status", "unseen_metric_status"), ("pattern", "unseen_metric_pattern"), ("dq", "unseen_metric_dq")):
        v, n = acc(ss, m)
        chk("unseen_metric: %s >= %d" % (m, round(100 * TH[key])), v is not None and v >= TH[key], "%s (n %d)" % (pct(v), n))
P = paired("unseen_layout")
if P:
    a, b, pairs = P
    v, n = acc(list(a["s"].values()), "status")
    vb = acc([q for _, q in pairs], "status")[0]
    chk("unseen_layout: status >= %d and >= B50" % round(100 * TH["unseen_layout_status"]),
        v is not None and v >= TH["unseen_layout_status"] and v >= (vb or 0), "%s (n %d; B50 %s)" % (pct(v), n, pct(vb)))
P = paired("campus")
if P:
    a, b, pairs = P
    v, vb = acc([p[0] for p in pairs], "status")[0], acc([p[1] for p in pairs], "status")[0]
    chk("test_campus (real held-out): status >= B50", v is not None and v >= vb, "B50 %s -> v3 %s (n %d)" % (pct(vb), pct(v), len(pairs)))
x = load("calm_fault", "v3")
if x:
    ss = [s for s in x["s"].values() if s["gold_status"] == "sensor_fault"]
    v = sum(s["pred_status"] == "sensor_fault" for s in ss) / len(ss) if ss else None
    chk("calm-looking fault recall >= %d" % round(100 * TH["calm_fault_recall"]), v is not None and v >= TH["calm_fault_recall"], "%s (n %d)" % (pct(v), len(ss)))

# ---------------------------------------------------------------- fault precision (owner 2026-11-13, label-audit lesson)
allv = []
for nm in ("dev_paired", "unseen_metric", "unseen_layout", "campus", "calm_fault"):
    x = load(nm, "v3")
    if x:
        allv += list(x["s"].values())
pf = [s for s in allv if s["pred_status"] == "sensor_fault"]
nf = [s for s in allv if s["gold_status"] != "sensor_fault"]
prec = (sum(s["gold_status"] == "sensor_fault" for s in pf) / len(pf)) if pf else None
ffr = (sum(s["pred_status"] == "sensor_fault" for s in nf) / len(nf)) if nf else None
chk("fault precision >= %d" % round(100 * TH["fault_precision"]), prec is not None and prec >= TH["fault_precision"],
    "%s of %d sensor_fault calls are real faults" % (pct(prec), len(pf)))
chk("false 'broken sensor' calls <= %d %%" % round(100 * TH["false_fault_max"]), ffr is not None and ffr <= TH["false_fault_max"],
    "%s %% of %d non-fault windows called sensor_fault" % (pct(ffr), len(nf)))

ok = bool(checks) and all(c["pass"] for c in checks)
res = {"candidate": cand, "verdict": "PASS" if ok else "FAIL", "checks": checks, "info": info}
json.dump(res, open(out_js, "w"), indent=1)
L = ["# GATE_agt: %s vs B50 -> **%s**" % (cand, res["verdict"]), "",
     "Strict gate (V3_DESIGN.md 5.4 + owner brief): every check must pass, otherwise B50 stays. Host GPU Q4_0, greedy, device "
     "prompts + prefill + app stop rule; B50 on its v2 prompts of the same windows. Raw samples: `%s`." % sdir, "",
     "| check | pass | detail |", "|---|---|---|"]
L += ["| %s | %s | %s |" % (c["check"], "yes" if c["pass"] else "**NO**", c["detail"]) for c in checks]
if "dev_overall" in info:
    L += ["", "Dev overall (B50 -> v3): " + "; ".join("%s %s -> %s" % (k, v["b50"], v["v3"]) for k, v in info["dev_overall"].items())]
if info.get("dev slices down > 1 pt (not significant)"):
    L += ["", "Slices down > 1 pt (not significant, for the record): " + ", ".join(info["dev slices down > 1 pt (not significant)"][:40])]
L += ["", "**Also required before agt_v3 replaces B50 (owner 2026-11-13, run after this gate):** " + "; ".join(CFG.get("post_gate_required", []))]
L += ["", "Not automated here (need the reasoner / one-time sets): design 5.4 items 7 (315 real-agent incidents through r3-2800) "
      "and 8 (untouched eval_test, once at the end)."]
open(out_md, "w").write("\n".join(L) + "\n")
print(res["verdict"], sum(c["pass"] for c in checks), "/", len(checks))
sys.exit(0 if ok else 1)
