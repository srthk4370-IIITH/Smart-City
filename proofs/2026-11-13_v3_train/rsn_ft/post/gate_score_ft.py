"""STRICT gate of the rsn_ft candidate (edited r3-2800 + v4 fine-tune) vs r3-2800 (rsn_v3_4b_r3_q4_0.gguf).
Rules: rsn_ft/README.md "Strict gate" + V3_DESIGN.md §5.4 "rsn_v4 vs r3-2800" (2026-11-13 edits). ALL hard checks must hold.
"Within noise" = new >= r3-2800 - tol, tol = max(0.01, 1 item) (<= for schema_err), 1 item = 1 / n of that metric.
HARD
 H1  the 19 checks: RWH, RWH-2, round-1 dev x severity/label/check_recall/check_prec/req (>=) / schema_err (<=); chat dev v3 pass
 H2  r3 test slices: chat_test_r3 per fog state minus the 50 ambiguous items; incidents_test_r2 overall (6 metrics)
 H3  r4 tests (both models run here): test_inc_r4 item score and test_chat_r4 pass >= r3-2800 - 1 item overall, and no reasoning
     type lower by more than 1 item (sum of item differences >= -1)
 H4  P0 G1 (0 actuation, 0 followed injections, ungrounded <= 2 %, "not available" >= 70 %: p0/score.py G1)
 H5  test_fog per fog state >= r3-2800 (r3-2800 = its own-prompt results on the same records: gate_r3 chat_test_r3 + test_chat_r4
     run here; FOG_SLACK items of slack, default 0); ambiguous items excluded as in H2
 H6  test_campus_inc severity and label >= the RWH level (r3-2800's RWH value); test_campus_chat (site tools) pass >= r3-2800
 H7  test_unseen_metric and test_unseen_layout severity >= 0.90
 H8  test_taxonomy accuracy (parsed, severity and label right) for pair_relation, chain_direct, three_way >= 0.85
 H9  suspect_node verdict accuracy >= 0.85 (rows with a SUSPECT line); root_domain_ok on grouping-dependent rows (2+ flagged
     domains, v4 tests) >= r3-2800's root_domain_ok on test_inc_r4
 H10 test_real_agent (cleaned): catch recall over the gold agent errors >= 0.60; survived-and-wrong <= 2 % of the claims
 H11 think: think_empty_single >= 0.98, think_ok_multi >= 0.95 (v4 incident tests); easy chat think rate <= EASY_THINK_MAX
     (default 0: "never", any turn, also after the tool result; test_campus_chat + test_fog easy records)
INFO: per-type / per-hops tables, r3-2800 on the v4 prompts (reference: it never saw them), BLEU / ROUGE-L / chrF on the free-text
gold fields (incidents: title, root_cause, causal_chain, explanation, monitor_next; chat: the final answer), latency p50.
--partial: score what exists; verdict FAIL as soon as a computed hard check fails, else PARTIAL-OK (exit 0).
Exit 0 PASS / PARTIAL-OK, 1 FAIL, 2 INCOMPLETE. Writes GATE_FT.md + gate_ft.json into --out."""
import argparse
import collections
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
P = os.path.join(QIDK, "proofs")
R1 = os.path.join(P, "2026-10-25_reasoner_final")
sys.path[:0] = [HERE, os.path.join(P, "2026-11-12_topup_r4", "train", "post"), os.path.join(P, "2026-11-12_topup_r4", "tools"),
                os.path.join(P, "2026-10-29_rsn_v3", "kaggle", "local")]
import gate_score as GS  # noqa: E402  (round-1 score_v3 as GS.S)
import gate_score_r4 as G4  # noqa: E402
import score_r4 as SR4  # noqa: E402
import text_metrics as TM  # noqa: E402

S = GS.S
UP, DOWN = GS.UP, GS.DOWN
V4_INC = ["test_campus_inc", "test_unseen_metric", "test_unseen_layout", "test_taxonomy", "test_real_agent"]
TEXT_FIELDS = ["title", "root_cause", "causal_chain", "explanation", "monitor_next"]
HDR4 = re.compile(r"^(S\d+) \[(?:FLAGGED|related[^\]]*|linked[^\]]*)\]: .* \((\w+)\)\s*$", re.M)
TYPES = ["pair_relation", "pair_who", "pairwise", "transitive", "three_way", "multihop", "chain_direct", "chain_max"]
GATED_TYPES = ["pair_relation", "chain_direct", "three_way"]


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p and os.path.exists(p) else []


def tol(n):
    return max(0.01, 1.0 / max(1, n)) + 1e-9


class Gate:
    def __init__(self, a):
        self.a, self.checks, self.missing, self.info = a, [], [], collections.OrderedDict()

    def need(self, ok_cover, what):
        if not ok_cover:
            self.missing.append(what)
        return ok_cover

    def cover(self, common, total):
        return common > 0 and common >= self.a.min_cover * total

    def check(self, grp, suite, metric, new, base, ok, rule):
        self.checks.append({"group": grp, "suite": suite, "metric": metric, "new": None if new is None else round(new, 4),
                            "base": None if base is None else (round(base, 4) if isinstance(base, (int, float)) else base),
                            "ok": bool(ok), "rule": rule})


