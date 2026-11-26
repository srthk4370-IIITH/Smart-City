"""baselines.py (item 5): classical baselines on Set B + D (n=218) vs the LLM arms, anomaly-vs-normal and (rules only) severity/label.
 Mode 1 rules-only : the rule finding of the lead flagged sensor (pcore.rule_finding, python mirror of rules.go) -> severity = its status, label = causeToLabel
 Isolation Forest  : per sensor key, fitted on real PRE-cutoff windows (never the test windows), window features; alarm threshold = 90th percentile of held-out pre-cutoff scores
 STL + threshold   : STL (period 288 = 1 day, robust) on 7 days of real history before the window + the case window; alarm when max |residual| over the 12 h case window
                     exceeds K x the robust sigma of the history residual (K = 4; also AUROC on the continuous score). The case window carries the injection; history is real.
 Gold anomaly = gold severity != normal (B: all 153 anomalies; D: 50 normal, 15 real sensor faults). Case score = max over its flagged sensors."""
import json, sys, math, random, numpy as np
import env_setup as ES
import pdata as D, pcase as P, pcore as C
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score
from statsmodels.tsa.seasonal import STL
rng = random.Random(26112605); np.random.seed(26112605)
cases = []
for n in "BD":
    cases += [json.loads(l) for l in open("%s/sets/%s.jsonl" % (D.PAPER, n))]
recs = {}
for l in open(D.PAPER + "/runs/full/records.jsonl"):
    r = json.loads(l); recs[r["id"]] = r
print("cases", len(cases), flush=True)


def feats(x):
    x = np.asarray(x, float); t = np.arange(len(x))
    sl = np.polyfit(t, x, 1)[0]
    d = np.abs(np.diff(x))
    return [x.mean(), x.std(), x.min(), x.max(), x[-1], sl * len(x), d.max(), x[-48:].mean() - x[:48].mean(), x[-12:].mean() - x[:-12].mean(), np.median(x)]


