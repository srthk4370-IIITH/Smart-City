"""analyze.py <tag>: RQ1 (host cost proxy), RQ2, Set D, F, RQ3 (offline trigger study), A routing -> RESULTS.md, results/*.json, results/*.png."""
import json, sys, math, random, collections, statistics as S, datetime as dt, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pdata as D
import pcase as P

tag = sys.argv[1] if len(sys.argv) > 1 else "full"
RUN = "%s/runs/%s" % (D.PAPER, tag); OUT = D.PAPER + "/results"; os.makedirs(OUT, exist_ok=True)
recs = [json.loads(l) for l in open(RUN + "/records.jsonl")]
RNG = np.random.default_rng(26112601)
lab = lambda r: (r or {}).get("label"); sev = lambda r: (r or {}).get("severity")


def arm(r, a):
    return r["mode2fair"]["report"] if a == "m2" and r.get("mode2fair") else (r[a] if a != "m2" else None)


def ok(r, a, what="both"):
    x = arm(r, a); g = r["gold"]
    if x is None:
        return None
    L_, S_ = lab(x) == g["label"], sev(x) == g["severity"]
    return {"both": L_ and S_, "label": L_, "sev": S_}[what]


def ci(v, B=2000):
    v = np.array(v, float)
    if len(v) == 0:
        return (None, None, None)
    bs = RNG.choice(v, (B, len(v))).mean(1)
    return (round(100 * v.mean(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1))


def mcnemar(a, b):      # exact two-sided on paired booleans
    n10 = sum(1 for x, y in zip(a, b) if x and not y); n01 = sum(1 for x, y in zip(a, b) if y and not x)
    n = n10 + n01
    if n == 0:
        return dict(b=n10, c=n01, p=1.0)
    k = min(n10, n01); p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return dict(b=n10, c=n01, p=round(p, 4))


def fmt(t):
    return "%s [%s, %s]" % t if t[0] is not None else "-"


gold_recs = [r for r in recs if r["gold"]]
B = [r for r in recs if r["set"] == "B"]; Dn = [r for r in recs if r["set"] == "D"]; F = [r for r in recs if r["set"] == "F"]; A = [r for r in recs if r["set"] == "A"]
Fi = [r for r in F if r["gold"]]
res = {"n": {s: sum(1 for r in recs if r["set"] == s) for s in "ABDF"}}
md = ["# RESULTS (host phase 2, tag `%s`)" % tag, "", "Generated %s by analyze.py. All accuracy numbers are on INJECTED cases (B, F-injected) or D controls; real windows (A, F-natural) are unscored. 'both' = label AND severity match the injection gold. 95%% CIs are bootstrap (2000 resamples) in brackets; McNemar exact two-sided." % dt.datetime.now().strftime("%Y-%m-%d %H:%M"), ""]

# ---------------------------------------------------------------- RQ2
ARMS = ["cheap", "cheap_x", "full", "m2"]
NAME = {"cheap": "cheap (isolatedReport)", "cheap_x": "cheap_x (fallbackReport)", "full": "full (agents+reasoner)", "m2": "Mode 2-fair (reasoner, no agents)"}
rq2 = {}
md += ["## RQ2: what escalation buys (Set B, injected, n=%d)" % len(B), "", "| N domains | n | arm | label acc % | severity acc % | both % | missed critical |", "|---|---|---|---|---|---|---|"]
for st in ["2", "3-4", "5+", "all"]:
    rr = B if st == "all" else [r for r in B if r["stratum"] == st]
    for a in ARMS:
        rows = [r for r in rr if arm(r, a) is not None]
        if not rows:
            continue
        crit = [r for r in rows if r["gold"]["severity"] == "critical"]
        miss = sum(1 for r in crit if sev(arm(r, a)) != "critical")
        d = dict(n=len(rows), label=ci([ok(r, a, "label") for r in rows]), sev=ci([ok(r, a, "sev") for r in rows]), both=ci([ok(r, a) for r in rows]), missed_critical="%d/%d" % (miss, len(crit)))
        rq2["%s|%s" % (st, a)] = d
        md.append("| %s | %d | %s | %s | %s | %s | %s |" % (st, len(rows), NAME[a], fmt(d["label"]), fmt(d["sev"]), fmt(d["both"]), d["missed_critical"]))
md += ["", "Paired tests (full vs cheap, both-correct; b = full right & cheap wrong, c = reverse):", ""]
for st in ["2", "3-4", "5+", "all"]:
    rr = B if st == "all" else [r for r in B if r["stratum"] == st]
    for other in ("cheap", "cheap_x", "m2"):
        rows = [r for r in rr if arm(r, other) is not None]
        if rows:
            m = mcnemar([ok(r, "full") for r in rows], [ok(r, other) for r in rows]); rq2["mcnemar|%s|%s" % (st, other)] = m
            md.append("- N=%s, full vs %s: b=%d c=%d p=%s" % (st, other, m["b"], m["c"], m["p"]))
# mapping-corrected cheap label
def cheap_any_label(r):
    labs = {P.CAUSE_TO_LABEL.get(a["finding"]["likely_cause"], "") or "normal_operation" for a in r["agents"] if a["finding"] and a["valid"]}
    return labs
mc = ci([r["gold"]["label"] in cheap_any_label(r) for r in B])
rq2["cheap_label_any_of_flagged_agents"] = mc
md += ["", "Mapping-corrected cheap label accuracy (Set B): the cheap template reports only the LEAD sensor's cause->label. Counting a label as right when the gold label is the label of ANY flagged agent's cause (an upper bound for a fair cause->label map): %s %% (strict cheap: %s %%)." % (fmt(mc), fmt(rq2["all|cheap"]["label"])), ""]
by_fam = collections.defaultdict(list)
for r in B:
    by_fam[r["family"]].append(r)
md += ["Per family (both-correct %, full / cheap / Mode 2-fair):", ""]
for f_, rr in sorted(by_fam.items()):
    md.append("- %s (n=%d): %s / %s / %s" % (f_, len(rr), round(100 * np.mean([ok(r, "full") for r in rr])), round(100 * np.mean([ok(r, "cheap") for r in rr])), round(100 * np.mean([ok(r, "m2") for r in rr if r.get("mode2fair")] or [0]))))
res["rq2"] = rq2

# ---------------------------------------------------------------- Set D
nor = [r for r in Dn if r["family"].startswith("normal")]; flt = [r for r in Dn if r["family"].startswith("real_fault")]
dres = {}
md += ["", "## Set D: negative controls (%d normal windows, %d real sensor-fault windows)" % (len(nor), len(flt)), "",
       "| arm | false-alarm rate (normal reported as warning/critical/fault) | false sensor_fault rate (normal) | fault detected as sensor_fault (n=%d) | fault called an event (warning/critical) |" % len(flt), "|---|---|---|---|---|"]
for a in ARMS:
    nn = [r for r in nor if arm(r, a)]; ff = [r for r in flt if arm(r, a)]
    if not nn:
        continue
    d = dict(false_alarm=ci([sev(arm(r, a)) != "normal" for r in nn]), false_fault=ci([sev(arm(r, a)) == "sensor_fault" or lab(arm(r, a)) == "sensor_fault" for r in nn]),
             fault_detected=ci([lab(arm(r, a)) == "sensor_fault" for r in ff]), fault_as_event=ci([sev(arm(r, a)) in ("warning", "critical") for r in ff]))
    dres[a] = d
    md.append("| %s | %s | %s | %s | %s |" % (NAME[a], fmt(d["false_alarm"]), fmt(d["false_fault"]), fmt(d["fault_detected"]), fmt(d["fault_as_event"])))
ev = [r for r in B + Fi if r["gold"]["label"] != "sensor_fault"]
md += ["", "Event called a sensor fault (injected events in B and F whose gold is not sensor_fault, n=%d), per arm: " % len(ev) + "; ".join("%s %s" % (a, fmt(ci([lab(arm(r, a)) == "sensor_fault" or sev(arm(r, a)) == "sensor_fault" for r in ev if arm(r, a)]))) for a in ARMS if any(arm(r, a) for r in ev))]
res["setD"] = dres

# ---------------------------------------------------------------- F
fres = {}
md += ["", "## Set F: forced single-domain cases (n=%d: %d injected with gold, %d natural unscored)" % (len(F), len(Fi), len(F) - len(Fi)), ""]
miss_esc = [r for r in Fi if ok(r, "full") and not ok(r, "cheap")]
wasted = [r for r in Fi if ok(r, "cheap") and not ok(r, "full")]
md.append("- The app's rule (>= 2 domains) escalates %d of %d of these; so every case where the reasoner would have fixed the cheap report is a MISSED escalation: %d of %d (%s %%). Escalations that would have hurt (cheap right, full wrong): %d." % (
    sum(r["triggers"]["app_would_escalate"] for r in F), len(F), len(miss_esc), len(Fi), round(100 * len(miss_esc) / max(1, len(Fi)), 1), len(wasted)))
for a in ("cheap", "full"):
    fres[a] = ci([ok(r, a) for r in Fi])
    md.append("- %s both-correct on F-injected: %s" % (NAME[a], fmt(fres[a])))
md.append("- Missed escalations by family: " + ", ".join("%s %d" % (k, v) for k, v in collections.Counter(r["family"] for r in miss_esc).items()))
fn = [r for r in F if not r["gold"]]
md.append("- Natural single-domain (unscored, n=%d): cheap vs full discordance (label or severity) %s %%; any-critical in %s %%." % (len(fn), round(100 * np.mean([lab(r["cheap"]) != lab(r["full"]) or sev(r["cheap"]) != sev(r["full"]) for r in fn]), 1), round(100 * np.mean([r["triggers"]["any_critical"] for r in fn]), 1)))
res["F"] = dict(missed=len(miss_esc), n=len(Fi), wasted=len(wasted))

# ---------------------------------------------------------------- RQ1 / costs
def agent_s(r):
    return sum(((a.get("prompt_ms") or 0) + (a.get("predicted_ms") or 0)) for a in r["agents"]) / 1000.0


def cost(r, a):
    if a == "cheap":
        return agent_s(r)
    if a == "full":
        return agent_s(r) + (r["reasoner"]["wall_s"] or 0)
    return (r["mode2fair"]["wall_s"] if r.get("mode2fair") else None)


rq1 = {}
md += ["", "## RQ1 host proxy: cost per case (laptop GPU Q4_0; sequential-equivalent agent time; swap cost is a board-only quantity and is NOT included)", "",
       "| N domains | n | cheap s (agents) | full s (agents+reasoner) | Mode 2-fair s | full/cheap | reasoner prefill tok | reasoner decode tok | Mode 2 prefill tok | agent calls |", "|---|---|---|---|---|---|---|---|---|---|"]
groups = [("1 (F,D 1-dom)", [r for r in F + Dn if r["n_domains"] == 1])] + [(s, [r for r in B if r["stratum"] == s]) for s in ["2", "3-4", "5+"]]
for nm, rr in groups:
    if not rr:
        continue
    m2 = [r["mode2fair"]["wall_s"] for r in rr if r.get("mode2fair")]
    d = dict(n=len(rr), cheap=round(np.mean([cost(r, "cheap") for r in rr]), 2), full=round(np.mean([cost(r, "full") for r in rr]), 2), m2=round(np.mean(m2), 2) if m2 else None,
             pre=round(np.mean([r["reasoner"]["prefill_tokens"] for r in rr])), dec=round(np.mean([r["reasoner"]["decode_tokens"] for r in rr])),
             m2pre=round(np.mean([r["mode2fair"]["prefill_tokens"] for r in rr if r.get("mode2fair")] or [0])), calls=round(np.mean([r["triggers"]["n_agents"] for r in rr]), 2))
    d["ratio"] = round(d["full"] / d["cheap"], 2); rq1[nm] = d
    md.append("| %s | %d | %s | %s | %s | %sx | %s | %s | %s | %s |" % (nm, d["n"], d["cheap"], d["full"], d["m2"], d["ratio"], d["pre"], d["dec"], d["m2pre"], d["calls"]))
res["rq1"] = rq1

# ---------------------------------------------------------------- RQ3
U = [r for r in B + Dn + Fi]
T = lambda k: (lambda r: bool(r["triggers"][k]))
unc = lambda r: bool(r["triggers"]["agent_low_conf"] or r["triggers"]["agent_invalid"] or r["triggers"]["agent_asked_more"] or any(x in ("suspect", "fault") for x in r["triggers"]["agent_dq"]))
POL = {"domains>=2": lambda r: r["triggers"]["n_domains_flagged"] >= 2, "any critical": T("any_critical"), "rules-vs-agent disagree": T("rule_agent_disagree"),
       "agent uncertain": unc, "site-tree links": T("site_linked")}
base = dict(POL)
POL["domains>=2 OR critical"] = lambda r: base["domains>=2"](r) or base["any critical"](r)
POL["domains>=2 OR disagree"] = lambda r: base["domains>=2"](r) or base["rules-vs-agent disagree"](r)
POL["critical OR disagree"] = lambda r: base["any critical"](r) or base["rules-vs-agent disagree"](r)
POL["disagree OR uncertain"] = lambda r: base["rules-vs-agent disagree"](r) or base["agent uncertain"](r)
POL["domains>=2 OR crit OR disagree OR uncertain"] = lambda r: any(base[k](r) for k in ("domains>=2", "any critical", "rules-vs-agent disagree", "agent uncertain"))
POL["never (cheap)"] = lambda r: False
POL["always (full)"] = lambda r: True
POL["oracle"] = lambda r: bool(ok(r, "full") and not ok(r, "cheap"))
orc = [POL["oracle"](r) for r in U]
rq3 = {}
md += ["", "## RQ3: offline trigger study (universe: B + D + F-injected = %d gold-labelled cases; policy = escalate to the full path when the trigger fires, else keep the cheap report)" % len(U), "",
       "Cost = host seconds per case (agents always; reasoner only when escalated). Oracle escalates exactly when full is right and cheap is wrong (%d of %d cases = %s %%, not implementable).  Precision/recall are against that oracle.  Domain count here = flagged domains (the app's own rule also counts informative context domains).".replace("  ", " ") % (sum(orc), len(U), round(100 * np.mean(orc), 1)), "",
       "| policy | escalation rate % | both-correct % [95% CI] | label % | severity % | host s/case | precision vs oracle | recall vs oracle |", "|---|---|---|---|---|---|---|---|"]
pts = []
for nm, pf in POL.items():
    esc = [pf(r) for r in U]
    out = [(r, "full" if e else "cheap") for r, e in zip(U, esc)]
    both = ci([ok(r, a) for r, a in out]); lb = ci([ok(r, a, "label") for r, a in out]); sv = ci([ok(r, a, "sev") for r, a in out])
    c = np.mean([cost(r, "full") if e else cost(r, "cheap") for r, e in zip(U, esc)])
    tp = sum(1 for e, o in zip(esc, orc) if e and o); prec = tp / max(1, sum(esc)) if sum(esc) else None; rec = tp / max(1, sum(orc))
    rq3[nm] = dict(esc_rate=round(100 * np.mean(esc), 1), both=both, label=lb[0], sev=sv[0], cost=round(float(c), 2), precision=None if prec is None else round(prec, 3), recall=round(rec, 3))
    pts.append((nm, rq3[nm]["esc_rate"], both[0], float(c)))
    md.append("| %s | %s | %s | %s | %s | %.2f | %s | %s |" % (nm, rq3[nm]["esc_rate"], fmt(both), lb[0], sv[0], c, rq3[nm]["precision"], rq3[nm]["recall"]))
rq3["_oracle_share_pct"] = round(100 * np.mean(orc), 1)
md += ["", "Escalation rate per trigger by stratum (percent of cases the trigger fires):", "", "| trigger | B N=2 | B N=3-4 | B N=5+ | D | F-injected | A (natural, unscored) |", "|---|---|---|---|---|---|---|"]
for nm in list(base):
    row = [nm]
    for rr in ([r for r in B if r["stratum"] == s] for s in ("2", "3-4", "5+")):
        row.append(round(100 * np.mean([base[nm](r) for r in rr]), 1))
    for rr in (Dn, Fi, A):
        row.append(round(100 * np.mean([base[nm](r) for r in rr]), 1) if rr else "-")
    md.append("| " + " | ".join(str(x) for x in row) + " |")
res["rq3"] = rq3
fig, ax = plt.subplots(figsize=(7.5, 5))
for nm, x, y, c in pts:
    ax.scatter(x, y, s=60 if nm in ("oracle", "never (cheap)", "always (full)") else 30, marker="*" if nm == "oracle" else "o")
    ax.annotate(nm, (x, y), fontsize=6, xytext=(3, 3), textcoords="offset points")
ax.set_xlabel("share escalated to the full path (%)"); ax.set_ylabel("label+severity accuracy (%)"); ax.set_title("RQ3 cost-accuracy (B+D+F-injected, host)"); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(OUT + "/fig_rq3_cost_accuracy.png", dpi=140); plt.close(fig)
fig, ax = plt.subplots(figsize=(7.5, 4.5))
xs = np.arange(3); w = .2
for i, a in enumerate(["cheap", "cheap_x", "full", "m2"]):
    v = [rq2["%s|%s" % (s, a)]["both"] for s in ("2", "3-4", "5+")]
    ax.bar(xs + i * w, [t[0] for t in v], w, yerr=[[t[0] - t[1] for t in v], [t[2] - t[0] for t in v]], label=a, capsize=2)
ax.set_xticks(xs + 1.5 * w); ax.set_xticklabels(["N=2", "N=3-4", "N=5+"]); ax.set_ylabel("label+severity accuracy (%)"); ax.legend(fontsize=7); ax.set_title("RQ2 by stratum (Set B injected, 95% CI)")
fig.tight_layout(); fig.savefig(OUT + "/fig_rq2_by_stratum.png", dpi=140); plt.close(fig)
fig, ax = plt.subplots(figsize=(6.5, 4))
ks = list(rq1)
for i, (k_, lab_) in enumerate((("cheap", "cheap"), ("full", "full"), ("m2", "Mode 2-fair"))):
    ax.bar(np.arange(len(ks)) + i * .27, [rq1[k][k_] or 0 for k in ks], .27, label=lab_)
ax.set_xticks(np.arange(len(ks)) + .27); ax.set_xticklabels(ks, fontsize=7); ax.set_ylabel("host s per case"); ax.legend(); ax.set_title("RQ1 host proxy (no swap)")
fig.tight_layout(); fig.savefig(OUT + "/fig_rq1_cost.png", dpi=140); plt.close(fig)

# ---------------------------------------------------------------- A
md += ["", "## Set A: natural replay (n=%d, unscored): routing and short-circuit" % len(A), ""]
if A:
    ares = dict(app_would_escalate=round(100 * np.mean([r["triggers"]["app_would_escalate"] for r in A]), 1), short_circuit=round(100 * np.mean([r["short_circuit_fired"] for r in A]), 1),
                flagged_dom_ge2=round(100 * np.mean([r["triggers"]["n_domains_flagged"] >= 2 for r in A]), 1), any_critical=round(100 * np.mean([r["triggers"]["any_critical"] for r in A]), 1),
                disagree=round(100 * np.mean([r["triggers"]["rule_agent_disagree"] for r in A]), 1), discord=round(100 * np.mean([lab(r["cheap"]) != lab(r["full"]) or sev(r["cheap"]) != sev(r["full"]) for r in A]), 1),
                full_s=round(np.mean([cost(r, "full") for r in A]), 2), cheap_s=round(np.mean([cost(r, "cheap") for r in A]), 2))
    res["A"] = ares
    md.append("- App routing rule (>= 2 domains incl. informative context) would escalate %s %% (short-circuit rate %s %%); flagged domains >= 2 in %s %%; the set was sampled 86/14 single/multi (no natural 5+ windows exist). Any-critical %s %%, rules-vs-agent disagreement %s %%. Cheap vs full discordance %s %% (unscored). Host cost: cheap %s s, full %s s per case." % (
        ares["app_would_escalate"], ares["short_circuit"], ares["flagged_dom_ge2"], ares["any_critical"], ares["disagree"], ares["discord"], ares["cheap_s"], ares["full_s"]))
    md.append("- Real-data note: natural windows are dominated by feeder power-factor dips and PM/CO2 sensor quirks (see Caveats), so rates here describe this campus in this period, not a general workload.")

# ---------------------------------------------------------------- health, appendix, caveats
h = [r["reasoner"] for r in recs]
md += ["", "## Run health", "", "- Reasoner valid %s %% over %d cases; fallback template fired %d; think on %s %%; tool calls %d; Mode 2-fair valid %s %% (n=%d)." % (
    round(100 * np.mean([x["valid"] for x in h]), 1), len(h), sum(x["fallback_fired"] for x in h), round(100 * np.mean([x["think_on"] for x in h]), 1), sum(len(x["tool_calls"]) for x in h),
    round(100 * np.mean([r["mode2fair"]["valid"] for r in recs if r.get("mode2fair")] or [0]), 1), sum(1 for r in recs if r.get("mode2fair"))),
       "", "## Appendix: BLEU / ROUGE / chrF", "", "Not computed: the frozen sets carry gold label, severity and affected domains by construction but no gold report text (RESEARCH_PAPER.md section 7 demotes these metrics because part of any gold text is self-distilled). Reasoner texts are in records.jsonl for a later judge-based or text-metric pass.",
       "", "## Caveats", "",
       "- **Thin post-cutoff data.** Real baselines come only from the 20 days after the 2025-12-11 cutoff. Weather exists for about 3.8 days, outdoor PM for 6.7, occupancy and water level essentially never; weather families therefore cluster in a few days and N=5+ cases reuse the same windows with different injections. Effective independent baselines are far fewer than 153.",
       "- **CO2 re-base.** The campus CO2 sensor reads physically implausibly low (median 364 ppm, 44 %% of windows rule-flagged as sensor_fault), so injections level-shift the pre-event CO2 to 430-520 ppm; occupancy baseline is held vacant and the event injected.",
       "- **Cheap label mapping artefact.** The Go template maps the LEAD sensor's agent cause through causeToLabel and reports one domain (and `normal_operation` for causes it does not map). At N >= 2 this makes low cheap label / domain scores partly structural. Mapping-corrected (any flagged agent's label) accuracy is given in RQ2; cheap_x is the cross-domain template. Cheap severity is derived from the lead finding's status (Go's isolatedReport has no severity field).",
       "- **Python rule mirror.** Rule status / patterns come from the training-time rules (generate_dataset.py + features.py), not rules.go with per-node card thresholds; disagreement, critical and domain-count trigger inputs are approximate. 'Flagged' sensors are the injected ones (occupancy and hvac forced into the incident in the 5+ family), not what the live alert path would have promoted.",
       "- **Gold by construction.** Injected gold labels encode one root-cause story per family; reasonable alternative labels (e.g. hvac_or_thermal_issue for a heat chain) count as wrong. Injection generators are separate from training generators but share the stories (LEAKAGE.md).",
       "- **Mode 2-fair** = reasoner model + reasoner prompt with every agent line removed (raw evidence only, context sensors kept), no tools.",
       "- **Host proxy only.** Costs are laptop-GPU Q4_0 seconds; swap, streams and thermal pacing exist only on the board (Set C). Agent time is the sequential sum of per-call times (the run used np=4).",
       "- Retrieval off (empty frozen corpus); no retrieval ablation."]
open(D.PAPER + "/RESULTS.md", "w", newline="\n").write("\n".join(md) + "\n")
json.dump(res, open(OUT + "/results.json", "w", newline="\n"), indent=1, default=str)
print("\n".join(md[:60]))