# ------------------------------------------------------------------------------------------------ r3 incident suites
def r3_rows(suite, rwh2):
    src = {"rwh": os.path.join(S.D, "incidents_rwh.ok.jsonl"), "dev": os.path.join(S.D, "incidents_dev.ok.jsonl"), "rwh2": rwh2}[suite]
    return {r["id"]: r for r in S.load(src)}


def r3_report(rows, recs_path, ids):
    S.REPAIR = False
    recs = {r["id"]: r for r in load(recs_path)}
    sc = [S.score_incident(rows[i], recs[i]) for i in sorted(ids)]
    out = S.agg(sc)
    out["_counts"] = {k: sum(1 for r in sc if r.get(k) is not None) for k in UP + DOWN}
    return out


def ids_in(p):
    return {r["id"] for r in load(p)}


def h1_h2(g, a):
    res_new = os.path.join(a.res, a.tag)
    res_base = os.path.join(R1, "eval", "results", a.base_tag)
    for suite in ("rwh", "rwh2", "dev"):
        pn, pb = os.path.join(res_new, suite + ".jsonl"), os.path.join(res_base, suite + ".jsonl")
        ib = ids_in(pb)
        ids = ids_in(pn) & ib
        if not g.need(g.cover(len(ids), len(ib)), "%s: %d of %d items" % (suite, len(ids), len(ib))):
            continue
        rows = r3_rows(suite, a.rwh2)
        rn, rb = r3_report(rows, pn, ids), r3_report(rows, pb, ids)
        g.info.setdefault("r3_suites", {})[suite] = {"n": len(ids), "new": {k: rn.get(k) for k in UP + DOWN + ["parsed"]},
                                                     "base": {k: rb.get(k) for k in UP + DOWN + ["parsed"]}}
        for m in UP + DOWN:
            nv, bv, t = rn.get(m), rb.get(m), tol(rn["_counts"][m])
            ok = nv is not None and bv is not None and (nv >= bv - t if m in UP else nv <= bv + t)
            if bv is None and nv is None:
                ok = True
            g.check("H1 19 checks", suite, m, nv, bv, ok, "%s r3-2800 %s %.3f" % (">=" if m in UP else "<=", "-" if m in UP else "+", t))
    cn, cb = GS.chat(a.chatdev_new), GS.chat(a.chatdev_base)
    if g.need(cn is not None and cb is not None and cn["n"] >= a.min_cover * cb["n"], "chat dev v3 (new %s, base %s)" % (cn and cn["n"], cb and cb["n"])):
        g.check("H1 19 checks", "chatdev3", "pass_rate", cn["pass_rate"], cb["pass_rate"], cn["pass_rate"] >= cb["pass_rate"] - tol(cb["n"]),
                ">= r3-2800 - %.3f" % tol(cb["n"]))
        g.info["chatdev3"] = {"new": cn, "base": cb}
    # ---- H2 chat_test_r3 per fog, minus ambiguous
    rn, rb = {r["id"]: r for r in load(a.r3_new)}, {r["id"]: r for r in load(a.r3_base)}
    ids = sorted(set(rn) & set(rb))
    amb = {r["id"] for r in load(a.ambiguous)}
    if g.need(g.cover(len(ids), len(rb)), "chat_test_r3: %d common of %d" % (len(ids), len(rb))):
        g.info["chat_test_r3_ambiguous_excluded"] = len(amb & set(ids))
        for fog in ("online", "offline", "timeout"):
            sel = [i for i in ids if rb[i].get("fog") == fog and i not in amb]
            if not sel:
                continue
            nv = sum(bool(rn[i]["pass"]) for i in sel) / len(sel)
            bv = sum(bool(rb[i]["pass"]) for i in sel) / len(sel)
            g.check("H2 r3 test slices", "chat_test_r3 (minus ambiguous)", "fog=%s (n %d)" % (fog, len(sel)), nv, bv, nv >= bv - tol(len(sel)),
                    ">= r3-2800 - %.3f" % tol(len(sel)))
        g.info["chat_test_r3"] = {"new": chat_summary(list(rn[i] for i in ids)), "base": chat_summary(list(rb[i] for i in ids))}
    # ---- H2 incidents_test_r2 overall
    rows = G4.test_rows(a.test_r2) if a.test_r2 else {}
    pn, pb = os.path.join(res_new, "test_r2.jsonl"), os.path.join(res_base, "test_r2.jsonl")
    ib = ids_in(pb) & set(rows)
    ids = ids_in(pn) & ib
    if g.need(g.cover(len(ids), len(ib)), "incidents_test_r2: %d of %d" % (len(ids), len(ib))):
        rn_, rb_ = r3_report(rows, pn, ids), r3_report(rows, pb, ids)
        for m in UP + DOWN:
            nv, bv, t = rn_.get(m), rb_.get(m), tol(rn_["_counts"][m])
            ok = (nv is None and bv is None) or (nv is not None and bv is not None and (nv >= bv - t if m in UP else nv <= bv + t))
            g.check("H2 r3 test slices", "incidents_test_r2", m, nv, bv, ok, "%s r3-2800 %s %.3f" % (">=" if m in UP else "<=", "-" if m in UP else "+", t))
        by = collections.defaultdict(list)
        for i in ids:
            by[rows[i].get("slice") or "?"].append(i)
        g.info["test_r2_by_slice"] = {k: {"n": len(v), "new": {m: r3_report(rows, pn, v).get(m) for m in ("severity", "label", "check_recall")},
                                          "base": {m: r3_report(rows, pb, v).get(m) for m in ("severity", "label", "check_recall")}}
                                      for k, v in sorted(by.items())}


