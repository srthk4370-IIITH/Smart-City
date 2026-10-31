"""rsn_v3 gate: report metrics (round-1 score_v3.py, strict JSON parse) on RWH 150, RWH-2 (new held-out set) and dev 120 vs the
rsn_v1 results, same item ids for both; chat dev v3 (chat3_eval.py outputs). PASS only if
- RWH and RWH-2: severity, label, check_recall, check_prec, req >= rsn_v1 and schema_err <= rsn_v1 (strict);
- dev: no metric more than 1 item worse than rsn_v1 (noise allowance; items = rows that carry that metric);
- chat dev v3 pass rate higher than rsn_v1's.
Writes gate.json + GATE.md into --out; exit 0 = PASS, 1 = FAIL, 2 = missing results.
  python3 gate_score.py --new rsn_v3_t1 --base ft612 --chat-new A.jsonl --chat-base B.jsonl --out DIR [--p0 p0.txt]"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.abspath(os.path.join(HERE, "..", "..", "..", "2026-10-25_reasoner_final"))
sys.path.insert(0, os.path.join(R1, "eval"))
import score_v3 as S  # noqa: E402

UP = ["severity", "label", "check_recall", "check_prec", "req"]
DOWN = ["schema_err"]
SUITES = {"rwh": "incidents_rwh.ok.jsonl", "rwh2": None, "dev": "incidents_dev.ok.jsonl"}   # rwh2 path: --rwh2
NOISE_ITEMS = {"rwh": 0, "rwh2": 0, "dev": 1}


def report(tag, suite, ids, repair):
    S.REPAIR = repair
    src = SUITES[suite] if os.path.isabs(SUITES[suite]) else os.path.join(S.D, SUITES[suite])
    rows = {r["id"]: r for r in S.load(src)}
    recs = {r["id"]: r for r in S.load(os.path.join(S.HERE, "results", tag, suite + ".jsonl"))}
    sc = [S.score_incident(rows[i], recs[i]) for i in sorted(ids)]
    out = S.agg(sc)
    out["_counts"] = {k: sum(1 for r in sc if r.get(k) is not None) for k in UP + DOWN}
    return out


def ids_of(tag, suite):
    p = os.path.join(S.HERE, "results", tag, suite + ".jsonl")
    return {json.loads(l)["id"] for l in open(p)} if os.path.exists(p) else set()


def chat(path):
    rs = [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
    if not rs:
        return None
    n = len(rs)
    has = lambda r, p: any(x.startswith(p) for x in r["reasons"])
    hard = [r for r in rs if r["hard"]]
    easy = [r for r in rs if not r["hard"]]
    per = collections.defaultdict(lambda: [0, 0])
    for r in rs:
        per[r["kind"]][0] += 1
        per[r["kind"]][1] += r["pass"]
    tt = lambda r: max(r["think_tokens"] or [0])
    return {"n": n, "pass_rate": round(sum(r["pass"] for r in rs) / n, 3),
            "calls_ok": round(sum(not (has(r, "missing_call") or has(r, "unexpected_call") or has(r, "extra_calls")) for r in rs) / n, 3),
            "facts_ok": round(sum(not has(r, "missing_fact") for r in rs) / n, 3),
            "grounded": round(sum(not has(r, "invented_") for r in rs) / n, 3),
            "refusal_ok": round(sum(not has(r, "no_refusal") for r in rs if r["must_refuse"]) / max(1, sum(r["must_refuse"] for r in rs)), 3),
            "hard_think_mean": round(sum(tt(r) for r in hard) / max(1, len(hard)), 1),
            "easy_think_nonempty": round(sum(tt(r) > 0 for r in easy) / max(1, len(easy)), 3),
            "wall_s_mean": round(sum(r["wall_s"] for r in rs) / n, 2), "gen_tokens_mean": round(sum(r["gen_tokens"] for r in rs) / n, 1),
            "fail_reasons": dict(collections.Counter(x.split(":")[0] for r in rs for x in r["reasons"]).most_common(12)),
            "per_kind_pass": {k: "%d/%d" % (v[1], v[0]) for k, v in sorted(per.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--base", default="ft612")
    ap.add_argument("--chat-new", required=True)
    ap.add_argument("--chat-base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--p0", default="")
    ap.add_argument("--rwh2", default="", help="incidents_rwh2.jsonl (held out); without it the rwh2 rule is reported missing")
    a = ap.parse_args()
    g = {"new": a.new, "base": a.base, "checks": [], "suites": {}}
    missing = []
    if a.rwh2:
        SUITES["rwh2"] = os.path.abspath(a.rwh2)
    else:
        SUITES.pop("rwh2")
        missing.append("rwh2 file not given")
    for suite in SUITES:
        ids = ids_of(a.new, suite) & ids_of(a.base, suite)
        if len(ids) < 0.95 * max(1, len(ids_of(a.base, suite))):
            missing.append("%s: %d common items" % (suite, len(ids)))
            continue
        st = {"n": len(ids), "new": report(a.new, suite, ids, False), "base": report(a.base, suite, ids, False),
              "new_repair": report(a.new, suite, ids, True), "base_repair": report(a.base, suite, ids, True)}
        g["suites"][suite] = st
        for m in UP + DOWN:
            nv, bv = st["new"].get(m), st["base"].get(m)
            n_m = max(1, st["new"]["_counts"][m])
            slack = NOISE_ITEMS[suite] / n_m + 1e-9
            ok = nv is not None and bv is not None and (nv >= bv - slack if m in UP else nv <= bv + slack)
            rule = (">=" if m in UP else "<=") + (" (1 item = %.3f)" % (1.0 / n_m) if NOISE_ITEMS[suite] else "")
            g["checks"].append({"suite": suite, "metric": m, "new": nv, "base": bv, "ok": bool(ok), "rule": rule})
    cn, cb = chat(a.chat_new), chat(a.chat_base)
    if cn is None or cb is None:
        missing.append("chat dev v3 results")
    else:
        g["chat"] = {"new": cn, "base": cb}
        g["checks"].append({"suite": "chatdev3", "metric": "pass_rate", "new": cn["pass_rate"], "base": cb["pass_rate"],
                            "ok": cn["pass_rate"] > cb["pass_rate"], "rule": ">"})
    g["missing"] = missing
    g["pass"] = not missing and all(c["ok"] for c in g["checks"])
    os.makedirs(a.out, exist_ok=True)
    json.dump(g, open(os.path.join(a.out, "gate.json"), "w"), indent=1)
    L = ["# rsn_v3 gate: %s vs %s -> **%s**" % (a.new, a.base, "PASS" if g["pass"] else ("INCOMPLETE" if missing else "FAIL")), "",
         "Rule: RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); dev within 1 item; strict JSON parse, same items; chat dev v3 pass rate > rsn_v1.", ""]
    if missing:
        L += ["Missing: " + "; ".join(missing), ""]
    L += ["| suite | metric | rsn_v3 | rsn_v1 | rule | ok |", "|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %s | %s | %s |" % (c["suite"], c["metric"], c["new"], c["base"], c["rule"], "yes" if c["ok"] else "**NO**") for c in g["checks"]]
    for suite, st in g["suites"].items():
        L += ["", "%s (n=%d) with the one-bracket JSON repair (info): v3 %s / v1 %s" % (suite, st["n"], {k: st["new_repair"].get(k) for k in UP + DOWN},
                                                                                   {k: st["base_repair"].get(k) for k in UP + DOWN})]
    if "chat" in g:
        L += ["", "## chat dev v3", "", "| metric | rsn_v3 | rsn_v1 |", "|---|---|---|"]
        for k in ("n", "pass_rate", "calls_ok", "facts_ok", "grounded", "refusal_ok", "hard_think_mean", "easy_think_nonempty", "wall_s_mean", "gen_tokens_mean"):
            L.append("| %s | %s | %s |" % (k, g["chat"]["new"][k], g["chat"]["base"][k]))
        L += ["", "rsn_v3 fail reasons: %s" % g["chat"]["new"]["fail_reasons"], "", "rsn_v1 fail reasons: %s" % g["chat"]["base"]["fail_reasons"]]
    if a.p0 and os.path.exists(a.p0):
        L += ["", "## P0 regression (informational)", "", "```", open(a.p0).read().strip(), "```"]
    open(os.path.join(a.out, "GATE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L[:3]))
    sys.exit(0 if g["pass"] else (2 if missing else 1))


if __name__ == "__main__":
    main()
