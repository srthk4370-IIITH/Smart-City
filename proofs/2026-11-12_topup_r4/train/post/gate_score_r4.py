"""STRICT gate of the r4 top-up (rsn_v3_4b_r4) vs the deployed r3 model (rsn_v3_4b_r3 = r3 step 2800). TOPUP.md "Gate".
PASS needs all three:
 (a) r4 held-out cross-domain test: the r4 model beats r3-2800 on the same items by at least one item-equivalent
     (combined = mean of the parts present: incident item score = mean of severity, label, check_recall, check_prec, req of a
     parsed report (0 when unparsed); chat = verify pass), and no part is worse beyond noise (paired z < -1.96).
 (b) the 19 existing gate checks (RWH, RWH-2, round-1 dev: severity, label, check_recall, check_prec, req >=, schema_err <=;
     chat dev v3 pass rate) >= r3-2800 within 1 item each (r3-2800 = its cached gate_r3 results, same items, strict JSON).
 (c) chat_test_r3 MINUS the ambiguous items (data/chat_test_r3_ambiguous.jsonl, owner 2026-11-12) per fog state (r3-2800
     filtered: online 0.876 / offline 0.739 / timeout 0.522; full slices 0.841 / 0.692 / 0.522 reported for info): not lower beyond noise
     (paired over the same records: worse only if the drop is >= 1 item and z < -1.96).
--stage a: only (a) (early FAIL saves the long suites). Writes gate.json + GATE_r4.md into --out; exit 0 PASS, 1 FAIL,
2 inputs missing.
  python3 gate_score_r4.py --stage final --out DIR --test4-inc F --t4-new results/.../test_r4.jsonl --t4-base ... [--c4-new X --c4-base Y]
         --rwh2 F --chatdev-new A --chatdev-base B --r3-new C --r3-base D"""
import argparse
import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "kaggle", "local"))
import gate_score as GS  # noqa: E402  (round-1 score_v3 as GS.S)


def split_think(t):
    """= topup_train.split_think (copied: this scorer runs without torch)"""
    t = t or ""
    i, j = t.find("</think>"), t.find("{")
    if i < 0 or (0 <= j < i and not t.lstrip().startswith("<think>")):
        return "", t
    th = t[:i].strip()
    return (th[len("<think>"):].strip() if th.startswith("<think>") else th), t[i + len("</think>"):]

S = GS.S
UP, DOWN = GS.UP, GS.DOWN
BASE_FOG = {"online": 0.841, "offline": 0.692, "timeout": 0.522}
# owner decision 2026-11-12: rule (c) gates on chat_test_r3 MINUS the ambiguous items (gold uses a window/min_count the question
# does not state; list + rule: ../../data/chat_test_r3_ambiguous.jsonl, tools/ambig_r3.py), for both models. Full slices = info.
# r3-2800 filtered baselines from its cached gate_r3 outputs: online 354/404, offline 340/460, timeout 36/69 (0 excluded).
BASE_FOG_FILTERED = {"online": 0.876, "offline": 0.739, "timeout": 0.522}
AMBIG = os.path.join(HERE, "..", "..", "data", "chat_test_r3_ambiguous.jsonl")


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p and os.path.exists(p) else []


def test_rows(path):
    """r4 test incident rows -> score_v3 rows with a gold block from the row's own report (think block stripped)"""
    rows = {}
    for r in load(path):
        m = r["messages"][-1]
        try:
            rep = json.loads(split_think(m.get("content") or "")[1].strip())
        except Exception:
            continue
        r["gold"] = {"labels": {rep.get("label"): 1.0}, "severities": {rep.get("severity"): 1.0}, "root_metric": "",
                     "required": [[c["action"]] for c in (rep.get("checklist") or [])[:1] if isinstance(c, dict) and c.get("action")],
                     "forbidden": [], "checks": [[c["ref"], [c["verdict"]]] for c in rep.get("agent_checks") or []
                                                 if isinstance(c, dict) and c.get("ref") and c.get("verdict")]}
        r["_multi"] = len(rep.get("affected_domains") or []) > 1
        rows[r["id"]] = r
    return rows