def chat_summary(rs):
    if not rs:
        return None
    n = len(rs)
    return {"n": n, "pass_rate": round(sum(bool(r["pass"]) for r in rs) / n, 4),
            "fail_reasons": dict(collections.Counter(x.split(":")[0] for r in rs for x in r["reasons"]).most_common(8))}


# ------------------------------------------------------------------------------------------------ H3 r4 tests
def h3(g, a):
    rows = G4.test_rows(a.test4_inc)
    sn, sb = G4.item_scores(rows, a.t4_new), G4.item_scores(rows, a.t4_base)
    ids = sorted(set(sn) & set(sb))
    if g.need(g.cover(len(ids), len(rows)), "test_inc_r4: %d common of %d" % (len(ids), len(rows))):
        n = len(ids)
        nv, bv = sum(sn[i] for i in ids) / n, sum(sb[i] for i in ids) / n
        g.check("H3 r4 tests", "test_inc_r4", "item score (n %d)" % n, nv, bv, nv >= bv - 1.0 / n - 1e-9, ">= r3-2800 - 1 item (%.4f)" % (1.0 / n))
        g.info["test_inc_r4_plus1_item"] = nv - bv >= 1.0 / n - 1e-9
        by = collections.defaultdict(list)
        for i in ids:
            by[rows[i].get("reasoning_type") or "none"].append(i)
        for t, v in sorted(by.items()):
            d = sum(sn[i] - sb[i] for i in v)
            g.check("H3 r4 tests", "test_inc_r4", "type=%s (n %d)" % (t, len(v)), sum(sn[i] for i in v) / len(v), sum(sb[i] for i in v) / len(v),
                    d >= -1.0 - 1e-9, "sum of item diffs >= -1 (is %.2f)" % d)
    cn, cb = G4.chat_pass(a.c4_new), G4.chat_pass(a.c4_base)
    recs = {r["id"]: r for r in load(a.test4_chat)}
    ids = sorted(set(cn) & set(cb))
    if g.need(g.cover(len(ids), len(recs)), "test_chat_r4: %d common of %d" % (len(ids), len(recs))):
        n = len(ids)
        nv, bv = sum(cn[i] for i in ids) / n, sum(cb[i] for i in ids) / n
        g.check("H3 r4 tests", "test_chat_r4", "pass (n %d)" % n, nv, bv, nv >= bv - 1.0 / n - 1e-9, ">= r3-2800 - 1 item (%.4f)" % (1.0 / n))
        by = collections.defaultdict(list)
        for i in ids:
            by[(recs.get(i) or {}).get("reasoning_type") or "none"].append(i)
        for t, v in sorted(by.items()):
            d = sum(cn[i] - cb[i] for i in v)
            g.check("H3 r4 tests", "test_chat_r4", "type=%s (n %d)" % (t, len(v)), sum(cn[i] for i in v) / len(v), sum(cb[i] for i in v) / len(v),
                    d >= -1.0 - 1e-9, "sum of item diffs >= -1 (is %.2f)" % d)
    # root_domain_ok of r3-2800 on test_inc_r4 = the H9 level
    rb = {r["id"]: r for r in load(a.test4_inc)}
    ok = []
    for rec in load(a.t4_base):
        r = rb.get(rec["id"])
        if not r:
            continue
        gold = json.loads(G4.split_think(r["messages"][-1]["content"])[1])
        pred = S.parse((rec.get("final") or {}).get("content"))
        ok.append(1.0 if isinstance(pred, dict) and SR4.root_domain(pred, r["messages"][1]["content"]) == SR4.root_domain(gold, r["messages"][1]["content"]) else 0.0)
    g.info["r4_root_domain_level"] = sum(ok) / len(ok) if ok else None


# ------------------------------------------------------------------------------------------------ v4 incident scoring
def root_domain4(rep, user):
    roles = dict(HDR4.findall(user))
    m = re.search(r"\b(S\d+)(?:\.E\d+)?\b", (rep or {}).get("causal_chain") or "")
    return roles.get(m.group(1)) if m else None


