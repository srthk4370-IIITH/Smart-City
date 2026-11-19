"""Scorer for the r4 held-out test (never trained on). Two parts:

inc  : outputs of run_r4_inc.py vs test_inc_r4.jsonl. Per item: parsed, severity, label, check_recall/check_prec (gold agent_checks),
       req (gold first action present), schema_err / ungrounded (round-1 verify.py, as score_v3), root_domain_ok (domain of the first
       sensor ref in causal_chain, gold vs prediction), think rules: think_ok_multi (2+ flagged domains: non-empty, <= 80 think tokens,
       numbers/times only from the prompt, no braces), think_empty_single (single domain: empty). Sliced by reasoning_type, hops,
       family, think_expected, mode (early/refine), novel_names.
chat : outputs of eval_chat_r4.py (chat_r3_eval loop on the r4 store) vs test_chat_r4.jsonl: verify_chat pass + answer_key
       (relation class phrase | first-mentioned id | mediator id present | ids in order) -> reasoning_ok = pass and key_ok.
       Sliced by reasoning_type, hops, kind, fog, hard, hinglish.
Gold free text is kept in each test record (gold_text) for BLEU/ROUGE/chrF later.
  python3 score_r4.py inc  --out OUT.jsonl [--rows ../data/final/test_inc_r4.jsonl] [--json SUMMARY.json]
  python3 score_r4.py chat --out OUT.jsonl [--records ../data/final/test_chat_r4.jsonl] [--json SUMMARY.json]
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "eval"))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "pipeline"))
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "pipeline"))
import score_v3 as S  # noqa: E402
import verify as V  # noqa: E402
import verify_chat as VC  # noqa: E402
FINAL = os.path.join(HERE, "..", "data", "final")
HDR = re.compile(r"^(S\d+) \[(?:FLAGGED|related[^\]]*)\]: .* \((\w+)\)$", re.M)
REL_PH = {"drove": ["drove", "caused", "led to", "triggered", "because of", "explains", "followed from", "result of", "driven by", "indirect"],
          "same": ["same cause", "shared cause", "common cause", "both came from", "both caused by", "both driven by", "both followed"],
          "fault": ["sensor fault", "faulty", "bad data", "sensor_fault", "not a real"],
          "indep": ["unrelated", "independent", "no link", "not linked", "no known link", "coincid", "not related", "no causal"]}


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p and os.path.exists(p) else []


def root_domain(rep, user):
    roles = dict(HDR.findall(user))
    m = re.search(r"\b(S\d+)(?:\.E\d+)?\b", (rep or {}).get("causal_chain") or "")
    return roles.get(m.group(1)) if m else None


def think_errs(th, user):
    errs = []
    if not th:
        return ["empty"]
    if VC.think_tokens(th) > VC.THINK_MAX:
        errs.append("long")
    if re.search(r"[{}\"]", th):
        errs.append("brace")
    t = re.sub(r"\b(?:S\d+\.E\d+|S\d+|E\d+|R\d+|M\d+|PM2\.5|PM10|CO2|SB00|11 kV|r2)\b", " ", th)
    cn = V.numset(re.sub(V.STRIP, " ", user))
    if any(tm not in user for tm in re.findall(r"\b\d\d:\d\d\b", t)):
        errs.append("time")
    if any(x not in cn for x in V.numset(re.sub(r"\b\d\d:\d\d\b", " ", t))):
        errs.append("num")
    return errs


def agg(items):
    out = {"n": len(items)}
    keys = sorted({k for o in items for k, v in o.items() if isinstance(v, (int, float)) and not isinstance(v, bool) or isinstance(v, bool)})
    for k in keys:
        v = [float(o[k]) for o in items if k in o and o[k] is not None]
        if v:
            out[k] = round(sum(v) / len(v), 3)
    return out


def score_inc(a):
    rows = {r["id"]: r for r in load(a.rows)}
    outs = load(a.out)
    items = []
    for o in outs:
        r = rows.get(o["id"])
        if not r:
            continue
        gold = json.loads(r["messages"][-1]["content"])
        row = {"messages": r["messages"], "gold": {"labels": {gold["label"]: 1.0}, "severities": {gold["severity"]: 1.0}, "root_metric": r["meta"]["root_metric"],
                                                    "required": [[gold["checklist"][0]["action"]]], "forbidden": [],
                                                    "checks": [[c["ref"], [c["verdict"]]] for c in gold["agent_checks"]]}}
        S.REPAIR = False
        sc = S.score_incident(row, {"final": {"content": o.get("json_text") or ""}, "calls": []})
        user = r["messages"][1]["content"]
        pred = S.parse(o.get("json_text") or "")
        it = {k: v for k, v in sc.items() if k in ("parsed", "severity", "label", "check_recall", "check_prec", "req", "schema_err", "ungrounded",
                                                   "floor_viol", "title_root")}
        it["root_domain_ok"] = 1 if isinstance(pred, dict) and root_domain(pred, user) == root_domain(gold, user) else 0
        th = o.get("think") or ""
        if r["think_expected"]:
            it["think_ok_multi"] = 0 if think_errs(th, user) else 1
            it["think_present_multi"] = 1 if th.strip() else 0
        else:
            it["think_empty_single"] = 0 if th.strip() else 1
        it["gen_tokens"] = o.get("gen_tokens", 0)
        it["_slices"] = {"reasoning_type": r["reasoning_type"], "hops": str(r["hops"]), "family": r["family"].split("+")[0],
                         "think_expected": str(r["think_expected"]), "mode": "refine" if "+refine" in r["family"] else "early",
                         "novel_names": str(r.get("novel_names")), "gold_severity": gold["severity"]}
        items.append(it)
    return summarize(items, ["reasoning_type", "hops", "family", "think_expected", "mode", "novel_names", "gold_severity"])


def key_ok(rec, final):
    k = rec.get("answer_key") or {}
    low = final.lower()
    ids = re.findall(r"INC-\d+", final)
    if "relation" in k:
        return 1 if any(p in low for p in REL_PH[k["relation"]]) else 0
    if "first_id" in k:
        return 1 if ids and ids[0] == k["first_id"] else 0
    if "mediator_id" in k:
        return 1 if k["mediator_id"] in final else 0
    if "ids_order" in k:
        pos = [final.find(i) for i in k["ids_order"]]
        return 1 if all(p >= 0 for p in pos) and pos == sorted(pos) else 0
    return None


def score_chat(a):
    recs = {r["id"]: r for r in load(a.records)}
    items = []
    for o in load(a.out):
        r = recs.get(o["id"])
        if not r:
            continue
        it = {"pass": 1 if o["pass"] else 0}
        ko = key_ok(r, o.get("final") or "")
        if ko is not None:
            it["key_ok"] = ko
            it["reasoning_ok"] = 1 if (o["pass"] and ko) else 0
        tt = o.get("think_tokens") or [0]
        it["think_nonempty"] = 1 if any(tt) else 0
        for x in o.get("reasons") or []:
            it["fail_" + x.split(":")[0]] = 1
        it["_slices"] = {"reasoning_type": r.get("reasoning_type", "none"), "hops": str(r.get("hops", 0)), "kind": r["kind"], "fog": r["fog"],
                         "hard": str(bool(r.get("hard"))), "hinglish": str(bool(r.get("hinglish"))), "group": r.get("group")}
        items.append(it)
    keys = {k for it in items for k in it if k.startswith("fail_")}
    for it in items:
        for k in keys:
            it.setdefault(k, 0)
    return summarize(items, ["reasoning_type", "hops", "kind", "fog", "hard", "hinglish", "group"])


def summarize(items, slices):
    out = {"all": agg([{k: v for k, v in i.items() if k != "_slices"} for i in items])}
    for s in slices:
        g = collections.defaultdict(list)
        for i in items:
            g[i["_slices"][s]].append({k: v for k, v in i.items() if k != "_slices"})
        out["by_" + s] = {k: agg(v) for k, v in sorted(g.items())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=("inc", "chat"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--rows", default=os.path.join(FINAL, "test_inc_r4.jsonl"))
    ap.add_argument("--records", default=os.path.join(FINAL, "test_chat_r4.jsonl"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    res = score_inc(a) if a.part == "inc" else score_chat(a)
    txt = json.dumps(res, indent=1)
    if a.json:
        open(a.json, "w").write(txt)
    print(json.dumps(res["all"]))
    for k, v in res.items():
        if k.startswith("by_reasoning_type") or k.startswith("by_hops"):
            print(k, json.dumps({kk: {x: vv.get(x) for x in ("n", "severity", "label", "root_domain_ok", "think_ok_multi", "pass", "reasoning_ok") if x in vv}
                                 for kk, vv in v.items()}))


if __name__ == "__main__":
    main()
