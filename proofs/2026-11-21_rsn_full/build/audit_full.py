"""audit_full.py: verify + audit every row of real_rows / gen5_multidomain / gen5_domain (check_big audit_report + G.full_check; real rows: severity == rule gold; pre-cutoff)."""
import sys, json, collections, re
sys.argv = ["x", "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/data/final_big"]
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
src = open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build/check_big.py").read().rsplit("\nmain()", 1)[0]
g = {"__file__": "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build/check_big.py", "__name__": "cb"}; exec(compile(src, "check_big", "exec"), g)
D = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full"; CUT = 1765391400
L = ["# AUDIT_REAL", "", "Cutoff epoch %d (2025-12-11 00:00 IST, see CUTOFF.md). Verifiers: G.full_check (round-1 + v4 checks), check_big.audit_report (ids exist, severity valid, contrast family severity, sensor_fault only on strong evidence, chain cites ids), real rows: severity == rule gold.\n" % CUT,
     "| file | rows | src_real | bad (verify+audit) | bad % | families | sev dist |", "|---|---|---|---|---|---|---|"]
res = {}
for fn in ("gen5_multidomain", "gen5_domain"):
    rows = [json.loads(l) for l in open("%s/data/%s.jsonl" % (D, fn))]
    bad = 0; ex = []; sev = collections.Counter(); fam = collections.Counter(); real = 0
    for r in rows:
        e = list(g["G"].full_check(r)) + g["audit_report"](r)
        p = g["rep_of"](r); s = p.get("severity") if p else None; sev[s] += 1; fam[r["family"].split(":")[1] if ":" in r["family"] else r["family"]] += 1
        real += bool(r.get("src_real"))
        if fn == "real_rows":
            if s != r["gold_status"]: e.append("severity %s != rule gold %s" % (s, r["gold_status"]))
            if r["real_end_epoch"] >= CUT: e.append("after cutoff")
            if s == "sensor_fault" and r["gold_status"] != "sensor_fault": e.append("unsupported sensor_fault")
        if e:
            bad += 1
            if len(ex) < 5: ex.append((r["id"], e[:2]))
    res[fn] = (len(rows), real, bad)
    L.append("| %s | %d | %d | %d | %.2f%% | %d | %s |" % (fn, len(rows), real, bad, 100 * bad / max(len(rows), 1), len(fam), dict(sev)))
    for x in ex: L.append("|  ex | %s | %s |||||" % x)
tot = sum(v[0] for v in res.values()); tb = sum(v[2] for v in res.values())
L += ["", "total %d rows, real %d, injected %d, bad %d (%.2f%%; limit 2%%)." % (tot, sum(v[1] for v in res.values()), tot - sum(v[1] for v in res.values()), tb, 100 * tb / max(tot, 1)),
      "Gold: real rows = rule gold (sft_v2 labels, label-audit judge on the exact E-lines) + deployed agent s0450 output (greedy, GPU) -> verified v2 report builder (gen_agt3); injected rows = gold by construction.",
      "Not done: board incidents (old_inc.jsonl) - sim clock +1 y, old report schema, no verified gold; reasoner-model self-distill not used (deterministic verified builder); injected scenes use generated series (not real windows)."]
open(D + "/AUDIT_REAL.md", "w").write("\n".join(L) + "\n"); print("\n".join(L[-6:]))
