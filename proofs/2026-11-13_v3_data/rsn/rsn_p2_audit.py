"""rsn_p2_audit.py DATA_DIR OUT.md : CPU audit of 60 random new p2 rows + 40 replay rows. exit 1 if >5% bad.
checks: cited ids exist in prompt; severity valid and consistent with family gold (flat/step/plateau alone never sensor_fault);
root_cause/causal_chain non-trivial and, for cross-domain rows, mention >=2 domains or ids; no 'zero/no noise' claim when that sensor's E8 noise > 0."""
import json, random, re, sys
D, out = sys.argv[1], sys.argv[2]; R = random.Random(18)
def rows(f): return [json.loads(l) for l in open(D + "/" + f, encoding="utf-8") if l.strip()]
new = [r for r in rows("train_new.jsonl") if str(r.get("family", "")).startswith("p2_")]; rep = rows("replay.jsonl")
S = R.sample(new, min(60, len(new))) + R.sample(rep, min(40, len(rep)))
ID = re.compile(r"S\d+\.E\d+"); SEV = {"normal", "info", "warning", "critical", "sensor_fault"}
def audit(r):
    m = r["messages"]; u = m[1]["content"]; c = m[-1]["content"]; bad = []
    c = c.split("</think>")[-1]; a, b = c.find("{"), c.rfind("}")  # report JSON after any think block
    try:
        p = json.loads(c[a:b + 1])
    except Exception:
        return None  # chat / tool turn: not an incident report, not audited
    if not isinstance(p, dict) or "severity" not in p:
        return None
    txt = json.dumps(p, ensure_ascii=False)
    for i in set(ID.findall(txt)):
        if (i + " ") not in u and (i + ",") not in u: bad.append("id %s not in prompt" % i)
    sev = p.get("severity")
    if sev not in SEV: bad.append("bad severity %s" % sev)
    fam = r.get("p2_family") or ""
    if any(k in fam for k in ("flat_alone", "step_real", "plateau_real", "flat_mem")) and sev == "sensor_fault" and "mem" not in fam: bad.append("sensor_fault on single-kind evidence")
    if fam == "p2_fault_2nd" and sev != "sensor_fault": bad.append("fault_2nd without sensor_fault")
    rc, cc = str(p.get("root_cause", "")), str(p.get("causal_chain", ""))
    if len(rc) < 25 or len(cc) < 10: bad.append("empty root cause/chain")
    if not ID.search(cc) and sev not in ("normal", "info"): bad.append("chain cites no evidence id")
    doms = p.get("domains") or []
    if len(doms) > 1 and sum(d.replace("_", " ") in (rc + cc).lower() or d in (rc + cc).lower() for d in doms) < 2 and not re.search(r"\bS\d", rc): bad.append("cross-domain link missing")
    for sid, n in re.findall(r"(S\d+)\.E8[^\n]*?noise ([0-9.]+)", u):
        if float(n) > 0 and re.search(r"(zero|no|without)\s+noise|noise\s+(of\s+)?(0|zero)\b", txt, re.I) and sid in txt: bad.append("noise claim vs %s E8 %s" % (sid, n))
    return bad
res = [(r.get("id"), r.get("family", "replay"), audit(r)) for r in S]
skipped = sum(1 for x in res if x[2] is None); res = [x for x in res if x[2] is not None]; print("skipped non-report rows:", skipped)
nb =sum(1 for _, _, b in res if b); rate = nb / max(len(res), 1)
L = ["# rsn p2 row audit", "", "%d rows (%d new p2, %d replay): bad %d = %.1f%% (limit 5%%)" % (len(res), min(60, len(new)), min(40, len(rep)), nb, 100 * rate), ""]
L += ["- %s [%s]: %s" % (i, f, "; ".join(b)) for i, f, b in res if b]
L.append("\nRESULT: " + ("PASS" if rate <= 0.05 else "FAIL"))
open(out, "w", newline="\n").write("\n".join(L) + "\n"); print(L[2]); sys.exit(0 if rate <= 0.05 else 1)
