"""Dataset r4 (top-up of rsn_v3 4B r3): verified new rows + stratified r3 replay + held-out test/dev.

inputs : ../build/inc/{train,test,dev}.jsonl (gen_r4_inc.py) + ../build/inc/go_{train,test,dev}.jsonl (app Go gate results)
         ../build/records/{train,test,dev}.jsonl (gen_chat_r4.py, r4 store)
         r3 final data (replay source): proofs/2026-11-06_4b_local/data/final/{incidents_train,chat_train_r3}.jsonl
outputs: ../data/final/train_new.jsonl, replay.jsonl, dev_gen_inc.jsonl, dev_gen_chat.jsonl, test_inc_r4.jsonl, test_chat_r4.jsonl,
         tools_r3.json (copy), build_manifest.json
chat rows: every record's gold calls re-executed on the r4 store in its fog state and verify_chat.verify-ed exactly as build_r3
(grounded numbers/ids/dates/units, gold facts, refusals, think rules); hard -> short numberless plan think, easy -> empty think.
incident rows: verify.py check_incident + think checks (gen_r4_inc) + the app's Go gate (checkReportV3For).
replay: r3 training rows, stratified by family (incidents) and by family/source (chat); incidents whose FLAGGED sensors span 2+
domains get a short templated think (the r4 rule), the rest keep the empty think.
dedup: no new train row (incident user prompt / chat session or last question) is in RWH, RWH-2, round-1 dev, incidents_test_r2,
incidents_dev60, chat dev v3, chat_test_r2, chat_test_r3, or the new test/dev.
  python3 build_r4.py [--replay-inc 7500] [--replay-chat 7500]
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
import gen_chat_r4 as GC  # noqa: E402
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
R3 = os.path.join(QIDK, "proofs", "2026-11-06_4b_local")
sys.path.insert(0, os.path.join(R3, "tools"))
import build_r3 as BR  # noqa: E402  (VC.DEFAULTS r3 update, build_row, rationale)
import check_schema_r3 as CS  # noqa: E402
B2, CL, VC = BR.B2, BR.CL, BR.VC
sys.path.insert(0, os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "pipeline"))
import lib as L  # noqa: E402

BUILD = os.path.join(HERE, "..", "build")
FINAL = os.path.join(HERE, "..", "data", "final")
BR.WHY.update({"x_relation": "Get the record and what happened around it: ",
               "x_who": "Find the cause-effect order around it: ", "x_severe": "Compare both records: ", "x_direct": "Find the nearest cause in two hours: ",
               "x_trans": "Look for a path through a middle incident: ", "x_three": "Link the three by cause and time: ",
               "x_chain": "Follow causes forward for two hours: ", "x_max": "Find the root with the most effects: ", "x_fu_links": "Cross-domain check: "})
_RAT = BR.rationale


def rationale_r4(rec):
    s = _RAT(rec)
    if rec["kind"].startswith("x_"):
        s = s.replace(" then answer from the result and name its source.", " then link them by label, building and time order.").replace(
            " then answer from the results.", " then link them by label, building and time order.")
    return s


BR.rationale = rationale_r4
DW = {"air_quality": "air quality", "water": "water", "power": "power", "weather": "weather", "occupancy": "occupancy", "hvac": "HVAC"}
FLAG_RX = re.compile(r"^(S\d+) \[FLAGGED\]: \S+ (\w+) \[[^\]]*\] at .* \((\w+)\)$", re.M)


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def write(p, rows):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def replay_think(r):
    """templated think for an r3 incident row whose flagged sensors span 2+ domains (numbers: none)"""
    u = r["messages"][1]["content"]
    fl = FLAG_RX.findall(u)
    doms = []
    for _, _, d in fl:
        if d not in doms:
            doms.append(d)
    if len(doms) < 2:
        return None
    rep = json.loads(r["messages"][-1]["content"])
    parts = ", ".join("%s %s" % (ref, L.word(role, m)) for ref, m, role in fl[:3])
    v = {"critical": "critical", "warning": "warning", "normal": "no action beyond monitoring", "sensor_fault": "a sensor fault"}[rep["severity"]]
    sus = (" Suspect: %s." % ", ".join(rep["suspect_sensors"][:2])) if rep.get("suspect_sensors") else ""
    return "Flagged in %s: %s. Check one shared cause, a chain, or separate events against the evidence.%s Verdict: %s, %s." % (
        " and ".join(DW.get(d, d) for d in doms[:3]), parts, sus, G_lab(rep["label"]), v)


def G_lab(x):
    return x.replace("_", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-inc", type=int, default=7500)
    ap.add_argument("--replay-chat", type=int, default=7500)
    ap.add_argument("--hinglish", type=float, default=0.2)
    ap.add_argument("--test-hinglish", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=1112)
    a = ap.parse_args()
    R = random.Random(a.seed)
    os.makedirs(FINAL, exist_ok=True)
    st = collections.Counter()
    # ------------------------------------------------ ban sets (gate/test/dev sets)
    V3 = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3")
    inc_sets = {"rwh": os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "data", "incidents_rwh.ok.jsonl"),
                "rwh2": os.path.join(V3, "kaggle", "build", "r1", "heldout", "incidents_rwh2.jsonl"),
                "dev_r1": os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final", "data", "incidents_dev.ok.jsonl"),
                "test_r2": os.path.join(R3, "data", "final", "incidents_test_r2.jsonl"), "dev60": os.path.join(R3, "data", "final", "incidents_dev60.jsonl")}
    ban_inc = set()
    for k, p in inc_sets.items():
        rs = load(p)
        st["ban_inc_" + k] = len(rs)
        ban_inc |= {r["messages"][1]["content"] for r in rs}
    chat_sets = {"chatdev3": os.path.join(V3, "data", "chat3_dev.jsonl"), "chat_test_r2": os.path.join(R3, "data", "final", "chat_test_r2.jsonl"),
                 "chat_test_r3": os.path.join(R3, "data", "final", "chat_test_r3.jsonl")}
    ban_q, ban_last = set(), set()
    for k, p in chat_sets.items():
        rs = load(p)
        st["ban_chat_" + k] = len(rs)
        ban_q |= {B2.qkey(CL.prompt_messages(r)) for r in rs}
        ban_last |= {B2.norm(CL.prompt_messages(r)[-1]["content"]) for r in rs}
    # ------------------------------------------------ incidents (Go gate filtered)
    inc = {}
    for sp in ("train", "test", "dev"):
        rows = load(os.path.join(BUILD, "inc", sp + ".jsonl"))
        gate = {g["id"]: g for g in load(os.path.join(BUILD, "inc", "go_%s.jsonl" % sp))}
        ok = [r for r in rows if gate.get(r["id"], {}).get("pass")]
        st["inc_%s_gen" % sp], st["inc_%s_go_pass" % sp] = len(rows), len(ok)
        inc[sp] = ok
    test_inc_prompts = {r["messages"][1]["content"] for r in inc["test"] + inc["dev"]}
    n0 = len(inc["train"])
    inc["train"] = [r for r in inc["train"] if r["messages"][1]["content"] not in ban_inc and r["messages"][1]["content"] not in test_inc_prompts]
    st["inc_train_drop_overlap"] = n0 - len(inc["train"])
    for r in inc["test"] + inc["dev"]:
        assert r["messages"][1]["content"] not in ban_inc
    # ------------------------------------------------ chat
    exs = GC.tools_r4()

    def ex_for(rec):
        e = exs[rec["fog"]]
        e.last_sync = rec.get("last_sync")
        return e

    def keep_fields(rec):
        return {k: rec[k] for k in ("reasoning_type", "hops", "answer_key") if k in rec}
    chat_test, chat_dev = [], []
    for sp, out, hp in (("test", chat_test, a.test_hinglish), ("dev", chat_dev, 0.2)):
        for rec in load(os.path.join(BUILD, "records", sp + ".jsonl")):
            if B2.norm(CL.prompt_messages(rec)[-1]["content"]) in ban_last:
                st["chat_%s_drop_gate" % sp] += 1
                continue
            ex = ex_for(rec)
            rec["hinglish"] = False
            if R.random() < hp:
                h = B2.hinglish(R, CL.prompt_messages(rec)[-1]["content"])
                if h:
                    rec2 = B2.with_question(rec, h)
                    if BR.build_row(rec2, ex)[0] is not None:
                        rec, rec["hinglish"] = rec2, True
            if BR.build_row(rec, ex)[0] is None:
                st["chat_%s_ref_fail" % sp] += 1
                continue
            rec["id"] = rec["id"].replace("r4-dev", "chat-%s-r4" % sp)
            rec["gold_text"] = {"answer": rec["reference_answer"]}
            out.append(rec)
    ban_last |= {B2.norm(CL.prompt_messages(r)[-1]["content"]) for r in chat_test + chat_dev}
    ban_q |= {B2.qkey(CL.prompt_messages(r)) for r in chat_test + chat_dev}
    chat_rows, reasons = [], collections.Counter()
    for rec in load(os.path.join(BUILD, "records", "train.jsonl")):
        if B2.qkey(CL.prompt_messages(rec)) in ban_q or B2.norm(CL.prompt_messages(rec)[-1]["content"]) in ban_last:
            st["chat_new_drop_overlap"] += 1
            continue
        ex = ex_for(rec)
        hing = False
        if R.random() < a.hinglish:
            h = B2.hinglish(R, CL.prompt_messages(rec)[-1]["content"])
            if h and B2.norm(h) not in ban_last:
                rec2 = B2.with_question(rec, h)
                if BR.build_row(rec2, ex)[0] is not None:
                    rec, hing = rec2, True
        new, why = BR.build_row(rec, ex)
        st["chat_checked"] += 1
        if new is None:
            reasons[(rec["kind"], why)] += 1
            continue
        row = {"id": rec["id"] + ("-h" if hing else ""), "family": "r4:" + rec["kind"] + ("+hinglish" if hing else ""), "tools": "chat", "think": True,
               "hard": bool(rec.get("hard")), "source": why, "fog": rec["fog"], "group": rec["group"], "r4_src": "new_" + rec["group"],
               "messages": CL.prompt_messages(rec) + new}
        row.update(keep_fields(rec))
        if not CS.row_ok(row):
            st["chat_schema_bad"] += 1
            continue
        chat_rows.append(row)
        st["chat_hinglish"] += hing
    st["chat_pass"] = len(chat_rows)
    # ------------------------------------------------ new train (incidents + chat)
    inc_rows = []
    for r in inc["train"]:
        r = dict(r)
        r["r4_src"] = "new_inc"
        r.pop("pair", None)
        inc_rows.append(r)
    train_new = inc_rows + chat_rows
    R.shuffle(train_new)
    # ------------------------------------------------ replay (stratified)
    rep = []

    def stream_sample(path, keyf, n_total):
        """two streaming passes (RAM): stratum sizes, then the sampled line numbers"""
        by = collections.defaultdict(list)
        with open(path, encoding="utf-8") as f:
            for i, l in enumerate(f):
                by[keyf(json.loads(l))].append(i)
        tot = sum(len(v) for v in by.values())
        pick = set()
        for k, v in sorted(by.items(), key=lambda z: str(z[0])):
            pick |= set(R.sample(v, min(len(v), max(1, round(n_total * len(v) / tot)))))
        with open(path, encoding="utf-8") as f:
            for i, l in enumerate(f):
                if i in pick:
                    yield json.loads(l)
    for r in stream_sample(os.path.join(R3, "data", "final", "incidents_train.jsonl"), lambda r: r["family"].split("+")[0], a.replay_inc):
        if True:
            t = replay_think(r)
            if t and VC.think_tokens(t) > VC.THINK_MAX:
                t = re.sub(r" Check one shared cause.*?evidence\.", "", t)
            if t:
                r["think"] = True
                r["messages"][-1]["reasoning_content"] = t
                st["replay_inc_think"] += 1
            r["r4_src"] = "replay_inc"
            r["reasoning_type"], r["hops"] = "none", 0
            rep.append(r)
    for r in stream_sample(os.path.join(R3, "data", "final", "chat_train_r3.jsonl"), lambda r: (r.get("r3_src", "?"), r.get("family", "").split("+")[0]),
                           a.replay_chat):
        rep.append(dict(r, r4_src="replay_chat", reasoning_type="none", hops=0))
    rep = [r for r in rep if not (r.get("tools") == "incident" and r["messages"][1]["content"] in test_inc_prompts)]
    R.shuffle(rep)
    # ------------------------------------------------ test/dev files
    for r in inc["test"] + inc["dev"]:
        r.pop("pair", None)
        r["think_expected"] = bool(r["think"])
    write(os.path.join(FINAL, "train_new.jsonl"), train_new)
    write(os.path.join(FINAL, "replay.jsonl"), rep)
    write(os.path.join(FINAL, "test_inc_r4.jsonl"), inc["test"])
    write(os.path.join(FINAL, "test_chat_r4.jsonl"), chat_test)
    write(os.path.join(FINAL, "dev_gen_inc.jsonl"), inc["dev"])
    write(os.path.join(FINAL, "dev_gen_chat.jsonl"), chat_dev)
    shutil.copyfile(os.path.join(R3, "data", "final", "tools_r3.json"), os.path.join(FINAL, "tools_r3.json"))
    comp = collections.Counter()
    for r in train_new:
        comp["kind:%s" % ("incident" if r["tools"] == "incident" else "chat")] += 1
        comp["rtype:%s:%s" % ("inc" if r["tools"] == "incident" else "chat", r.get("reasoning_type", "none"))] += 1
        if r["tools"] == "incident":
            comp["inc_think:%s" % bool(r.get("think"))] += 1
            comp["inc_fam:" + r["family"].split("+")[0]] += 1
            comp["inc_hops:%s" % r.get("hops")] += 1
        else:
            comp["chat_fog:%s" % r["fog"]] += 1
            comp["chat_%s" % ("hard" if r["hard"] else "easy")] += 1
            comp["chat_kind:" + r["family"].split("+")[0]] += 1
    tcomp = collections.Counter()
    for r in inc["test"]:
        tcomp["inc_rtype:" + r["reasoning_type"]] += 1
        tcomp["inc_think:%s" % r["think"]] += 1
        tcomp["inc_hops:%s" % r["hops"]] += 1
    for r in chat_test:
        tcomp["chat_rtype:" + r["reasoning_type"]] += 1
        tcomp["chat_fog:" + r["fog"]] += 1
        tcomp["chat_kind:" + r["kind"]] += 1
    rcomp = collections.Counter(("inc" if r.get("tools") == "incident" else "chat") + ":" + str(bool(r.get("think")) if r.get("tools") == "incident" else r.get("tools")) for r in rep)
    man = {"train_new": len(train_new), "replay": len(rep), "test_inc": len(inc["test"]), "test_chat": len(chat_test), "dev_inc": len(inc["dev"]),
           "dev_chat": len(chat_dev), "stats": dict(st), "train_new_composition": dict(sorted(comp.items())), "test_composition": dict(sorted(tcomp.items())),
           "replay_composition": dict(rcomp), "chat_verify_fail": {"%s:%s" % k: v for k, v in reasons.most_common(40)}, "seed": a.seed}
    json.dump(man, open(os.path.join(FINAL, "build_manifest.json"), "w"), indent=1)
    print(json.dumps({k: man[k] for k in ("train_new", "replay", "test_inc", "test_chat", "dev_inc", "dev_chat")}))
    print(json.dumps(man["stats"]))
    print("chat fails:", reasons.most_common(15))


if __name__ == "__main__":
    main()