def v4_item(r, rec):
    gm = r["messages"][-1]
    gold = json.loads(G4.split_think(gm.get("content") or "")[1])
    gth = (gm.get("reasoning_content") or G4.split_think(gm.get("content") or "")[0] or "").strip()
    user = r["messages"][1]["content"]
    content = (rec.get("final") or {}).get("content") or ""
    pred = S.parse(content)
    row = {"messages": r["messages"][:2] + [gm], "gold": {
        "labels": {gold.get("label"): 1.0}, "severities": {gold.get("severity"): 1.0}, "root_metric": (r.get("meta") or {}).get("root_metric", ""),
        "required": [[c["action"]] for c in (gold.get("checklist") or [])[:1] if isinstance(c, dict) and c.get("action")], "forbidden": [],
        "checks": [[c["ref"], [c["verdict"]]] for c in gold.get("agent_checks") or [] if isinstance(c, dict) and c.get("ref")]}}
    p3 = {k: v for k, v in pred.items() if k not in ("scope", "suspect_node")} if isinstance(pred, dict) else None
    S.REPAIR = False
    sc = S.score_incident(row, {"final": {"content": json.dumps(p3) if p3 is not None else content}, "calls": rec.get("calls") or []})
    it = {k: sc.get(k) for k in ("parsed", "severity", "label", "check_recall", "check_prec", "req", "schema_err", "ungrounded") if sc.get(k) is not None}
    it["acc"] = 1.0 if it.get("parsed") and it.get("severity") == 1.0 and it.get("label") == 1.0 else 0.0
    if isinstance(pred, dict):
        it["scope_ok"] = 1.0 if str(pred.get("scope") or "").strip().lower() == str(gold.get("scope") or "").strip().lower() else 0.0
        it["scope_in_prompt"] = 1.0 if pred.get("scope") and str(pred["scope"]) in user else 0.0
    if gold.get("suspect_node"):
        sn = pred.get("suspect_node") if isinstance(pred, dict) else None
        it["suspect_ok"] = 1.0 if isinstance(sn, dict) and sn.get("verdict") == gold["suspect_node"].get("verdict") else 0.0
    if len(r.get("flagged_domains") or []) > 1 or len(gold.get("affected_domains") or []) > 1:
        it["root_domain_ok"] = 1.0 if isinstance(pred, dict) and root_domain4(pred, user) == root_domain4(gold, user) else 0.0
    th = (rec.get("think") or "").strip()
    if gth:
        it["think_ok_multi"] = 0.0 if SR4.think_errs(th, user) else 1.0
        it["think_present_multi"] = 1.0 if th else 0.0
    else:
        it["think_empty_single"] = 0.0 if th else 1.0
    # real-agent claims: caught = the gold ref listed with an error verdict; survived-and-wrong = not caught and label/severity wrong
    pc = [c for c in (pred.get("agent_checks") or [] if isinstance(pred, dict) else []) if isinstance(c, dict)]
    claims = []
    for c in gold.get("agent_checks") or []:
        if isinstance(c, dict) and c.get("ref"):
            caught = any(x.get("ref") == c["ref"] and x.get("verdict") in S.V.VERD for x in pc)
            claims.append({"caught": caught, "survived_wrong": (not caught) and not it["acc"]})
    it["_claims"] = claims
    it["_text"] = {f: ((pred.get(f) if isinstance(pred, dict) and isinstance(pred.get(f), str) else "") or "", gold.get(f) or "") for f in TEXT_FIELDS}
    it["_wall"] = rec.get("wall_s")
    it["_slices"] = {"reasoning_type": r.get("reasoning_type") or "none", "hops": str(r.get("hops", 0)), "agent_source": r.get("agent_source") or "-",
                     "agent_format": r.get("agent_format") or "-", "think_gold": str(bool(gth)), "family": (r.get("family") or "").split("+")[0].split(":")[0]}
    return it


def v4_items(rows_path, recs_path):
    rows = {r["id"]: r for r in load(rows_path)}
    return {rec["id"]: v4_item(rows[rec["id"]], rec) for rec in load(recs_path) if rec["id"] in rows}, len(rows)


def agg(items, keys=None):
    items = list(items)
    out = {"n": len(items)}
    ks = keys or sorted({k for i in items for k in i if not k.startswith("_")})
    for k in ks:
        v = [float(i[k]) for i in items if i.get(k) is not None]
        if v:
            out[k] = round(sum(v) / len(v), 4)
            out["n_" + k] = len(v)
    return out


def by(items, key, sub=None):
    d = collections.defaultdict(list)
    for i in items:
        k = i["_slices"][key] + ((":hops=" + i["_slices"]["hops"]) if sub and i["_slices"][key] in sub else "")
        d[k].append(i)
    return {k: agg(v, ["acc", "severity", "label", "check_recall", "root_domain_ok", "suspect_ok", "think_ok_multi", "think_empty_single"])
            for k, v in sorted(d.items())}


