"""select_v2.py score SAMPLES.jsonl [call|ans]   -> one-line JSON of the score of one eval set
select_v2.py pick POST REF_DIR OUT.json FINAL_K2 ADAPTER_ROOT [REFTAG=s0300] [ALPHA=0.05]
Selection + no-harm of the top-up v2 against s0300 (the deployed v1 winner). POST/sNNNN/{val,syn,unk,hard,t2,t1}.jsonl = host-eval samples of the merged Q4_0
of every pulled snapshot: val = REAL VAL 400, syn = synthetic slice 120, unk = unseen_metric 100 (the v1 sets), hard = hard-case slice (dev split),
t2 = tool FINAL turns (call + result teacher-forced), t1 = tool TURN 1 (call_ok on gold-call rows, direct_ok = no spurious call on direct rows).
REF_DIR/{val,syn,unk,hard,t2,t1}_s0300.jsonl = s0300 samples. HARM (any one rejects the snapshot):
  - val/syn/unk: a field (status, pattern, cause, dq) worse than s0300 with exact two-sided sign test p < ALPHA (as v1), or a composite score below
    s0300 minus a tolerance (val 0.012, syn 0.025, unk 0.03) on any of the three sets;
  - hard/t2: a field worse with p < ALPHA;  t1: direct_ok worse with p < ALPHA or spurious calls on direct rows above 8 %.
WINNER = highest  val + 0.35*hard + 0.35*t2 + 0.30*t1  among snapshots without harm whose (hard + t2 + t1)/3 beats s0300's by >= 0.02 (otherwise s0300 stays).
exit 0 winner (FINAL_K2 written), 3 none."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("AGT_DIR", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt"), "kaggle"))
import rows as RW  # noqa: E402

FIELDS = ("status", "pattern", "cause", "dq")
TOL = {"val": 0.012, "syn": 0.025, "unk": 0.03}   # composite-score tolerance per set (n = 400 / 120 / 100)


def rd(p):
    if not os.path.exists(p):
        return None
    return {x["id"]: x for x in (json.loads(l) for l in open(p) if l.strip())}


def acc(s, k):
    v = [x[k] for x in s if x.get(k) is not None]
    return round(sum(bool(t) for t in v) / len(v), 4) if v else None


def agg_ans(s):
    s = list(s)
    d = {k: acc(s, k) for k in ("json",) + FIELDS}
    d.update(score=round(RW.gen_score(s), 5), n=len(s))
    return d


def agg_t1(s):
    s = list(s)
    d = {"json": acc(s, "json"), "call_ok": acc(s, "call_ok"), "direct_ok": acc(s, "direct_ok"), "n": len(s)}
    parts = [d[k] for k in ("call_ok", "direct_ok") if d[k] is not None]
    d["score"] = round(sum(parts) / len(parts), 5) if parts else 0.0
    return d


def paired(c, r, fields, alpha):
    out, harm = {}, []
    ids = sorted(set(c) & set(r))
    if len(ids) < 0.9 * len(c):
        sys.exit("only %d of %d rows pair with the s0300 reference: wrong reference set" % (len(ids), len(c)))
    for k in fields:
        v = [i for i in ids if c[i].get(k) is not None and r[i].get(k) is not None]
        if not v:
            continue
        w = sum(bool(c[i][k]) and not bool(r[i][k]) for i in v)
        l_ = sum(bool(r[i][k]) and not bool(c[i][k]) for i in v)
        p = RW.binom_two_sided(w, l_)
        out[k] = {"cand": round(100 * sum(bool(c[i][k]) for i in v) / len(v), 1), "ref": round(100 * sum(bool(r[i][k]) for i in v) / len(v), 1),
                  "wins": w, "losses": l_, "p": round(p, 4), "n": len(v)}
        if l_ > w and p < alpha:
            out[k]["harm"] = True
            harm.append(k)
    return out, harm


if sys.argv[1] == "score":
    s = [json.loads(l) for l in open(sys.argv[2]) if l.strip()]
    print(json.dumps(agg_t1(s) if len(sys.argv) > 3 and sys.argv[3] == "call" else agg_ans(s)))
    sys.exit(0)
post, refd, outp, finalk, aroot = sys.argv[2:7]
reftag = sys.argv[7] if len(sys.argv) > 7 else "s0300"
ALPHA = float(sys.argv[8]) if len(sys.argv) > 8 else 0.05
SETS = ("val", "syn", "unk", "hard", "t2", "t1")
ref = {k: rd("%s/%s_%s.jsonl" % (refd, k, reftag)) for k in SETS}
if not all(ref.values()):
    sys.exit("missing %s reference samples in %s: %s" % (reftag, refd, [k for k in SETS if not ref[k]]))
agg = lambda k, s: (agg_t1 if k == "t1" else agg_ans)(s)  # noqa: E731
refa = {k: agg(k, ref[k].values()) for k in SETS}
gain = lambda a: (a["hard"]["score"] + a["t2"]["score"] + a["t1"]["score"]) / 3  # noqa: E731
res = []
for d in sorted(glob.glob(post + "/s[0-9][0-9][0-9][0-9]")):
    step = int(os.path.basename(d)[1:])
    smp = {k: rd("%s/%s.jsonl" % (d, k)) for k in SETS}
    if not all(smp.values()):
        continue
    row = {"step": step, "harm": []}
    for k in SETS:
        row[k] = agg(k, smp[k].values())
        row[k + "_vs_ref"], h = paired(smp[k], ref[k], ("call_ok", "direct_ok") if k == "t1" else FIELDS, ALPHA)
        if k == "t1":
            h = [x for x in h if x == "direct_ok"]          # call_ok can only improve over a model that never calls
            if row[k]["direct_ok"] is not None and row[k]["direct_ok"] < 0.92:
                h.append("spurious_calls>8%")
        row["harm"] += ["%s.%s" % (k, f) for f in h]
    for k in ("val", "syn", "unk"):
        if row[k]["score"] < refa[k]["score"] - TOL[k]:
            row["harm"].append("%s.score(-%.3f)" % (k, refa[k]["score"] - row[k]["score"]))
    row["rank"] = round(row["val"]["score"] + 0.35 * row["hard"]["score"] + 0.35 * row["t2"]["score"] + 0.30 * row["t1"]["score"], 5)
    row["gain"] = round(gain(row) - gain(refa), 4)
    g = glob.glob("%s/agt3_s%04d_q4_0.gguf" % (d, step))
    row["gguf"] = g[0] if g else None
    res.append(row)
# DYNAMIC RULE (owner 2026-11-18): weighted delta of slice scores vs s0300 >= +0.02, no slice drops > 0.10; the per-field sign-test harm and
# per-set tolerances are replaced by safety floors: status accuracy (critical/severity) drop <= 0.03 on every set, JSON validity >= 0.98 (or ref's if lower),
# spurious calls on direct rows <= 8 % (kept).
WT = {"val": .25, "syn": .10, "unk": .10, "hard": .20, "t2": .15, "t1": .20}
for r in res:
    r["wd"] = round(sum(WT[k] * (r[k]["score"] - refa[k]["score"]) for k in SETS), 4)
    h = ["%s.spurious_calls>8%%" % "t1" for _ in [0] if r["t1"]["direct_ok"] is not None and r["t1"]["direct_ok"] < 0.92]
    h += ["%s.score(-%.3f)" % (k, refa[k]["score"] - r[k]["score"]) for k in SETS if r[k]["score"] < refa[k]["score"] - 0.10]
    h += ["%s.status" % k for k in ("val", "syn", "unk", "hard", "t2") if (r[k]["status"] or 0) < (refa[k]["status"] or 0) - 0.03]
    h += ["%s.json" % k for k in ("val", "syn", "unk", "hard", "t2", "t1") if (r[k]["json"] or 0) < min(0.98, refa[k]["json"] or 0)]
    r["harm"] = h
    r["gain"] = r["wd"]
ok = [r for r in res if not r["harm"] and r["gain"] >= 0.02]
best = max(ok, key=lambda r: (r["rank"], -r["step"])) if ok else None
sel = {"alpha": ALPHA, "tol_score": TOL, "ref": reftag, "ref_scores": refa, "curve": res, "best_step": best["step"] if best else None,
       "reason_none": None if best else "no snapshot is harm-free and >= 0.02 better than %s on hard/tool sets: %s stays" % (reftag, reftag)}
json.dump(sel, open(outp, "w", newline="\n"), indent=1)
for r in res:
    print("step %4d  val %.4f (%s %.4f)  syn %.4f unk %.4f  hard %.4f t2 %.4f t1 %.4f (call %s direct %s)  gain %+.3f  harm %s" % (
        r["step"], r["val"]["score"], reftag, refa["val"]["score"], r["syn"]["score"], r["unk"]["score"], r["hard"]["score"], r["t2"]["score"],
        r["t1"]["score"], r["t1"]["call_ok"], r["t1"]["direct_ok"], r["gain"], r["harm"] or "none"))
open(os.path.join(os.path.dirname(outp), "DECISION.md"), "w", newline="\n").write(
    "# DECISION (laptop Q4_0 selection)\nDYNAMIC RULE: winner = weighted delta (val .25 syn .10 unk .10 hard .20 t2 .15 t1 .20) >= +0.02 vs s0300, no slice drop > 0.10, status accuracy drop <= 0.03, JSON validity >= 0.98, spurious calls <= 8%%.\nbest step: %s\n" % (best["step"] if best else None))
if not best:
    print("NO WINNER:", sel["reason_none"])
    sys.exit(3)
g = best["gguf"]
if not g or not os.path.exists(g):
    sys.exit("winner step %d has no gguf (%s)" % (best["step"], g))
md5 = (open(g + ".md5").read().split() or ["?"])[0] if os.path.exists(g + ".md5") else "?"
with open(finalk, "w", newline="\n") as f:
    f.write("gguf=%s\nmd5=%s\nadapter=%s/snap_%04d\nstep=%d\nval_score=%s\n%s_val_score=%s\n" % (
        g, md5, aroot, best["step"], best["step"], best["val"]["score"], reftag, refa["val"]["score"]))
for r in res:
    if r["step"] != best["step"] and r["gguf"] and os.path.exists(r["gguf"]):
        os.remove(r["gguf"])
print("WINNER step %d -> %s" % (best["step"], finalk))
