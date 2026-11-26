"""extra34.py: analysis + RESULTS.md sections for item 4 (Mode 3 ablations on Set B) and item 3 (Mode 2 as built on B+D).
Inputs: runs/full/records.jsonl, runs/full/reasoner_abl_{nt,nc}_out.jsonl, runs/full/mode2_asbuilt.jsonl. Output: results/extra34.json (+ markdown printed to results/extra34.md).
Arms (Set B, n=153, 'both' = label AND severity match gold):
  full            : main run (tools on, context agents on, guards on: invalid -> cross-domain template fallback)
  no tools        : tools=None (covers 'no retrieval' and 'no more-data tool calls': the corpus was empty so retrieval returned nothing anyway)
  no context agents: only the flagged sensors in the reasoner prompt (context sensors + their rule/agent lines removed)
  no guards       : the SAME raw reasoner output as 'full', but an invalid report (bad JSON / label / severity) counts as wrong instead of being replaced by the template fallback
Mode 2 as built: agent model + singlePrompt, B+D, severity = ruleSeverity (the report has no severity key), policy gate = JSON parses and label in ReportLabels else rule-fallback template."""
import json, os, re, math, numpy as np
import env_setup as ES
import pdata as D, pcase as P
PAPER = D.PAPER
RUN = PAPER + "/runs/full"
recs = {}
for l in open(RUN + "/records.jsonl"):
    r = json.loads(l); recs[r["id"]] = r
LABELS = P.REPORT_LABELS; SEVS = {"normal", "warning", "critical", "sensor_fault"}
RNG = np.random.default_rng(11)


def parse_report(txt):
    t = (txt or "").strip(); t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        o = json.loads(t); return o if isinstance(o, dict) else None
    except Exception:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try: return json.loads(t[i:j + 1])
            except Exception: return None
    return None


def load(p):
    out = {}
    if os.path.exists(p):
        for l in open(p):
            o = json.loads(l); out[o["id"]] = o
    return out


def mcnemar(a, b):
    n10 = sum(1 for x, y in zip(a, b) if x and not y); n01 = sum(1 for x, y in zip(a, b) if y and not x); n = n10 + n01
    if n == 0: return dict(b=n10, c=n01, p=1.0)
    k = min(n10, n01); p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return dict(b=n10, c=n01, p=round(p, 4))


def ci(v):
    v = np.array(v, float); bs = RNG.choice(v, (2000, len(v))).mean(1)
    return "%.1f [%.1f, %.1f]" % (100 * v.mean(), 100 * np.percentile(bs, 2.5), 100 * np.percentile(bs, 97.5))


def paired_ci(a, b):
    d = np.array(a, float) - np.array(b, float); idx = np.arange(len(d)); bs = [d[RNG.choice(idx, len(d))].mean() for _ in range(2000)]
    return "%+.1f [%+.1f, %+.1f]" % (100 * d.mean(), 100 * np.percentile(bs, 2.5), 100 * np.percentile(bs, 97.5))


def score(x, g):
    if not x: return (False, False)
    return (x.get("label") == g["label"], x.get("severity") == g["severity"])


md, js = [], {}
Bc = sorted([r for r in recs.values() if r["set"] == "B"], key=lambda r: r["id"])


def build_arms(Bsub, tags):
    arms = {"full (main, guards on)": [r["full"] for r in Bsub]}
    for tag, nm in tags:
        o = load("%s/reasoner_abl_%s_out.jsonl" % (RUN, tag))
        if not all(r["id"] in o for r in Bsub):
            md.append("- ablation `%s`: only %d of %d cases finished; not reported." % (tag, sum(r["id"] in o for r in Bsub), len(Bsub))); continue
        xs = []
        for r in Bsub:
            rep = parse_report(((o[r["id"]].get("final") or {}).get("content")))
            ok = bool(rep) and rep.get("label") in LABELS and rep.get("severity") in SEVS
            xs.append(rep if ok else r["cheap_x"])
        arms[nm] = xs
    arms["no guards (invalid output counts as wrong)"] = [r["reasoner"]["report"] if r["reasoner"]["valid"] else None for r in Bsub]
    return arms