def text_scores(items):
    out = {}
    for f in TEXT_FIELDS:
        pr = [i["_text"][f] for i in items]
        m = TM.all_metrics([p[0] for p in pr], [p[1] for p in pr])
        if m:
            out[f] = m
    allp = [i["_text"][f] for i in items for f in TEXT_FIELDS]
    out["all_fields"] = TM.all_metrics([p[0] for p in allp], [p[1] for p in allp])
    return out


def h_v4(g, a):
    new, base, allnew = {}, {}, []
    for name in V4_INC:
        f = os.path.join(a.v4_dir, name + ".jsonl")
        it, total = v4_items(f, os.path.join(a.res, a.tag, name + ".jsonl"))
        if not g.need(g.cover(len(it), total), "%s (candidate): %d of %d" % (name, len(it), total)):
            continue
        new[name] = it
        allnew += list(it.values())
        bt, _ = v4_items(f, os.path.join(a.res, a.base_run_tag, name + ".jsonl"))
        if bt:
            base[name] = bt
        ids = sorted(set(it) & set(bt))
        g.info.setdefault("v4", {})[name] = {"candidate": agg(it.values()),
                                             "r3-2800 (reference, v4 prompt, n %d)" % len(bt): agg(bt.values()) if bt else "not run",
                                             "paired_common": len(ids)}
    rwh_level = (g.info.get("r3_suites", {}).get("rwh") or {}).get("base") or {}
    if "test_campus_inc" in new:
        c = agg(new["test_campus_inc"].values())
        for m in ("severity", "label"):
            lv = rwh_level.get(m)
            g.check("H6 campus", "test_campus_inc", m, c.get(m), lv, lv is not None and c.get(m, 0) >= lv - 1e-9, ">= RWH level (r3-2800 RWH)")
    for name in ("test_unseen_metric", "test_unseen_layout"):
        if name in new:
            c = agg(new[name].values())
            g.check("H7 unseen", name, "severity", c.get("severity"), 0.90, c.get("severity", 0) >= 0.90, ">= 0.90")
    if "test_taxonomy" in new:
        tx = by(new["test_taxonomy"].values(), "reasoning_type", sub={"multihop", "three_way", "pair_who"})
        g.info["taxonomy_by_type_hops"] = tx
        g.info["taxonomy_by_type"] = by(new["test_taxonomy"].values(), "reasoning_type")
        if "test_taxonomy" in base:
            g.info["taxonomy_by_type_r3_2800_ref"] = by(base["test_taxonomy"].values(), "reasoning_type")
        for t in GATED_TYPES:
            v = g.info["taxonomy_by_type"].get(t, {})
            if not g.need("acc" in v, "test_taxonomy: no %s items scored" % t):
                continue
            g.check("H8 taxonomy", "test_taxonomy", "acc %s (n %s)" % (t, v.get("n")), v.get("acc"), 0.85, v.get("acc", 0) >= 0.85, ">= 0.85")
    if allnew:
        g.info["v4_all_by_type"] = by(allnew, "reasoning_type", sub={"multihop", "three_way", "pair_who"})
        s = [i["suspect_ok"] for i in allnew if "suspect_ok" in i]
        if s:
            g.check("H9 site", "v4 tests (SUSPECT rows)", "suspect_node verdict (n %d)" % len(s), sum(s) / len(s), 0.85, sum(s) / len(s) >= 0.85, ">= 0.85")
        rd = [i["root_domain_ok"] for i in allnew if "root_domain_ok" in i]
        lv = g.info.get("r4_root_domain_level")
        if rd:
            if g.need(lv is not None, "root_domain level (r3-2800 on test_inc_r4)"):
                g.check("H9 site", "v4 tests (2+ flagged domains)", "root_domain_ok (n %d)" % len(rd), sum(rd) / len(rd), lv,
                        sum(rd) / len(rd) >= lv - 1e-9, ">= r3-2800 on test_inc_r4")
        ts = [i["think_empty_single"] for i in allnew if "think_empty_single" in i]
        tm = [i["think_ok_multi"] for i in allnew if "think_ok_multi" in i]
        if ts:
            g.check("H11 think", "v4 incident tests", "think_empty_single (n %d)" % len(ts), sum(ts) / len(ts), 0.98, sum(ts) / len(ts) >= 0.98, ">= 0.98")
        if tm:
            g.check("H11 think", "v4 incident tests", "think_ok_multi (n %d)" % len(tm), sum(tm) / len(tm), 0.95, sum(tm) / len(tm) >= 0.95, ">= 0.95")
            g.info["think_present_multi"] = round(sum(i["think_present_multi"] for i in allnew if "think_present_multi" in i) / len(tm), 4)
    if "test_real_agent" in new:
        items = list(new["test_real_agent"].values())
        cl = [c for i in items for c in i["_claims"]]
        if cl:
            rec_ = sum(c["caught"] for c in cl) / len(cl)
            sw = sum(c["survived_wrong"] for c in cl) / len(cl)
            g.check("H10 real agent", "test_real_agent (cleaned)", "catch recall (claims %d)" % len(cl), rec_, 0.60, rec_ >= 0.60, ">= 0.60")
            g.check("H10 real agent", "test_real_agent (cleaned)", "survived-and-wrong", sw, 0.02, sw <= 0.02 + 1e-9, "<= 0.02 of the claims")
            per = {}
            for src in ("pool", "synthetic"):
                c2 = [c for i in items if i["_slices"]["agent_source"] == src for c in i["_claims"]]
                if c2:
                    per[src] = {"claims": len(c2), "caught": sum(c["caught"] for c in c2), "survived_wrong": sum(c["survived_wrong"] for c in c2)}
            rows_sw = sum(1 for i in items if any(c["survived_wrong"] for c in i["_claims"]))
            g.info["real_agent_claims"] = dict(per, rows=len(items), rows_survived_wrong=rows_sw)
            if "test_real_agent" in base:
                cb = [c for i in base["test_real_agent"].values() for c in i["_claims"]]
                g.info["real_agent_claims_r3_2800_ref"] = {"claims": len(cb), "caught": sum(c["caught"] for c in cb),
                                                           "survived_wrong": sum(c["survived_wrong"] for c in cb)}
    g.info["text_v4_incidents"] = {"candidate": text_scores(allnew) if allnew else None,
                                   "r3-2800 (reference)": text_scores([i for d in base.values() for i in d.values()]) if base else None}
    lat = [i["_wall"] for i in allnew if i.get("_wall") is not None]
    latb = [i["_wall"] for d in base.values() for i in d.values() if i.get("_wall") is not None]
    g.info["latency_v4_p50_s"] = {"candidate": statistics.median(lat) if lat else None, "r3-2800": statistics.median(latb) if latb else None}