def item_scores(rows, recs_path):
    out = {}
    for rec in load(recs_path):
        if rec["id"] not in rows:
            continue
        S.REPAIR = False
        o = S.score_incident(rows[rec["id"]], rec)
        v = [o[k] for k in UP if o.get(k) is not None] if o.get("parsed") else []
        out[rec["id"]] = sum(v) / len(v) if v else 0.0
    return out


def chat_pass(path):
    return {r["id"]: float(bool(r["pass"])) for r in load(path)}


def paired(new, base, ids):
    """mean paired difference, its z (0 when no variance), n"""
    d = [new[i] - base[i] for i in ids]
    n = len(d)
    if not n:
        return 0.0, 0.0, 0
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / max(1, n - 1))
    return m, (m / (sd / math.sqrt(n)) if sd > 0 else (0.0 if m == 0 else math.copysign(99.0, m))), n


def worse_beyond_noise(m, z, n):
    return m < 0 and m * n <= -1 and z < -1.96


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("a", "final"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--new", default="rsn_v3_4b_r4")
    ap.add_argument("--base", default="rsn_v3_4b_r3")
    ap.add_argument("--test4-inc", default="")
    ap.add_argument("--t4-new", default="")
    ap.add_argument("--t4-base", default="")
    ap.add_argument("--c4-new", default="")
    ap.add_argument("--c4-base", default="")
    ap.add_argument("--rwh2", default="")
    ap.add_argument("--chatdev-new", default="")
    ap.add_argument("--chatdev-base", default="")
    ap.add_argument("--r3-new", default="")
    ap.add_argument("--r3-base", default="")
    ap.add_argument("--ambiguous", default=AMBIG)
    a = ap.parse_args()
    g = {"new": a.new, "base": a.base, "stage": a.stage, "a": {}, "checks": [], "fog": {}, "fog_full": {}, "missing": []}
    L4 = []
    # ---- (a)
    parts, ok_a = [], True
    if a.test4_inc:
        rows = test_rows(a.test4_inc)
        sn, sb = item_scores(rows, a.t4_new), item_scores(rows, a.t4_base)
        ids = sorted(set(sn) & set(sb))
        if len(ids) < 0.95 * len(rows) or not ids:
            g["missing"].append("r4 test incidents: %d common of %d" % (len(ids), len(rows)))
        else:
            m, z, n = paired(sn, sb, ids)
            nb, nn = sum(sb[i] for i in ids) / n, sum(sn[i] for i in ids) / n
            parts.append(("incidents", nn, nb, n, m, z))
            for name, sel in (("multi-domain", [i for i in ids if rows[i]["_multi"]]), ("single-domain", [i for i in ids if not rows[i]["_multi"]])):
                if sel:
                    mm, zz, k = paired(sn, sb, sel)
                    g["a"][name] = {"n": k, "new": round(sum(sn[i] for i in sel) / k, 4), "base": round(sum(sb[i] for i in sel) / k, 4),
                                    "diff": round(mm, 4), "z": round(zz, 2)}
            sl = collections.defaultdict(list)
            for i in ids:
                sl[rows[i].get("slice") or "?"].append(i)
            g["a"]["by_slice"] = {k: "%.3f vs %.3f (n %d)" % (sum(sn[i] for i in v) / len(v), sum(sb[i] for i in v) / len(v), len(v))
                                  for k, v in sorted(sl.items())}
    if a.c4_new or a.c4_base:
        cn, cb = chat_pass(a.c4_new), chat_pass(a.c4_base)
        ids = sorted(set(cn) & set(cb))
        if not ids or len(ids) < 0.95 * max(len(cn), len(cb)):
            g["missing"].append("r4 test chat: %d common" % len(ids))
        else:
            m, z, n = paired(cn, cb, ids)
            parts.append(("chat", sum(cn[i] for i in ids) / n, sum(cb[i] for i in ids) / n, n, m, z))
    if not parts:
        g["missing"].append("r4 test results")
    else:
        comb_n = sum(p[1] for p in parts) / len(parts)
        comb_b = sum(p[2] for p in parts) / len(parts)
        one_item = sum(1.0 / p[3] for p in parts) / len(parts)
        bad = [p[0] for p in parts if worse_beyond_noise(p[4], p[5], p[3])]
        ok_a = comb_n - comb_b >= one_item - 1e-12 and not bad
        g["a"].update({"parts": [{"part": p[0], "new": round(p[1], 4), "base": round(p[2], 4), "n": p[3], "diff": round(p[4], 4), "z": round(p[5], 2)}
                                 for p in parts], "combined_new": round(comb_n, 4), "combined_base": round(comb_b, 4),
                       "one_item": round(one_item, 4), "worse_parts": bad, "ok": ok_a})
        g["checks"].append({"suite": "r4 test", "metric": "combined", "new": round(comb_n, 4), "base": round(comb_b, 4), "ok": ok_a,
                            "rule": "> base by >= 1 item (%.4f), no part worse beyond noise" % one_item})
    # ---- (b) + (c)
    if a.stage == "final":
        if a.rwh2:
            GS.SUITES["rwh2"] = os.path.abspath(a.rwh2)
        for suite in ("rwh", "rwh2", "dev"):
            ids = GS.ids_of(a.new, suite) & GS.ids_of(a.base, suite)
            if len(ids) < 0.95 * max(1, len(GS.ids_of(a.base, suite))):
                g["missing"].append("%s: %d common items" % (suite, len(ids)))
                continue
            rn, rb = GS.report(a.new, suite, ids, False), GS.report(a.base, suite, ids, False)
            for m in UP + DOWN:
                nv, bv = rn.get(m), rb.get(m)
                n_m = max(1, rn["_counts"][m])
                slack = 1.0 / n_m + 1e-9
                ok = nv is not None and bv is not None and (nv >= bv - slack if m in UP else nv <= bv + slack)
                g["checks"].append({"suite": suite, "metric": m, "new": nv, "base": bv, "ok": bool(ok),
                                    "rule": "%s r3-2800 within 1 item (%.3f)" % (">=" if m in UP else "<=", 1.0 / n_m)})
        cn, cb = GS.chat(a.chatdev_new), GS.chat(a.chatdev_base)
        if cn is None or cb is None or cn["n"] < cb["n"]:
            g["missing"].append("chat dev v3 (new %s, base %s)" % (cn and cn["n"], cb and cb["n"]))
        else:
            g["checks"].append({"suite": "chatdev3", "metric": "pass_rate", "new": cn["pass_rate"], "base": cb["pass_rate"],
                                "ok": cn["pass_rate"] >= cb["pass_rate"] - 1.0 / cb["n"] - 1e-9,
                                "rule": ">= r3-2800 within 1 item (%.4f)" % (1.0 / cb["n"])})
        rn, rb = {r["id"]: r for r in load(a.r3_new)}, {r["id"]: r for r in load(a.r3_base)}
        ids = sorted(set(rn) & set(rb))
        if not ids or len(ids) < 0.95 * len(rb):
            g["missing"].append("chat_test_r3: %d common of %d" % (len(ids), len(rb)))
        else:
            amb = {json.loads(l)["id"] for l in open(a.ambiguous, encoding="utf-8") if l.strip()}
            g["fog_ambiguous_excluded"] = len(amb & set(ids))
            for tag, idset in (("gating (minus ambiguous)", [i for i in ids if i not in amb]), ("full (info)", ids)):
                gating = tag.startswith("gating")
                for fog in ("online", "offline", "timeout"):
                    sel = [i for i in idset if rb[i].get("fog") == fog]
                    pn = {i: float(bool(rn[i]["pass"])) for i in sel}
                    pb = {i: float(bool(rb[i]["pass"])) for i in sel}
                    m, z, n = paired(pn, pb, sel)
                    ok = not worse_beyond_noise(m, z, n)
                    g["fog" if gating else "fog_full"][fog] = {
                        "n": n, "new": round(sum(pn.values()) / max(1, n), 3), "base": round(sum(pb.values()) / max(1, n), 3),
                        "base_reported": (BASE_FOG_FILTERED if gating else BASE_FOG)[fog], "diff": round(m, 4), "z": round(z, 2), "ok": ok}
                    if gating:
                        g["checks"].append({"suite": "chat_test_r3 (minus ambiguous)", "metric": "fog=" + fog, "new": g["fog"][fog]["new"],
                                            "base": g["fog"][fog]["base"], "ok": ok, "rule": "not lower beyond noise (paired z < -1.96 and >= 1 item)"})
    complete = not g["missing"] and (a.stage == "final" or parts)
    g["pass"] = bool(complete and all(c["ok"] for c in g["checks"]))
    if a.stage == "a" and not g["missing"] and not ok_a:
        verdict = "FAIL"
    elif a.stage == "a":
        verdict = "A-PASS (b, c pending)" if ok_a and not g["missing"] else "INCOMPLETE"
    else:
        verdict = "PASS" if g["pass"] else ("FAIL" if any(not c["ok"] for c in g["checks"]) else "INCOMPLETE")
    g["verdict"] = verdict
    os.makedirs(a.out, exist_ok=True)
    json.dump(g, open(os.path.join(a.out, "gate.json"), "w"), indent=1)
    L4 = ["# r4 top-up STRICT gate: %s vs %s (r3 step 2800) -> **%s**" % (a.new, a.base, verdict), "",
          "Rule (TOPUP.md): (a) r4 held-out cross-domain test better than r3-2800 by >= 1 item, no part worse beyond noise; "
          "(b) all 19 existing gate checks >= r3-2800 within 1 item; (c) chat_test_r3 fog slices not lower beyond noise. "
          "Q4_0 on the host GPU (host = board numerics). On FAIL r3-2800 (rsn_v3_4b_r3_q4_0.gguf) stays the model.", ""]
    if g["missing"]:
        L4 += ["Missing: " + "; ".join(g["missing"]), ""]
    L4 += ["| suite | metric | r4 | r3-2800 | rule | ok |", "|---|---|---|---|---|---|"]
    L4 += ["| %s | %s | %s | %s | %s | %s |" % (c["suite"], c["metric"], c["new"], c["base"], c["rule"], "yes" if c["ok"] else "**NO**")
           for c in g["checks"]]
    if g["a"]:
        L4 += ["", "## (a) r4 test detail", "", "```", json.dumps(g["a"], indent=1), "```"]
    for key, head in (("fog", "## (c) chat_test_r3 by fog, GATING: minus %s ambiguous items (data/chat_test_r3_ambiguous.jsonl, owner 2026-11-12)"
                       % g.get("fog_ambiguous_excluded", "?")),
                      ("fog_full", "## chat_test_r3 by fog, full set (info, not gating)")):
        if g[key]:
            L4 += ["", head, "", "| fog | n | r4 | r3-2800 | reported r3-2800 | paired diff | z | ok |", "|---|---|---|---|---|---|---|---|"]
            L4 += ["| %s | %d | %s | %s | %s | %s | %s | %s |" % (f, d["n"], d["new"], d["base"], d["base_reported"], d["diff"], d["z"], d["ok"])
                   for f, d in g[key].items()]
    if g["fog"]:
        L4 += ["", "Baseline note: r3-2800 filtered (gating) fog baselines from its cached gate_r3 outputs: online 354/404 = 0.876, "
               "offline 340/460 = 0.739, timeout 36/69 = 0.522 (full: 0.841 / 0.692 / 0.522; the 50 excluded items: 1 pass)."]
    open(os.path.join(a.out, "GATE_r4.md"), "w").write("\n".join(L4) + "\n")
    print(L4[0])
    if verdict.startswith("A-PASS") or verdict == "PASS":
        sys.exit(0)
    sys.exit(1 if verdict == "FAIL" else 2)


if __name__ == "__main__":
    main()