def table(title, Bsub, arms, tags):
    md.extend(["", title, "", "| arm | label % | severity % | both % [95% CI] | both, paired diff vs full (pp) [95% CI] | McNemar b / c / p (b = arm right & full wrong) |", "|---|---|---|---|---|---|"])
    base = [all(score(x, r["gold"])) for x, r in zip(arms["full (main, guards on)"], Bsub)]
    for nm, xs in arms.items():
        sc = [score(x, r["gold"]) for x, r in zip(xs, Bsub)]; both = [a and b for a, b in sc]
        mn = mcnemar(both, base) if not nm.startswith("full") else None
        md.append("| %s | %s | %s | %s | %s | %s |" % (nm, ci([a for a, _ in sc]), ci([b for _, b in sc]), ci(both), paired_ci(both, base) if mn else "-", ("%d / %d / %s" % (mn["b"], mn["c"], mn["p"])) if mn else "-"))
        js.setdefault(title[:40], {})[nm] = dict(n=len(Bsub), both=float(np.mean(both)), label=float(np.mean([a for a, _ in sc])), sev=float(np.mean([b for _, b in sc])), mcnemar_vs_full=mn)
    for tag, _ in tags:
        o = load("%s/reasoner_abl_%s_out.jsonl" % (RUN, tag)); oo = [o[r["id"]] for r in Bsub if r["id"] in o]
        if oo:
            md.append("- `%s`: mean reasoner wall %.2f s (main run, same cases %.2f s), mean prefill tokens %.0f (main %.0f)" % (tag, np.mean([x["wall_s"] for x in oo]), np.mean([r["reasoner"]["wall_s"] for r in Bsub]),
                      np.mean([sum(t.get("prompt_n") or 0 for t in x["turns"]) for x in oo]), np.mean([r["reasoner"]["prefill_tokens"] for r in Bsub])))


md += ["", "## Mode 3 ablations (item 4; extra34.py, results/extra34.json)", "",
       "Guards = the validity gate (JSON + label + severity enums) with the cross-domain template as fallback; 'no guards' scores the same raw reasoner output but an invalid report counts as wrong. The Go severity guard (rule anchor) is not part of the python pipeline and is not ablated."]
Bnt = Bc
RT = [("nt", "no tools (no retrieval, no more-data)"), ("rt", "retrieval ON (populated past-incident store: MEMORY + incident tools)")]
table("### Set B, all %d cases: no tools / no retrieval, retrieval ON, no guards" % len(Bnt), Bnt, build_arms(Bnt, RT), [("nt", ""), ("rt", "")])
_rt = load(RUN + "/reasoner_abl_rt_out.jsonl")
if _rt:
    _st = json.load(open(RUN + "/retrieval_store.json"))
    _mem = [x["user"].count(chr(10) + "  M") for x in _rt.values()]
    md.append("- `rt` store: %d past incidents (%d closed with an outcome: sensor_fault gold -> sensor_repaired, normal -> no_action_needed, other -> fixed_by_action; outcomes simulated from gold of OTHER, earlier cases, >= 12 h before the case window). MEMORY lines reached %d of %d prompts (mean %.2f lines, max 3). Tool calls: %d of %d cases." %
              (len(_st), sum(1 for x in _st if x.get("outcome")), sum(1 for m in _mem if m), len(_mem), float(np.mean(_mem)), sum(1 for x in _rt.values() if x["calls"]), len(_rt)))
by = {}
for r in Bc: by.setdefault(r["stratum"], []).append(r)
B60 = sorted([r for k in sorted(by) for r in by[k][:20]], key=lambda r: r["id"])
table("### Fixed stratified 60 of Set B (20 per N stratum, host speed): no context agents", B60, build_arms(B60, [("nt", "no tools (no retrieval, no more-data)"), ("nc", "no context agents")]), [("nc", "")])
md.append("")
md.append("Retrieval note: the paper runs used an empty frozen corpus; the reasoner called a tool in only %d of %d Set-B cases and every call returned an empty result, so 'no retrieval' and 'no tools / no more-data' are the same ablation here (the `rt` arm above repeats Set B with a populated store)." %
          (sum(1 for r in Bc if r["reasoner"]["tool_calls"]), len(Bc)))