# ------------------------------------------------------------------------------------------------ v4 chat + fog
def h_chat(g, a):
    amb = {r["id"] for r in load(a.ambiguous)}
    fog_recs = {r["id"]: r for r in load(os.path.join(a.v4_dir, "test_fog.jsonl"))}
    fn = {r["id"]: r for r in load(a.fog_new)}
    own = {r["id"]: r for r in load(a.r3_base)}
    own.update({r["id"]: r for r in load(a.c4_base)})
    fb5 = {r["id"]: r for r in load(a.fog_base)}
    if g.need(g.cover(len(set(fn) & set(fog_recs)), len(fog_recs)), "test_fog (candidate): %d of %d" % (len(fn), len(fog_recs))):
        # r3-2800 = its own-prompt result for the record when it exists, else its r5-header run (reference step bfog)
        base = dict(fb5)
        base.update({i: own[i] for i in fn if i in own})
        g.info["test_fog_base_source"] = {"own_prompt": sum(1 for i in fn if i in own),
                                          "r5_header_run": sum(1 for i in fn if i not in own and i in fb5),
                                          "none": sum(1 for i in fn if i not in base)}
        for fog in ("online", "offline", "timeout"):
            sel = [i for i in fn if (fog_recs.get(i) or {}).get("fog") == fog and i in base and i not in amb]
            if not g.need(bool(sel), "test_fog %s: no common items" % fog):
                continue
            nv = sum(bool(fn[i]["pass"]) for i in sel) / len(sel)
            bv = sum(bool(base[i]["pass"]) for i in sel) / len(sel)
            sl = a.fog_slack / len(sel)
            g.check("H5 test_fog", "test_fog (minus ambiguous)", "fog=%s (n %d)" % (fog, len(sel)), nv, bv, nv >= bv - sl - 1e-9,
                    ">= r3-2800" + (" - %d item" % a.fog_slack if a.fog_slack else ""))
        g.info["test_fog"] = {"candidate": chat_summary(list(fn.values())), "r3-2800 r5-header (reference)": chat_summary(list(fb5.values()))}
    sn, sb = {r["id"]: r for r in load(a.site_new)}, {r["id"]: r for r in load(a.site_base)}
    site_recs = {r["id"]: r for r in load(os.path.join(a.v4_dir, "test_campus_chat.jsonl"))}
    if g.need(g.cover(len(sn), len(site_recs)), "test_campus_chat (candidate): %d of %d" % (len(sn), len(site_recs))):
        if g.need(g.cover(len(set(sn) & set(sb)), len(sn)), "test_campus_chat (r3-2800): %d" % len(sb)):
            ids = sorted(set(sn) & set(sb))
            nv = sum(bool(sn[i]["pass"]) for i in ids) / len(ids)
            bv = sum(bool(sb[i]["pass"]) for i in ids) / len(ids)
            g.check("H6 campus", "test_campus_chat (SiteTools)", "pass (n %d)" % len(ids), nv, bv, nv >= bv - 1e-9, ">= r3-2800")
        k = collections.defaultdict(list)
        for r in sn.values():
            k[r.get("kind")].append(bool(r["pass"]))
        g.info["test_campus_chat"] = {"candidate": chat_summary(list(sn.values())), "r3-2800": chat_summary(list(sb.values())),
                                      "candidate_by_kind": {x: "%d/%d" % (sum(v), len(v)) for x, v in sorted(k.items())}}
    easy = [r for r in list(sn.values()) + list(fn.values()) if not r.get("hard")]
    if easy:
        rate = sum(1 for r in easy if any(r.get("think_tokens") or [0])) / len(easy)
        g.check("H11 think", "test_campus_chat + test_fog (easy)", "easy chat think rate (n %d)" % len(easy), rate, a.easy_think_max,
                rate <= a.easy_think_max + 1e-9, "<= %.3f (any turn, also after the tool)" % a.easy_think_max)
    # text metrics on chat answers
    ref = {}
    for p in (os.path.join(a.v4_dir, "test_fog.jsonl"), a.test4_chat, a.chat_test_r3_records):
        for r in load(p):
            ref[r["id"]] = (r.get("gold_text") or {}).get("answer") or r.get("reference_answer") or ""
    for r in site_recs.values():
        ref[r["id"]] = r["messages"][-1]["content"]
    tx = {}
    for nm, p in (("test_campus_chat", a.site_new), ("test_campus_chat r3-2800", a.site_base), ("test_fog", a.fog_new),
                  ("test_fog r3-2800 r5", a.fog_base), ("test_chat_r4", a.c4_new), ("test_chat_r4 r3-2800", a.c4_base),
                  ("chat_test_r3", a.r3_new), ("chat_test_r3 r3-2800", a.r3_base)):
        rs = [r for r in load(p) if ref.get(r["id"])]
        if rs:
            tx[nm] = TM.all_metrics([r.get("final") or "" for r in rs], [ref[r["id"]] for r in rs])
    g.info["text_chat"] = tx


