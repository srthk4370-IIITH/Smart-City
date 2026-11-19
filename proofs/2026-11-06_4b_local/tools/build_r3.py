"""Dataset r3 (rsn_v3 4B local): verified training rows + test/dev files.

chat rows
  * new: records of gen_chat_r3.py (train phrasings). Each record's gold calls are re-executed on the r3 store in the record's
    fog state (tools_r3_impl.ToolsR3) and the row (gold calls + results + reference answer) must pass verify_chat.verify
    (schema-valid executed calls, grounded numbers/ids/dates/units, gold facts, refusals, think rules). Hard records get a
    short numberless plan think (the plan names the calls, never a result), easy ones an empty think.
    --hinglish of them are rewritten to Hinglish/code-switched (build_chat_r2.hinglish) and re-verified.
  * r2: proofs/2026-11-02_2b_r2/data/final/chat_train.jsonl re-rendered with the r3 prompt: tools "chat" (tools_r3.json,
    21 tools), system = r3 rules + the offline fog sentence (their world: rsn_v3 store, no fog, full records since 2026-01-01).
    Dropped: the kinds the r3 tools replace (offline_docs, fog_knowledge, old_data, history_old, compare_periods) and every
    row that calls search_knowledge. Replay rows (general, no tools) kept as they are.
  * dedup: no row whose session (normalised user side) or last question occurs in chat dev v3 (gate), chat_test_r2 or the
    r3 test set.
incident rows: r2 incidents_train.jsonl unchanged (tools "incident" is identical in tools_r3.json).
outputs (data/final): chat_train_r3.jsonl, incidents_train.jsonl, chat_test_r3.jsonl (records), dev_r3.jsonl (loss-only),
  incidents_test_r2.jsonl, incidents_dev60.jsonl, chat_test_r2.jsonl (copied), build_manifest.json
  python3 build_r3.py
"""
import argparse
import collections
import copy
import json
import os
import random
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tools_r3_impl as TR  # noqa: E402
import gen_chat_r3 as GR  # noqa: E402
import check_schema_r3 as CS  # noqa: E402
QIDK = TR.QIDK
R2 = os.path.join(QIDK, "proofs", "2026-11-02_2b_r2")
V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
sys.path.insert(0, os.path.join(R2, "tools"))
sys.path.insert(0, os.path.join(V3, "distill_laptop"))
import build_chat_r2 as B2  # noqa: E402
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402
import select_distill as SD  # noqa: E402

VC.DEFAULTS.update({"fog_search_history": {"limit": 5}, "fog_analytics": {"bucket": "month", "group_by": "label"},
                    "co_occurring_incidents": {"window_min": 60, "other_domains_only": True},
                    "recurring_issues": {"min_count": 3, "by": "sensor"}, "search_knowledge": {"k": 3}})
FINAL = os.path.join(HERE, "..", "data", "final")
REC = os.path.join(HERE, "..", "build", "records")
DROP_FAM = {"chat3:" + k for k in GR.DROP_OLD}
R2_SINCE = "2026-01-01"
WHY = {"fog_find_old": "Older than the device's full records: ", "fog_text": "Search all history on the fog: ", "fog_old_detail": "",
       "fog_trend": "Multi-month counts: ", "fog_resolve": "Close times over months: ", "fog_sensor_monthly": "Monthly readings: ",
       "cooccur": "Cross-domain check: ", "compare_tool": "Compare both periods: ", "recurring": "Repeated incidents: ",
       "fu_fog_detail": "Details of that incident: ", "fu_fog_period": "Same search, other month: ", "fu_fog_status": "Check the fog link: ",
       "fu_cooccur": "Cross-domain check: ", "fog_drop": "Older data: "}


def rationale(rec):
    calls = rec.get("gold_calls") or []
    if not calls:
        return "The earlier results already answer this; no new tool call is needed."
    cd = "; ".join("%s(%s)" % (c["name"], ", ".join("%s=%s" % (k, SD._short(v)) for k, v in c["args"].items())) for c in calls)
    tail = " then answer from the result and name its source." if any(c["name"] in TR.FOG_TOOLS or c["name"] == "get_incident" for c in calls) \
        else " then answer from the results."
    return WHY.get(rec["kind"], "Plan: ") + cd + ";" + tail


