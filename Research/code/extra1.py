"""extra1.py: item 1 extra metrics from runs/full/records.jsonl (no new runs). Output results/extra1.json + section appended to RESULTS.md by extra1_md.py"""
import json, re, collections, numpy as np, math
from scipy.stats import wilcoxon
from sklearn.metrics import f1_score, confusion_matrix
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-26_paper"
recs = [json.loads(l) for l in open(P + "/runs/full/records.jsonl")]
rng = np.random.default_rng(1)
SEV = ["normal", "warning", "critical", "sensor_fault"]
def rep(r, a):
    if a == "m2":
        return (r.get("mode2fair") or {}).get("report")
    return r[a]
ARMS = ["cheap", "cheap_x", "full", "m2"]
G = [r for r in recs if r["gold"] and r["set"] in ("B", "D", "F")]
out = {"n_gold": len(G)}
# severity macro-F1 + confusion
sevres = {}
for a in ARMS:
    rr = [r for r in G if rep(r, a) and (a != "m2" or r["set"] in "BD")]
    y = [r["gold"]["severity"] for r in rr]; p = [(rep(r, a).get("severity") or "none") for r in rr]
    labs = SEV
    f = f1_score(y, p, labels=labs, average="macro", zero_division=0)
    idx = np.arange(len(y)); bs = []
    ya, pa = np.array(y), np.array(p)
    for _ in range(1000):
        i = rng.choice(idx, len(idx)); bs.append(f1_score(ya[i], pa[i], labels=labs, average="macro", zero_division=0))
    sevres[a] = dict(n=len(y), macro_f1=round(f, 3), ci=[round(np.percentile(bs, 2.5), 3), round(np.percentile(bs, 97.5), 3)],
                     per_class=dict(zip(labs, [round(x, 3) for x in f1_score(y, p, labels=labs, average=None, zero_division=0)])),
                     cm=confusion_matrix(y, p, labels=labs).tolist())
out["severity"] = sevres
# affected domain F1
def dset(x):
    d = x.get("affected_domains") or []
    return set(d) if isinstance(d, list) else set()
dres = {}
for a in ARMS:
    f1s = []; tp = fp = fn = 0
    for r in G:
        if r["set"] == "D" or not rep(r, a) or (a == "m2" and r["set"] not in "BD"): continue
        g = set(r["gold"]["affected_domains"]); p = dset(rep(r, a))
        t = len(g & p); tp += t; fp += len(p - g); fn += len(g - p)
        pr = t / len(p) if p else 0; rc = t / len(g) if g else 0
        f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0)
    mp = tp / (tp + fp) if tp + fp else 0; mr = tp / (tp + fn) if tp + fn else 0
    dres[a] = dict(n=len(f1s), mean_case_f1=round(float(np.mean(f1s)), 3), micro_f1=round(2 * mp * mr / (mp + mr), 3) if mp + mr else 0, micro_p=round(mp, 3), micro_r=round(mr, 3))
out["domains"] = dres
# grounding
IDS = re.compile(r"\bS\d+\.E\d+\b"); NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
def txt(x):
    parts = [x.get("root_cause") or "", x.get("explanation") or "", x.get("causal_chain") or "", x.get("title") or ""]
    for o in x.get("observations") or []:
        parts.append(o.get("text", "") if isinstance(o, dict) else str(o))
    return " ".join(parts)
gres = {}
for a in ["full", "m2", "cheap", "cheap_x"]:
    valid = tot = 0; cov = []; ung = 0; nn = 0; ncase = 0
    for r in recs:
        if r["set"] == "A" or not rep(r, a) or (a == "m2" and r["set"] not in "BD"): continue
        if not r["reasoner"] or "user" not in r["reasoner"]: continue
        prompt = r["reasoner"]["user"]
        have = set(IDS.findall(prompt)); pnums = set(NUM.findall(prompt))
        ev = rep(r, a).get("evidence") or []
        ev = [e for e in ev if isinstance(e, str)]
        ncase += 1
        valid += sum(1 for e in ev if e in have); tot += len(ev)
        flagged = set(re.findall(r"^(S\d+) \[FLAGGED\]", prompt, re.M))
        cited = set(e.split(".")[0] for e in ev)
        if flagged: cov.append(len(flagged & cited) / len(flagged))
        for n in NUM.findall(txt(rep(r, a))):
            nn += 1; ung += (n not in pnums and n.lstrip("-") not in pnums)
    gres[a] = dict(cases=ncase, evidence_ids=tot, id_validity=round(valid / tot, 4) if tot else None, flagged_sensor_coverage=round(float(np.mean(cov)), 3) if cov else None,
                   numbers=nn, ungrounded_number_rate=round(ung / nn, 4) if nn else None)
out["grounding"] = gres
# latency
def wall(r, a):
    ag = r["agents_wall_s_total"] or 0
    if a == "cheap": return ag
    if a == "full": return ag + ((r["reasoner"] or {}).get("wall_s") or 0)
    if a == "m2": return (r.get("mode2fair") or {}).get("wall_s")
lat = {}
sub = [r for r in recs if r.get("mode2fair")]
def med(v): return round(float(np.median(v)), 2)
for a, b in [("full", "cheap"), ("full", "m2"), ("m2", "cheap")]:
    x = np.array([wall(r, a) for r in sub], float); y = np.array([wall(r, b) for r in sub], float)
    w = wilcoxon(x, y)
    lat["%s_vs_%s" % (a, b)] = dict(n=len(sub), median_a=med(x), median_b=med(y), median_diff=med(x - y), W=float(w.statistic), p=float(w.pvalue))
out["latency"] = lat
out["retrieval"] = dict(hits_nonzero=sum(1 for r in recs if r["retrieval_hits"]), n=len(recs), tool_calls_cases=sum(1 for r in recs if r["reasoner"] and (r["reasoner"].get("tool_calls") or [])))
json.dump(out, open(P + "/results/extra1.json", "w"), indent=1)
print(json.dumps(out, indent=1)[:5000])
