"""ke_score.py OUTDIR ROUNDDIR [REFDIR]   -> OUTDIR/scores.json, SUMMARY.md, DECISION.md (+ errors.json); exit 0 GOOD, 3 NOT GOOD, 4 no data.
ROUNDDIR/<tag>/{val,hard,t1,t2}.jsonl = Kaggle samples; REFDIR (default ROUNDDIR) must hold s0300. Same scorer as select_v2.py (rows.gen_score on
status/pattern/cause/dq; t1 = mean(call_ok, direct_ok)). GOOD = best candidate with hard gain >= .02 AND tool gain >= .02 (tool = mean(t1, t2) score)
AND val >= s0300 - .012. Candidates ranked by val + .35 hard + .35 tool."""
import collections
import glob
import json
import os
import sys

sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/kaggle")
import rows as RW  # noqa: E402

out, rdir = sys.argv[1], sys.argv[2]
ref = sys.argv[3] if len(sys.argv) > 3 else rdir
REF = "s0300"
F = ("status", "pattern", "cause", "dq")


def rd(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else None


def acc(s, k):
    v = [x[k] for x in s if x.get(k) is not None]
    return round(sum(bool(t) for t in v) / len(v), 4) if v else None


def agg(k, s):
    if k == "t1":
        d = {"call_ok": acc(s, "call_ok"), "direct_ok": acc(s, "direct_ok"), "json": acc(s, "json"), "n": len(s)}
        p = [d[x] for x in ("call_ok", "direct_ok") if d[x] is not None]
        d["score"] = round(sum(p) / len(p), 4) if p else 0.0
        return d
    d = {x: acc(s, x) for x in ("json",) + F}
    d.update(score=round(RW.gen_score(s), 4), n=len(s))
    return d


def load(base, tag):
    r = {k: rd("%s/%s/%s.jsonl" % (base, tag, k)) for k in ("val", "hard", "t1", "t2")}
    return r if all(r.values()) else None


res = {}
for d in sorted(glob.glob(rdir + "/*/")) + sorted(glob.glob(ref + "/%s/" % REF)):
    tag = os.path.basename(d.rstrip("/"))
    s = load(os.path.dirname(d.rstrip("/")), tag)
    if s:
        res[tag] = {k: agg(k, v) for k, v in s.items()}
        res[tag]["tool"] = round((res[tag]["t1"]["score"] + res[tag]["t2"]["score"]) / 2, 4)
        res[tag]["_rows"] = s
if REF not in res or len(res) < 2:
    open(out + "/DECISION.md", "w").write("# DECISION\nNO DATA: %s\n" % sorted(res))
    sys.exit(4)
r0 = res[REF]
cand = []
for tag, r in sorted(res.items()):
    if tag == REF:
        continue
    r["d_hard"], r["d_tool"], r["d_val"] = (round(r["hard"]["score"] - r0["hard"]["score"], 4), round(r["tool"] - r0["tool"], 4),
                                            round(r["val"]["score"] - r0["val"]["score"], 4))
    # DYNAMIC RULE (owner 2026-11-18): weighted slice delta (val .35, hard .30, tool .35) >= +0.02; no slice drops > 0.10;
    # safety: status accuracy (critical/severity) on val/hard drops <= 0.03; JSON validity >= 0.98 (or the reference's if lower)
    r["wd"] = round(0.35 * r["d_val"] + 0.30 * r["d_hard"] + 0.35 * r["d_tool"], 4)
    sd = [(r[k]["status"] or 0) - (r0[k]["status"] or 0) for k in ("val", "hard")]
    js = all((r[k]["json"] or 0) >= min(0.98, r0[k]["json"] or 0) for k in ("val", "hard", "t1", "t2"))
    r["good"] = r["wd"] >= 0.02 and min(r["d_val"], r["d_hard"], r["d_tool"]) >= -0.10 and min(sd) >= -0.03 and js
    r["rank"] = round(r["val"]["score"] + 0.35 * r["hard"]["score"] + 0.35 * r["tool"], 4)
    cand.append((tag, r))
good = [(t, r) for t, r in cand if r["good"]]
best = max(good, key=lambda x: x[1]["rank"])[0] if good else None
# error analysis of the LATEST snapshot (highest tag), by family
latest = max(t for t, _ in cand)
err = {}
for k, rows in res[latest]["_rows"].items():
    fam = collections.defaultdict(lambda: [0, 0])
    for x in rows:
        if k == "t1":
            bad = (x.get("call_ok") is False) or (x.get("direct_ok") is False)
            kind = "call" if x.get("turn") == "call" else "direct"
            key = "%s|%s" % (x["family"], kind)
        else:
            bad = any(x.get(f) is False for f in ("status", "pattern")) or not x.get("json")
            key = x["family"]
        fam[key][0] += 1
        fam[key][1] += bool(bad)
    err[k] = {f: {"n": n, "fail": b, "rate": round(b / n, 3)} for f, (n, b) in sorted(fam.items())}
json.dump({"latest": latest, "errors": err}, open(out + "/errors.json", "w"), indent=1)
sc = {t: {k: v for k, v in r.items() if k != "_rows"} for t, r in res.items()}
json.dump({"ref": REF, "best": best, "scores": sc}, open(out + "/scores.json", "w"), indent=1)
L = ["# Kaggle eval SUMMARY (HF fp16, greedy, not Q4_0)", "", "| model | val | hard | t1 call | t1 direct | t1 | t2 | tool | d_hard | d_tool | d_val | GOOD |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for t in [REF] + [t for t, _ in cand]:
    r = res[t]
    L.append("| %s | %.3f | %.3f | %s | %s | %.3f | %.3f | %.3f | %s | %s | %s | %s |" % (
        t, r["val"]["score"], r["hard"]["score"], r["t1"]["call_ok"], r["t1"]["direct_ok"], r["t1"]["score"], r["t2"]["score"], r["tool"],
        r.get("d_hard", ""), r.get("d_tool", ""), r.get("d_val", ""), r.get("good", "ref")))
L += ["", "Set sizes: " + ", ".join("%s=%d" % (k, r0[k]["n"]) for k in ("val", "hard", "t1", "t2")),
      "Field accuracy of %s: val %s; hard %s" % (latest, {k: res[latest]["val"][k] for k in F}, {k: res[latest]["hard"][k] for k in F})]
open(out + "/SUMMARY.md", "w").write("\n".join(L) + "\n")
open(out + "/DECISION.md", "w").write("# DECISION\n%s\n\nbest: %s\n"
                                      % ("GOOD" if best else "NOT GOOD", best))
open(out + "/DECISION.md", "a").write("DYNAMIC RULE: GOOD = weighted delta (val .35, hard .30, tool .35) >= +0.02, no slice drop > 0.10, status accuracy drop <= 0.03, JSON validity >= 0.98 (or reference). wd: %s\n" % {t: r["wd"] for t, r in cand})
print("GOOD" if best else "NOT GOOD", best)
sys.exit(0 if best else 3)