def build_row(rec, ex):
    ref = CL.gold_messages(rec)[len(CL.prompt_messages(rec)):]
    msgs = copy.deepcopy(ref)
    if rec.get("hard"):
        th = rationale(rec)
        if VC.think_tokens(th) > VC.THINK_MAX:
            th = re.sub(r"\(.*?\)", "()", th)
        for m in msgs:
            if m["role"] == "assistant":
                m["reasoning_content"] = th
                break
    ex.qid = 0
    v = VC.verify(rec, msgs, executor=ex)
    return (msgs, "template" if rec.get("hard") else "reference") if v["pass"] else (None, ",".join(x.split(":")[0] for x in v["reasons"]))


def r3_system_of_r2(R, content):
    """an r2 system message -> the r3 one (offline, last sync or never, full records since 2026-01-01)"""
    assert content.startswith(GR.HEAD), content[:80]
    ls = GR.last_sync_for(R)
    return GR.system_r3("offline", ls, R2_SINCE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hinglish", type=float, default=0.2)
    ap.add_argument("--test-hinglish", type=float, default=0.25)
    ap.add_argument("--dev-new", type=int, default=120)
    ap.add_argument("--seed", type=int, default=611)
    ap.add_argument("--records", default=REC)
    a = ap.parse_args()
    R = random.Random(a.seed)
    os.makedirs(FINAL, exist_ok=True)
    exs = {s: TR.ToolsR3(fog=s) for s in ("online", "offline", "timeout")}

    def ex_for(rec):
        e = exs[rec["fog"]]
        e.last_sync = rec.get("last_sync")
        return e
    st = collections.Counter()
    gate = [json.loads(l) for l in open(os.path.join(V3, "data", "chat3_dev.jsonl"), encoding="utf-8")]
    t2 = [json.loads(l) for l in open(os.path.join(R2, "data", "final", "chat_test_r2.jsonl"), encoding="utf-8")]
    ban_q = {B2.qkey(CL.prompt_messages(r)) for r in gate + t2}
    ban_last = {B2.norm(CL.prompt_messages(r)[-1]["content"]) for r in gate + t2}
    # ---- r3 test records (verified references, Hinglish share)
    test = []
    for l in open(os.path.join(a.records, "test.jsonl"), encoding="utf-8"):
        rec = json.loads(l)
        if B2.norm(CL.prompt_messages(rec)[-1]["content"]) in ban_last:
            st["test_drop_gate"] += 1
            continue
        ex = ex_for(rec)
        rec["hinglish"] = False
        if R.random() < a.test_hinglish:
            h = B2.hinglish(R, CL.prompt_messages(rec)[-1]["content"])
            if h:
                rec2 = B2.with_question(rec, h)
                if build_row(rec2, ex)[0] is not None:
                    rec, rec["hinglish"] = rec2, True
        if build_row(rec, ex)[0] is None:
            st["test_ref_fail"] += 1
            continue
        rec["id"] = rec["id"].replace("r3-dev", "chat-test-r3")
        test.append(rec)
    test_last = {B2.norm(CL.prompt_messages(r)[-1]["content"]) for r in test}
    ban_last |= test_last
    # ---- new rows
    rows, dev = [], []
    reasons = collections.Counter()
    fails_kept = collections.Counter()
    fail_f = open(os.path.join(HERE, "..", "build", "verify_fail_samples.jsonl"), "w", encoding="utf-8")
    for l in open(os.path.join(a.records, "train.jsonl"), encoding="utf-8"):
        rec = json.loads(l)
        k = B2.qkey(CL.prompt_messages(rec))
        if k in ban_q or B2.norm(CL.prompt_messages(rec)[-1]["content"]) in ban_last:
            st["new_drop_overlap"] += 1
            continue
        ex = ex_for(rec)
        hing = False
        if rec["group"] == "new" and R.random() < a.hinglish:
            h = B2.hinglish(R, CL.prompt_messages(rec)[-1]["content"])
            if h:
                rec2 = B2.with_question(rec, h)
                if B2.norm(h) not in ban_last and build_row(rec2, ex)[0] is not None:
                    rec, hing = rec2, True
                else:
                    st["hinglish_verify_fail"] += 1
        new, why = build_row(rec, ex)
        st["checked_" + rec["group"]] += 1
        if new is None:
            reasons[(rec["kind"], why)] += 1
            if fails_kept[rec["kind"]] < 3:
                fails_kept[rec["kind"]] += 1
                ex.qid = 0
                v = VC.verify(rec, CL.gold_messages(rec)[len(CL.prompt_messages(rec)):], executor=ex)
                fail_f.write(json.dumps({"kind": rec["kind"], "fog": rec["fog"], "q": CL.prompt_messages(rec)[-1]["content"],
                                         "answer": rec["reference_answer"], "reasons": v["reasons"]}, ensure_ascii=False) + "\n")
            st["fail_" + rec["group"]] += 1
            continue
        row = {"id": rec["id"] + ("-h" if hing else ""), "family": "r3:" + rec["kind"] + ("+hinglish" if hing else ""), "tools": "chat", "think": True,
               "hard": bool(rec.get("hard")), "source": why, "fog": rec["fog"], "group": rec["group"], "r3_src": "new_" + rec["group"],
               "messages": CL.prompt_messages(rec) + new}
        rows.append(row)
        st["hinglish"] += hing
    R.shuffle(rows)
    devp = [r for r in rows if r["group"] == "new"][:a.dev_new]
    dset = {r["id"] for r in devp}
    rows = [r for r in rows if r["id"] not in dset]
    dev += devp
    # ---- r2 rows re-rendered
    for l in open(os.path.join(R2, "data", "final", "chat_train.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") == "none":
            r["r3_src"] = "r2_replay"
            rows.append(r)
            st["r2_replay"] += 1
            continue
        fam = r.get("family", "").split("+")[0]
        if fam in DROP_FAM or "search_knowledge" in B2.call_names(r["messages"]):
            st["r2_drop_replaced"] += 1
            continue
        if not CS.row_ok(r):
            st["r2_drop_schema"] += 1
            continue
        lu = B2.last_user_idx(r["messages"])
        if B2.qkey(r["messages"][:lu + 1]) in ban_q or B2.norm(r["messages"][lu]["content"]) in ban_last:
            st["r2_drop_overlap"] += 1
            continue
        r["messages"][0]["content"] = r3_system_of_r2(R, r["messages"][0]["content"])
        r["tools"], r["fog"], r["r3_src"] = "chat", "offline", "r2_" + r.get("r2_src", "?")
        rows.append(r)
        st["r2_rows"] += 1
    R.shuffle(rows)
    # ---- dev (loss-only): r2 dev_mix3 chat rows re-rendered + held-out new rows
    for l in open(os.path.join(R2, "data", "final", "dev_mix3.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r.get("tools") in ("chat", "chat9") and r["messages"][0]["role"] == "system" and r["messages"][0]["content"].startswith(GR.HEAD):
            r["messages"][0]["content"] = r3_system_of_r2(R, r["messages"][0]["content"])
            r["tools"] = "chat"
        dev.append(r)
    for name, data in (("chat_train_r3.jsonl", rows), ("chat_test_r3.jsonl", test), ("dev_r3.jsonl", dev)):
        with open(os.path.join(FINAL, name), "w", encoding="utf-8", newline="\n") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for n in ("incidents_train.jsonl", "incidents_test_r2.jsonl", "incidents_dev60.jsonl", "chat_test_r2.jsonl"):
        shutil.copyfile(os.path.join(R2, "data", "final", n), os.path.join(FINAL, n))
    comp = collections.Counter()
    for r in rows:
        comp["src:" + r.get("r3_src", "?")] += 1
        if r.get("tools") == "chat":
            comp["fog:%s:%s" % (r.get("group", "r2"), r.get("fog"))] += 1
            comp["hard" if r.get("hard") else "easy"] += 1
            comp["turns:%d" % sum(1 for m in r["messages"] if m["role"] == "user")] += 1
    kinds = collections.Counter(r["family"] for r in rows if r.get("r3_src", "").startswith("new"))
    tk = collections.Counter("%s|%s" % (r["kind"], r["fog"]) for r in test)
    man = {"chat_train_rows": len(rows), "test_records": len(test), "dev_rows": len(dev), "stats": dict(st), "composition": dict(sorted(comp.items())),
           "new_kinds": dict(sorted(kinds.items())), "test_kinds_fog": dict(sorted(tk.items())),
           "test_fog": dict(collections.Counter(r["fog"] for r in test)), "test_hinglish": sum(r["hinglish"] for r in test),
           "verify_fail_reasons": {"%s:%s" % k: v for k, v in reasons.most_common(60)}, "seed": a.seed}
    json.dump(man, open(os.path.join(FINAL, "build_manifest.json"), "w"), indent=1)
    print(json.dumps({k: man[k] for k in ("chat_train_rows", "test_records", "dev_rows", "stats")}))
    print("fail reasons:", reasons.most_common(25))


if __name__ == "__main__":
    main()