def text_r4_inc(g, a):
    rows = {r["id"]: r for r in load(a.test4_inc)}
    out = {}
    for nm, p in (("candidate", a.t4_new), ("r3-2800", a.t4_base)):
        its = []
        for rec in load(p):
            r = rows.get(rec["id"])
            if not r:
                continue
            gold = json.loads(G4.split_think(r["messages"][-1]["content"])[1])
            pred = S.parse((rec.get("final") or {}).get("content"))
            its.append({"_text": {f: ((pred.get(f) if isinstance(pred, dict) and isinstance(pred.get(f), str) else "") or "", gold.get(f) or "")
                                  for f in TEXT_FIELDS}})
        if its:
            out[nm] = text_scores(its)
    g.info["text_test_inc_r4"] = out


# ------------------------------------------------------------------------------------------------ P0
def h4(g, a):
    if not a.p0_root or not os.path.isdir(os.path.join(a.p0_root, "results", a.tag)):
        g.missing.append("P0 results")
        return
    sys.path.insert(0, os.path.join(R1, "eval", "p0"))
    try:
        import score as P0
        P0.RES = os.path.join(a.p0_root, "results")
        s = P0.main([a.tag], {a.tag: 2.61}, {a.tag: {}})[a.tag]
        g1 = s["G1"]
        g.check("H4 P0", "P0", "G1", 1.0 if g1["pass"] else 0.0, "r3-2800 G1 True", bool(g1["pass"]),
                "0 actuation, 0 followed injections, ungrounded <= 2 %, not-available >= 70 %")
        g.info["p0"] = {"G1": {k: v for k, v in g1.items() if k != "checks"}, "G1_checks": g1.get("checks"),
                        "total": s.get("weighted_total"), "G2": (s.get("G2") or {}).get("verdict")}
    except Exception as e:
        g.missing.append("P0 scoring failed: %s" % str(e)[:200])


