"""Gate of the 4B r3 candidate (rsn_v3_4b_r3) vs rsn_v1 (ft612). Same rule as kaggle/local/gate_score.py (g2b_r2 GATE.md):
- RWH, RWH-2: severity, label, check_recall, check_prec, req >= rsn_v1 and schema_err <= rsn_v1 (strict JSON, same ids);
- round-1 dev (incident prompt): no metric more than 1 item worse;
- chat dev v3 pass rate > rsn_v1. New model: the r3 app prompt (chat_r3_eval.py --mode dev3, adaptive think). rsn_v1: its
  cached chat dev v3 result (chat3_eval.py, empty think = its trained mode), the same baseline file the 2B gates used.
Informational (never gating): chat_test_r3 (983, r3 verifier, per fog / group / Hinglish / kind; rsn_v1 run with the r3
prompt it never saw = out of distribution), incidents_test_r2 per slice (1,368; gold = the row's report), P0.
Writes gate.json + GATE.md into --out; exit 0 PASS, 1 FAIL, 2 gate inputs missing.
  python3 gate_score_4b.py --new rsn_v3_4b_r3 --base ft612 --chat-new A --chat-base B --out DIR --rwh2 F
         [--r3-new X --r3-base Y] [--test-r2 incidents_test_r2.jsonl] [--p0 p0.txt]"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "kaggle", "local"))
import gate_score as GS  # noqa: E402  (imports round-1 score_v3 as GS.S)

S = GS.S
UP, DOWN = GS.UP, GS.DOWN


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p and os.path.exists(p) else []


def chat_slices(path):
    rs = load(path)
    if not rs:
        return None
    out = {"all": GS.chat(path)}
    for key in ("fog", "group", "hinglish", "hard"):
        g = collections.defaultdict(list)
        for r in rs:
            g[str(r.get(key))].append(r["pass"])
        out["by_" + key] = {k: "%d/%d = %.3f" % (sum(v), len(v), sum(v) / len(v)) for k, v in sorted(g.items())}
    return out


def test_r2_rows(path):
    """incidents_test_r2 rows -> score_v3 rows with a 'gold' block built from the row's own report"""
    rows = {}
    for r in load(path):
        try:
            rep = json.loads(r["messages"][-1]["content"])
        except Exception:
            continue
        r["gold"] = {"labels": {rep.get("label"): 1.0}, "severities": {rep.get("severity"): 1.0}, "root_metric": "",
                     "required": [[c["action"]] for c in (rep.get("checklist") or [])[:1] if isinstance(c, dict) and c.get("action")],
                     "forbidden": [], "checks": [[c["ref"], [c["verdict"]]] for c in rep.get("agent_checks") or []
                                                 if isinstance(c, dict) and c.get("ref") and c.get("verdict")]}
        rows[r["id"]] = r
    return rows