IF = {}
for s in D.SENSORS:
    ts, _ = D.raw(s["node"], s["metric"])
    lo, hi = ts[0] + 12 * 3600, D.CUTOFF - 3600
    W = []
    for _ in range(3000):
        T = rng.randrange(lo // 300, hi // 300) * 300
        w = D.window(s["node"], s["metric"], T, 144)
        if w is not None:
            W.append(C.rnd(w, s["role"], s["metric"]))
        if len(W) >= 500:
            break
    if len(W) < 60:
        print("few windows", s["key"], len(W)); continue
    F = np.array([feats(w) for w in W]); mu, sd = F.mean(0), F.std(0) + 1e-9
    k = int(0.8 * len(F)); Z = (F - mu) / sd
    m = IsolationForest(n_estimators=200, random_state=1, n_jobs=1).fit(Z[:k])
    thr = np.percentile(-m.score_samples(Z[k:]), 90)
    IF[s["key"]] = (m, mu, sd, thr, len(W))
print("IF fitted", {k: v[4] for k, v in IF.items()}, flush=True)


def if_score(key, x):
    if key not in IF:
        return None
    m, mu, sd, thr, _ = IF[key]
    return float(-m.score_samples(((np.array([feats(x)]) - mu) / sd))[0]) / thr


def hist_series(node, metric, end):
    n = 7 * 288
    start = end - 144 * 300
    xs = [D.value_at(node, metric, start - 300 * (n - i)) for i in range(n)]
    if sum(x is not None for x in xs) < 0.8 * n:
        return None
    last = next(x for x in xs if x is not None)
    out = []
    for x in xs:
        if x is None:
            x = last
        else:
            last = x
        out.append(x)
    return out


def stl_score(sd, x, end):
    h = hist_series(sd["node"], sd["metric"], end)
    if h is None:
        return None
    y = np.array(h + list(x), float)
    res = STL(y, period=288, robust=True).fit().resid
    hr = res[:len(h)]
    sig = 1.4826 * np.median(np.abs(hr - np.median(hr))) + 1e-9
    return float(np.max(np.abs(res[-144:])) / sig)


rows = []
for c in cases:
    ser = c["series"]; a = P.assemble(c)
    lead = a["sensors"][0]["rule"]
    flagged = [s for s in a["sensors"] if s["flagged"]]
    anyrule = any(s["rule"]["status"] != "normal" for s in flagged)
    ifs = [v for v in (if_score(s["sdef"]["key"], ser[s["sdef"]["key"]]) for s in flagged) if v is not None]
    sts = [v for v in (stl_score(s["sdef"], ser[s["sdef"]["key"]], c["end"]) for s in flagged) if v is not None]
    rows.append(dict(id=c["id"], set=c["set"], gold=c["gold"], rule_status=lead["status"], rule_label=P.CAUSE_TO_LABEL.get(lead["likely_cause"], "") or "normal_operation",
                     rule_any=anyrule, if_score=max(ifs) if ifs else None, stl_score=max(sts) if sts else None, family=c["family"]))
    if len(rows) % 40 == 0:
        print(len(rows), flush=True)
json.dump(rows, open(D.PAPER + "/results/baselines_rows.json", "w"))


def auc(y, s):
    pr = [(a, b) for a, b in zip(y, s) if b is not None]
    return round(roc_auc_score([a for a, _ in pr], [b for _, b in pr]), 3)


def metrics(pred, rs):
    y = [r["gold"]["severity"] != "normal" for r in rs]; p = [bool(pred(r)) for r in rs]
    B_ = [b for a, b, r in zip(y, p, rs) if r["set"] == "B"]; N_ = [b for a, b, r in zip(y, p, rs) if r["set"] == "D" and not a]; Fa = [b for a, b, r in zip(y, p, rs) if r["set"] == "D" and a]
    rec = sum(B_) / len(B_); fpr = sum(N_) / len(N_); frec = sum(Fa) / len(Fa)
    tp = sum(1 for a, b in zip(y, p) if a and b); fp = sum(1 for a, b in zip(y, p) if not a and b); fn = sum(1 for a, b in zip(y, p) if a and not b)
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0
    return dict(recall_B=round(rec, 3), fpr_normal=round(fpr, 3), recall_fault=round(frec, 3), f1=round(f1, 3), balanced_acc=round((rec + (1 - fpr)) / 2, 3))


def boot(pred, n=1000):
    idx = np.arange(len(rows)); v = []
    for _ in range(n):
        i = np.random.choice(idx, len(idx)); v.append(metrics(pred, [rows[j] for j in i])["f1"])
    return [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]


out = {"n": len(rows)}
Y = [r["gold"]["severity"] != "normal" for r in rows]
PR = {"Mode 1 rules-only (any flagged sensor non-normal)": lambda r: r["rule_any"],
      "Isolation Forest (score>1)": lambda r: r["if_score"] is not None and r["if_score"] > 1,
      "STL + threshold (K=4)": lambda r: r["stl_score"] is not None and r["stl_score"] > 4}
for a, nm in [("cheap", "cheap (agents + template)"), ("cheap_x", "cheap_x"), ("full", "full (agents + reasoner)"), ("m2", "Mode 2-fair")]:
    def pr(r, a=a):
        rec = recs[r["id"]]; x = rec["mode2fair"]["report"] if a == "m2" else rec[a]
        return (x or {}).get("severity") not in (None, "normal")
    PR[nm] = pr
arms = {}
for nm, f in PR.items():
    arms[nm] = metrics(f, rows); arms[nm]["ci_f1"] = boot(f)
arms["Isolation Forest (score>1)"]["auroc"] = auc(Y, [r["if_score"] for r in rows])
arms["STL + threshold (K=4)"]["auroc"] = auc(Y, [r["stl_score"] for r in rows])
out["anomaly"] = arms
out["sweep"] = {"stl": {str(K): metrics(lambda r, K=K: r["stl_score"] is not None and r["stl_score"] > K, rows) for K in (3, 4, 6, 8, 12, 20)},
                "if": {str(t): metrics(lambda r, t=t: r["if_score"] is not None and r["if_score"] > t, rows) for t in (0.8, 1.0, 1.2, 1.5)}}
sev = [r["rule_status"] == r["gold"]["severity"] for r in rows]; lab = [r["rule_label"] == r["gold"]["label"] for r in rows]
both = [a and b for a, b in zip(sev, lab)]
isB = [r["set"] == "B" for r in rows]
out["mode1"] = dict(severity_acc=round(float(np.mean(sev)), 3), label_acc=round(float(np.mean(lab)), 3), both=round(float(np.mean(both)), 3),
                    B_both=round(float(np.mean([x for x, b in zip(both, isB) if b])), 3), B_sev=round(float(np.mean([x for x, b in zip(sev, isB) if b])), 3),
                    B_label=round(float(np.mean([x for x, b in zip(lab, isB) if b])), 3), n_if=sum(r["if_score"] is not None for r in rows), n_stl=sum(r["stl_score"] is not None for r in rows))
json.dump(out, open(D.PAPER + "/results/baselines.json", "w"), indent=1)
print(json.dumps(out, indent=1))