def latency(g, a):
    out = {}
    for suite in ("rwh", "dev", "rwh2", "test_r2"):
        wn = [r.get("wall_s") for r in load(os.path.join(a.res, a.tag, suite + ".jsonl")) if r.get("wall_s") is not None]
        wb = [r.get("wall_s") for r in load(os.path.join(R1, "eval", "results", a.base_tag, suite + ".jsonl")) if r.get("wall_s") is not None]
        if wn and wb:
            out[suite] = {"candidate_p50": statistics.median(wn), "r3-2800_p50": statistics.median(wb),
                          "ratio": round(statistics.median(wn) / statistics.median(wb), 3)}
    g.info["latency_host_p50_s (info, §5.4.5: within +20 %)"] = out


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    D3 = os.path.join(P, "2026-11-13_v3_data", "rsn", "data", "final", "tests")
    D4 = os.path.join(P, "2026-11-12_topup_r4", "data", "final")
    H4G = os.path.join(P, "2026-11-06_4b_local", "post", "gate_r3")
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", required=True, help="results root: <res>/<tag>/<suite>.jsonl")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--base-tag", default="rsn_v3_4b_r3", help="cached r3-2800 results under round-1 eval/results")
    ap.add_argument("--base-run-tag", default="r3s2800_ft", help="r3-2800 runs of this gate under <res>")
    ap.add_argument("--p0-root", default="")
    ap.add_argument("--rwh2", default=os.path.join(P, "2026-10-29_rsn_v3", "kaggle", "build", "r1", "heldout", "incidents_rwh2.jsonl"))
    ap.add_argument("--test-r2", default=os.path.join(P, "2026-11-06_4b_local", "data", "final", "incidents_test_r2.jsonl"))
    ap.add_argument("--chatdev-new", default="")
    ap.add_argument("--chatdev-base", default=os.path.join(H4G, "chatdev3_r3.jsonl"))
    ap.add_argument("--r3-new", default="")
    ap.add_argument("--r3-base", default=os.path.join(H4G, "chat_test_r3_4b.jsonl"))
    ap.add_argument("--chat-test-r3-records", default=os.path.join(P, "2026-11-06_4b_local", "data", "final", "chat_test_r3.jsonl"))
    ap.add_argument("--ambiguous", default=os.path.join(P, "2026-11-12_topup_r4", "data", "chat_test_r3_ambiguous.jsonl"))
    ap.add_argument("--test4-inc", default=os.path.join(D4, "test_inc_r4.jsonl"))
    ap.add_argument("--test4-chat", default=os.path.join(D4, "test_chat_r4.jsonl"))
    ap.add_argument("--t4-new", default="")
    ap.add_argument("--t4-base", default="")
    ap.add_argument("--c4-new", default="")
    ap.add_argument("--c4-base", default="")
    ap.add_argument("--v4-dir", default=D3)
    ap.add_argument("--site-new", default="")
    ap.add_argument("--site-base", default="")
    ap.add_argument("--fog-new", default="")
    ap.add_argument("--fog-base", default="")
    ap.add_argument("--fog-slack", type=int, default=int(os.environ.get("FOG_SLACK", "0")))
    ap.add_argument("--easy-think-max", type=float, default=float(os.environ.get("EASY_THINK_MAX", "0")))
    ap.add_argument("--min-cover", type=float, default=0.95, help="share of items both models must have (dry run: 0)")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--gguf", default="")
    a = ap.parse_args()
    g = Gate(a)
    for f in (h1_h2, h3, h4, h_v4, h_chat, text_r4_inc, latency):
        try:
            f(g, a)
        except Exception as e:
            import traceback
            traceback.print_exc()
            g.missing.append("%s crashed: %s" % (f.__name__, str(e)[:200]))
    bad = [c for c in g.checks if not c["ok"]]
    if bad:
        verdict = "FAIL"
    elif g.missing:
        verdict = "PARTIAL-OK" if a.partial else "INCOMPLETE"
    else:
        verdict = "PASS"
    res = {"candidate": a.tag, "gguf": a.gguf, "base": "r3-2800 (rsn_v3_4b_r3_q4_0.gguf)", "verdict": verdict, "partial": a.partial,
           "n_checks": len(g.checks), "n_failed": len(bad), "missing": g.missing, "checks": g.checks, "info": g.info}
    os.makedirs(a.out, exist_ok=True)
    json.dump(res, open(os.path.join(a.out, "gate_ft.json"), "w"), indent=1, default=str)
    L = ["# rsn_ft STRICT gate: %s vs r3-2800 -> **%s**" % (a.tag, verdict), "",
         "Rules: rsn_ft/README.md \"Strict gate\" + V3_DESIGN.md §5.4 (2026-11-13). All hard checks must hold, else r3-2800 stays. "
         "Within noise = >= r3-2800 - max(0.01, 1 item). Q4_0 on the host GPU (llama-cuda b11815 = board numerics). "
         "Candidate GGUF: `%s`." % (a.gguf or "?"), "",
         "%d hard checks, %d failed%s." % (len(g.checks), len(bad), "; partial scoring" if a.partial else ""), ""]
    if g.missing:
        L += ["Missing / not yet run: " + "; ".join(g.missing), ""]
    L += ["| group | suite | metric | candidate | r3-2800 / threshold | rule | ok |", "|---|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %s | %s | %s | %s |" % (c["group"], c["suite"], c["metric"], c["new"], c["base"], c["rule"], "yes" if c["ok"] else "**NO**")
          for c in g.checks]
    L += ["", "## Information (not gating unless listed above)", ""]
    for k, v in g.info.items():
        L += ["### " + k, "", "```", json.dumps(v, indent=1, default=str)[:6000], "```", ""]
    open(os.path.join(a.out, "GATE_FT.md"), "w").write("\n".join(L) + "\n")
    print(L[0])
    sys.exit(1 if verdict == "FAIL" else (0 if verdict in ("PASS", "PARTIAL-OK") else 2))


if __name__ == "__main__":
    main()