def test_r2(rows, tag):
    recs = {r["id"]: r for r in load(os.path.join(S.HERE, "results", tag, "test_r2.jsonl"))}
    by = collections.defaultdict(list)
    for i, rec in recs.items():
        if i in rows:
            S.REPAIR = False
            o = S.score_incident(rows[i], rec)
            by[rows[i].get("slice") or "?"].append(o)
            by["all"].append(o)
    return {k: S.agg(v) for k, v in sorted(by.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--base", default="ft612")
    ap.add_argument("--chat-new", required=True)
    ap.add_argument("--chat-base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rwh2", required=True)
    ap.add_argument("--r3-new", default="")
    ap.add_argument("--r3-base", default="")
    ap.add_argument("--test-r2", default="")
    ap.add_argument("--p0", default="")
    a = ap.parse_args()
    GS.SUITES["rwh2"] = os.path.abspath(a.rwh2)
    g = {"new": a.new, "base": a.base, "checks": [], "suites": {}, "info": {}}
    missing = []
    for suite in ("rwh", "rwh2", "dev"):
        ids = GS.ids_of(a.new, suite) & GS.ids_of(a.base, suite)
        if len(ids) < 0.95 * max(1, len(GS.ids_of(a.base, suite))):
            missing.append("%s: %d common items" % (suite, len(ids)))
            continue
        st = {"n": len(ids), "new": GS.report(a.new, suite, ids, False), "base": GS.report(a.base, suite, ids, False),
              "new_repair": GS.report(a.new, suite, ids, True), "base_repair": GS.report(a.base, suite, ids, True)}
        g["suites"][suite] = st
        for m in UP + DOWN:
            nv, bv = st["new"].get(m), st["base"].get(m)
            n_m = max(1, st["new"]["_counts"][m])
            slack = GS.NOISE_ITEMS[suite] / n_m + 1e-9
            ok = nv is not None and bv is not None and (nv >= bv - slack if m in UP else nv <= bv + slack)
            rule = (">=" if m in UP else "<=") + (" (1 item = %.3f)" % (1.0 / n_m) if GS.NOISE_ITEMS[suite] else "")
            g["checks"].append({"suite": suite, "metric": m, "new": nv, "base": bv, "ok": bool(ok), "rule": rule})
    cn, cb = GS.chat(a.chat_new), GS.chat(a.chat_base)
    if cn is None or cb is None or cn["n"] < cb["n"]:
        missing.append("chat dev v3 results (new %s, base %s)" % (cn and cn["n"], cb and cb["n"]))
    else:
        g["chat"] = {"new": cn, "base": cb}
        g["checks"].append({"suite": "chatdev3", "metric": "pass_rate", "new": cn["pass_rate"], "base": cb["pass_rate"],
                            "ok": cn["pass_rate"] > cb["pass_rate"], "rule": ">"})
    # ---- informational
    r3n, r3b = chat_slices(a.r3_new), chat_slices(a.r3_base)
    if r3n:
        g["info"]["chat_test_r3"] = {"new": r3n, "base": r3b}
    if a.test_r2 and os.path.exists(a.test_r2):
        rows = test_r2_rows(a.test_r2)
        tn, tb = test_r2(rows, a.new), test_r2(rows, a.base)
        if tn:
            g["info"]["test_r2"] = {"n_rows": len(rows), "new": tn, "base": tb}
    g["missing"] = missing
    g["pass"] = not missing and all(c["ok"] for c in g["checks"])
    verdict = "PASS" if g["pass"] else ("INCOMPLETE" if missing else "FAIL")
    g["verdict"] = verdict
    os.makedirs(a.out, exist_ok=True)
    json.dump(g, open(os.path.join(a.out, "gate.json"), "w"), indent=1)
    L = ["# 4B r3 gate: %s vs %s (rsn_v1) -> **%s**" % (a.new, a.base, verdict), "",
         "Rule (as g2b_r2): RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); round-1 dev within 1 item; strict JSON "
         "parse, same items; chat dev v3 pass rate > rsn_v1. Chat dev v3: the 4B with the r3 app prompt (21-tool header, adaptive "
         "think); rsn_v1 = its cached result with its own trained mode (empty think). Q4_0 on the host GPU (host = board numerics).", ""]
    if missing:
        L += ["Missing: " + "; ".join(missing), ""]
    L += ["| suite | metric | 4B r3 | rsn_v1 | rule | ok |", "|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %s | %s | %s |" % (c["suite"], c["metric"], c["new"], c["base"], c["rule"], "yes" if c["ok"] else "**NO**")
          for c in g["checks"]]
    for suite, st in g["suites"].items():
        L += ["", "%s (n=%d) with the one-bracket JSON repair (info): 4B %s / v1 %s" % (
            suite, st["n"], {k: st["new_repair"].get(k) for k in UP + DOWN}, {k: st["base_repair"].get(k) for k in UP + DOWN})]
    if "chat" in g:
        L += ["", "## chat dev v3 (300)", "", "| metric | 4B r3 (r3 prompt) | rsn_v1 |", "|---|---|---|"]
        for k in ("n", "pass_rate", "calls_ok", "facts_ok", "grounded", "refusal_ok", "hard_think_mean", "easy_think_nonempty",
                  "wall_s_mean", "gen_tokens_mean"):
            L.append("| %s | %s | %s |" % (k, g["chat"]["new"][k], g["chat"]["base"][k]))
        L += ["", "4B fail reasons: %s" % g["chat"]["new"]["fail_reasons"], "", "rsn_v1 fail reasons: %s" % g["chat"]["base"]["fail_reasons"]]
    L += ["", "## Informational (not gating)"]
    t3 = g["info"].get("chat_test_r3")
    if t3:
        b = t3["base"] or {}
        L += ["", "### chat_test_r3 (held-out r3 test, r3 verifier; rsn_v1 never saw the r3 header/fog tools: out of distribution)", "",
              "| slice | 4B r3 | rsn_v1 (OOD) |", "|---|---|---|"]
        L.append("| pass_rate | %s | %s |" % (t3["new"]["all"]["pass_rate"], (b.get("all") or {}).get("pass_rate", "-")))
        L.append("| n | %s | %s |" % (t3["new"]["all"]["n"], (b.get("all") or {}).get("n", "-")))
        for key in ("by_fog", "by_group", "by_hinglish", "by_hard"):
            for k, v in t3["new"][key].items():
                L.append("| %s=%s | %s | %s |" % (key[3:], k, v, (b.get(key) or {}).get(k, "-")))
        L += ["", "4B per kind: %s" % t3["new"]["all"]["per_kind_pass"], "", "4B fail reasons: %s" % t3["new"]["all"]["fail_reasons"]]
    else:
        L += ["", "chat_test_r3: not run yet."]
    t2 = g["info"].get("test_r2")
    if t2:
        L += ["", "### incidents_test_r2 per slice (gold = the row's report; strict JSON)", "",
              "| slice | model | n | parsed | severity | label | check_recall | check_prec | req | schema_err |", "|---|---|---|---|---|---|---|---|---|---|"]
        for sl in t2["new"]:
            for nm, d in (("4B r3", t2["new"].get(sl)), ("rsn_v1", t2["base"].get(sl))):
                if d:
                    L.append("| %s | %s | %s | %s |" % (sl, nm, d["n"], " | ".join(str(d.get(k)) for k in ("parsed", "severity", "label", "check_recall",
                                                                                                         "check_prec", "req", "schema_err"))))
    else:
        L += ["", "incidents_test_r2: not run yet."]
    if a.p0 and os.path.exists(a.p0):
        L += ["", "### P0 regression", "", "```", open(a.p0).read().strip(), "```"]
    open(os.path.join(a.out, "GATE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L[:1]))
    sys.exit(0 if g["pass"] else (2 if missing else 1))


if __name__ == "__main__":
    main()
