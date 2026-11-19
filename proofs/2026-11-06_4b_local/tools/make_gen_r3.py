"""Generation-eval records for train_rsn3.py (--gen-chat / --gen-train-chat) on dataset r3.

gen_chat_r3.jsonl        60 fresh records (gen_chat_r3 seed 2611, train phrasings): 40 new fog/cross-domain kinds + 20 rsn_v3
                         device kinds, fog online/offline/timeout, ~1/4 Hinglish; none of their sessions or last questions
                         is in chat_train_r3 / chat_test_r3 / dev_r3 (or chat dev v3 / chat_test_r2); reference passes.
gen_train_chat_r3.jsonl  20 records whose rows ARE in chat_train_r3 (build/records/train.jsonl ids), for the train/dev gap.
Record format = gen_chat_v3 records + fog, last_sync, since (verified with tools_r3_impl.ToolsR3 in that fog state).
  python3 make_gen_r3.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_r3 as BR  # noqa: E402
import gen_chat_r3 as GR  # noqa: E402
import tools_r3_impl as TR  # noqa: E402

B2, CL = BR.B2, BR.CL
FINAL = BR.FINAL


def main():
    R = random.Random(2611)
    exs = {s: TR.ToolsR3(fog=s) for s in ("online", "offline", "timeout")}

    def ex_for(rec):
        e = exs[rec["fog"]]
        e.last_sync = rec.get("last_sync")
        return e
    ban_q, ban_last = set(), set()
    for fn in ("chat_train_r3.jsonl", "chat_test_r3.jsonl", "dev_r3.jsonl", "chat_test_r2.jsonl"):
        for l in open(os.path.join(FINAL, fn), encoding="utf-8"):
            r = json.loads(l)
            if r.get("tools") == "none" or r["messages"][0]["role"] != "system":
                continue
            m = CL.prompt_messages(r) if "gold_calls" in r else r["messages"][:B2.last_user_idx(r["messages"]) + 1]
            ban_q.add(B2.qkey(m))
            ban_last.add(B2.norm(m[-1]["content"]))
    for l in open(os.path.join(BR.V3, "data", "chat3_dev.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        ban_last.add(B2.norm(CL.prompt_messages(r)[-1]["content"]))
    cand = GR.make(exs, "train", 400, 200, 2611)
    R.shuffle(cand)
    out, need = [], {"new": 40, "old": 20}
    for rec in cand:
        if need[rec["group"]] == 0:
            continue
        m = CL.prompt_messages(rec)
        if B2.qkey(m) in ban_q or B2.norm(m[-1]["content"]) in ban_last:
            continue
        rec["hinglish"] = False
        if R.random() < 0.25:
            h = B2.hinglish(R, m[-1]["content"])
            if h and B2.norm(h) not in ban_last:
                r2 = B2.with_question(rec, h)
                if BR.build_row(r2, ex_for(r2))[0] is not None:
                    rec, rec["hinglish"] = r2, True
        if BR.build_row(rec, ex_for(rec))[0] is None:
            continue
        rec["id"] = rec["id"].replace("r3-train", "gen-r3")
        out.append(rec)
        need[rec["group"]] -= 1
        ban_last.add(B2.norm(CL.prompt_messages(rec)[-1]["content"]))
    tr_ids = {json.loads(l)["id"] for l in open(os.path.join(FINAL, "chat_train_r3.jsonl"), encoding="utf-8")}
    recs = [json.loads(l) for l in open(os.path.join(HERE, "..", "build", "records", "train.jsonl"), encoding="utf-8")]
    recs = [r for r in recs if r["id"] in tr_ids]
    R.shuffle(recs)
    gtrain = []
    for rec in recs:
        if len(gtrain) >= 20:
            break
        if sum(1 for r in gtrain if r["group"] == "new") >= 13 and rec["group"] == "new":
            continue
        rec["hinglish"] = False
        if BR.build_row(rec, ex_for(rec))[0] is not None:
            gtrain.append(rec)
    for name, rows in (("gen_chat_r3.jsonl", out), ("gen_train_chat_r3.jsonl", gtrain)):
        with open(os.path.join(FINAL, name), "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        c = {}
        for r in rows:
            k = "%s/%s" % (r["group"], r["fog"])
            c[k] = c.get(k, 0) + 1
        print(name, len(rows), c, "hinglish", sum(r["hinglish"] for r in rows))


if __name__ == "__main__":
    main()