# ---------------------------------------------------------------- Mode 2 as built
m2 = load(RUN + "/mode2_asbuilt.jsonl")
if len(m2) >= 218:
    cases = {}
    for n in "BD":
        for l in open("%s/sets/%s.jsonl" % (PAPER, n)):
            c = json.loads(l); cases[c["id"]] = c
    rank = {"critical": 3, "warning": 2, "sensor_fault": 1, "normal": 0}
    rows = []
    for cid, o in m2.items():
        c = cases[cid]; a = P.assemble(c); rec = recs[cid]
        flagged = [s for s in a["sensors"] if s["flagged"]]
        sev = max((s["rule"]["status"] for s in flagged), key=lambda s: rank.get(s, 0))
        rep = parse_report(o["text"]); valid = bool(rep) and rep.get("label") in LABELS
        if not valid:
            P_ = P.place_env(cid)
            sens = [dict(ref=s["ref"], role=s["sdef"]["role"], metric=s["sdef"]["metric"], node=s["sdef"]["node"], loc=P_.loc(P_.host.get(s["sdef"]["node"], P_.room)), context=not s["flagged"], rule=s["rule"]) for s in a["sensors"]]
            rep = P.fallback_report(sens, [(None, False) if s["flagged"] else (s["rule"], True) for s in a["sensors"]])
        rows.append(dict(id=cid, set=c["set"], gold=c["gold"], label=(rep or {}).get("label"), sev=sev, valid=valid, wall=o["wall_s"], prompt_tokens=o.get("prompt_tokens"),
                         raw_label=(parse_report(o["text"]) or {}).get("label")))
    rows.sort(key=lambda r: r["id"])
    ids = [r["id"] for r in rows]
    full_ok = [all(score(recs[i]["full"], recs[i]["gold"])) if recs[i]["gold"] and recs[i]["set"] == "B" else None for i in ids]
    md += ["", "## Mode 2 as built (item 3; agent model agt3_s0450 Q4_0 + singlePrompt port; Set B + D; mode2_asbuilt.py, results/extra34.json)", "",
           "Severity = ruleSeverity of the flagged sensors (this mode's report has no severity key; the Go reasonerSeverity guard is not ported). Label gate: JSON parses and label in the 13 report labels, else rule-fallback template (as Go).", "",
           "| set | n | arm | label % | severity % | both % [95% CI] | valid JSON+label % |", "|---|---|---|---|---|---|---|"]
    for st in ("B", "D"):
        rr = [r for r in rows if r["set"] == st]
        for nm, f in (("Mode 2 as built (agent model, old prompt)", lambda r: (r["label"] == r["gold"]["label"], r["sev"] == r["gold"]["severity"])),
                      ("Mode 2-fair (reasoner, no agents)", lambda r: score(recs[r["id"]]["mode2fair"]["report"], r["gold"])),
                      ("Mode 3 full", lambda r: score(recs[r["id"]]["full"], r["gold"])), ("cheap (Mode 3 template)", lambda r: score(recs[r["id"]]["cheap"], r["gold"]))):
            sc = [f(r) for r in rr]; both = [a and b for a, b in sc]
            md.append("| %s | %d | %s | %s | %s | %s | %s |" % (st, len(rr), nm, ci([a for a, _ in sc]), ci([b for _, b in sc]), ci(both), ("%.1f" % (100 * np.mean([r["valid"] for r in rr]))) if nm.startswith("Mode 2 as") else "-"))
    Bn = [r for r in rows if r["set"] == "B"]
    asb = [r["label"] == r["gold"]["label"] and r["sev"] == r["gold"]["severity"] for r in Bn]
    for nm, k in (("Mode 3 full", "full"), ("Mode 2-fair", "m2")):
        other = [all(score(recs[r["id"]]["full"] if k == "full" else recs[r["id"]]["mode2fair"]["report"], r["gold"])) for r in Bn]
        m = mcnemar(other, asb); md.append("- Set B both-correct, %s vs Mode 2 as built: b=%d (arm right, as-built wrong) c=%d p=%s" % (nm, m["b"], m["c"], m["p"]))
    md.append("- Mode 2 as built: mean host wall %.2f s per case, mean prompt tokens %.0f; label invalid -> fallback in %d of %d cases." % (np.mean([r["wall"] for r in rows]), np.mean([r["prompt_tokens"] or 0 for r in rows]), sum(1 for r in rows if not r["valid"]), len(rows)))
    # D: false alarms for as built
    Dn = [r for r in rows if r["set"] == "D" and r["gold"]["severity"] == "normal"]
    md.append("- Set D normal windows (n=%d): as-built reports severity != normal (rule severity) in %.1f %% and a label != normal_operation in %.1f %%." % (len(Dn), 100 * np.mean([r["sev"] != "normal" for r in Dn]), 100 * np.mean([r["label"] != "normal_operation" for r in Dn])))
    js["mode2_asbuilt"] = dict(n=len(rows), B_both=float(np.mean(asb)), valid=float(np.mean([r["valid"] for r in rows])))
else:
    md += ["", "## Mode 2 as built (item 3)", "", "Run not finished (%d of 218 cases)." % len(m2)]
open(PAPER + "/results/extra34.md", "w").write("\n".join(md) + "\n")
json.dump(js, open(PAPER + "/results/extra34.json", "w"), indent=1)
print("\n".join(md))
