"""select_k.py score SAMPLES.jsonl                          -> one-line JSON of the dev score (rows.gen_score + per-field accuracy)
select_k.py pick POST REF_DIR OUT.json FINAL_K ADAPTER_ROOT [ALPHA=0.05]
Selection + no-harm of the agt_v3 Kaggle top-up. POST/sNNNN/{val,syn,unk}.jsonl = host-eval samples of the merged Q4_0 of every pulled
snapshot (val = REAL VAL 400, syn = synthetic slice 120, unk = unseen_metric 100); REF_DIR/{val,syn,unk}_s1750.jsonl = snap_1750.
Per snapshot and per synthetic/unseen set and field (status, pattern, cause, dq): exact two-sided sign test on the discordant rows
(paired by row id). HARM = candidate worse than snap_1750 with p < ALPHA. The best snapshot = highest REAL VAL score among the
snapshots without harm AND above snap_1750 on REAL VAL (otherwise no snapshot wins and snap_1750 stays). The winner is written to
FINAL_K (gguf, md5, adapter, step). Exit 0 winner, 3 none."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("AGT_DIR", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt"), "kaggle"))
import rows as RW  # noqa: E402

FIELDS = ("status", "pattern", "cause", "dq")


def rd(p):
    if not os.path.exists(p):
        return None
    return {x["id"]: x for x in (json.loads(l) for l in open(p) if l.strip())}


def agg(s):
    s = list(s)
    d = {k: round(sum(bool(x[k]) for x in s if x.get(k) is not None) / max(1, sum(x.get(k) is not None for x in s)), 4)
         for k in ("json",) + FIELDS}
    d.update(score=round(RW.gen_score(s), 5), n=len(s))
    return d


def paired(c, r):
    out, harm = {}, []
    ids = sorted(set(c) & set(r))
    if len(ids) < 0.9 * len(c):
        sys.exit("only %d of %d rows pair with the snap_1750 reference: wrong reference set" % (len(ids), len(c)))
    for k in FIELDS:
        v = [i for i in ids if c[i].get(k) is not None and r[i].get(k) is not None]
        if not v:
            continue
        w = sum(bool(c[i][k]) and not bool(r[i][k]) for i in v)
        l_ = sum(bool(r[i][k]) and not bool(c[i][k]) for i in v)
        p = RW.binom_two_sided(w, l_)
        out[k] = {"cand": round(100 * sum(bool(c[i][k]) for i in v) / len(v), 1), "ref": round(100 * sum(bool(r[i][k]) for i in v) / len(v), 1),
                  "wins": w, "losses": l_, "p": round(p, 4), "n": len(v)}
        if l_ > w and p < ALPHA:
            out[k]["harm"] = True
            harm.append(k)
    return out, harm


if sys.argv[1] == "score":
    print(json.dumps(agg(json.loads(l) for l in open(sys.argv[2]) if l.strip())))
    sys.exit(0)
post, refd, outp, finalk, aroot = sys.argv[2:7]
ALPHA = float(sys.argv[7]) if len(sys.argv) > 7 else 0.05
ref = {k: rd("%s/%s_s1750.jsonl" % (refd, k)) for k in ("val", "syn", "unk")}
if not all(ref.values()):
    sys.exit("missing snap_1750 reference samples in " + refd)
ref_val = agg(ref["val"].values())
res = []
for d in sorted(glob.glob(post + "/s[0-9][0-9][0-9][0-9]")):
    step = int(os.path.basename(d)[1:])
    smp = {k: rd("%s/%s.jsonl" % (d, k)) for k in ("val", "syn", "unk")}
    if not all(smp.values()):
        continue
    row = {"step": step, "val": agg(smp["val"].values()), "syn": agg(smp["syn"].values()), "unk": agg(smp["unk"].values()), "harm": []}
    row["val_vs_s1750"] = paired(smp["val"], ref["val"])[0]
    for k in ("syn", "unk"):
        row["%s_vs_s1750" % k], h = paired(smp[k], ref[k])
        row["harm"] += ["%s.%s" % (k, f) for f in h]
    g = glob.glob("%s/agt3_s%04d_q4_0.gguf" % (d, step))
    row["gguf"] = g[0] if g else None
    res.append(row)
ok = [r for r in res if not r["harm"] and r["val"]["score"] > ref_val["score"]]
best = max(ok, key=lambda r: (r["val"]["score"], -r["step"])) if ok else None
sel = {"alpha": ALPHA, "snap_1750_val": ref_val, "snap_1750_syn": agg(ref["syn"].values()), "snap_1750_unk": agg(ref["unk"].values()),
       "curve": res, "best_step": best["step"] if best else None, "reason_none": None if best else
       "no snapshot is both harm-free (syn/unseen) and above snap_1750 on REAL VAL: snap_1750 stays"}
json.dump(sel, open(outp, "w", newline="\n"), indent=1)
for r in res:
    print("step %4d  val %.4f (s1750 %.4f)  syn %.4f  unk %.4f  harm %s" % (r["step"], r["val"]["score"], ref_val["score"],
          r["syn"]["score"], r["unk"]["score"], r["harm"] or "none"))
if not best:
    print("NO WINNER:", sel["reason_none"])
    sys.exit(3)
g = best["gguf"]
if not g or not os.path.exists(g):
    sys.exit("winner step %d has no gguf (%s)" % (best["step"], g))
md5 = (open(g + ".md5").read().split() or ["?"])[0] if os.path.exists(g + ".md5") else "?"
with open(finalk, "w", newline="\n") as f:
    f.write("gguf=%s\nmd5=%s\nadapter=%s/snap_%04d\nstep=%d\nval_score=%s\nsnap_1750_val_score=%s\n" % (
        g, md5, aroot, best["step"], best["step"], best["val"]["score"], ref_val["score"]))
for r in res:                     # disk: only the winner's Q4_0 stays
    if r["step"] != best["step"] and r["gguf"] and os.path.exists(r["gguf"]):
        os.remove(r["gguf"])
print("WINNER step %d -> %s" % (best["step"], finalk))
