"""rsn_v3 dev mix (always) and chat selection (when bundle B is present). Incident rows stay in their own file (bundle A).
dev (loss only, never trained on): --dev-n incident dev rows + --dev-n chat3 dev rows (gold transcript + reference answer)
  -> dev_mix3.jsonl
chat (--chat given): rows from the distilled file so that chat is --chat-frac of all training rows (first one row per question,
  distilled preferred over reference rows, then the second sample of each question); fewer available -> all of them
  -> chat_mix3.jsonl
  python build_mix3.py --inc incidents3_train.jsonl --inc-dev incidents_dev60.jsonl --chat-dev chat3_dev.jsonl --out-dir DIR
                       [--chat chat3_distilled.jsonl] [--target-only]"""
import argparse
import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chatloop as CL  # noqa: E402

REQ = {"id", "tools", "messages"}


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def target(n_inc, frac):
    return int(round(n_inc * frac / (1 - frac)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inc", required=True)
    ap.add_argument("--chat", default="")
    ap.add_argument("--inc-dev", default="")
    ap.add_argument("--chat-dev", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--chat-frac", type=float, default=0.375)
    ap.add_argument("--dev-n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=303)
    ap.add_argument("--target-only", action="store_true", help="print the planned chat row count and exit")
    ap.add_argument("--replay", default="", help="general replay rows (tools none, base-model answers): all appended to chat_mix3")
    ap.add_argument("--replay-max", type=int, default=1200)
    a = ap.parse_args()
    n_inc = sum(1 for _ in open(a.inc, encoding="utf-8"))
    tg = target(n_inc, a.chat_frac)
    if a.target_only:
        print(tg)
        return
    R = random.Random(a.seed)
    os.makedirs(a.out_dir, exist_ok=True)
    msgs = []
    if a.inc_dev and a.chat_dev and not os.path.exists(os.path.join(a.out_dir, "dev_mix3.jsonl")):
        dev = []
        for r in load(a.inc_dev)[:a.dev_n]:
            r["think"] = False
            dev.append(r)
        cd = load(a.chat_dev)
        R.shuffle(cd)
        for rec in cd[:a.dev_n]:
            dev.append({"id": rec["id"], "family": "chat3:" + rec["kind"], "tools": "chat", "think": True, "hard": rec.get("hard"),
                        "source": "reference", "messages": CL.gold_messages(rec)})
        with open(os.path.join(a.out_dir, "dev_mix3.jsonl"), "w", encoding="utf-8") as f:
            for r in dev:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        msgs.append("dev %d rows" % len(dev))
    if a.chat:
        chat = load(a.chat)
        bad = [r.get("id") for r in chat if not REQ <= set(r)]
        assert not bad, "chat rows without id/tools/messages: %s" % bad[:5]
        chat = [r for r in chat if r["tools"] == "chat"]
        pref = {"distill": 0, "distill_long": 1, "reference": 2}
        byq = collections.defaultdict(list)
        for r in chat:
            r["think"] = True
            byq[r.get("question_id") or r["id"].rsplit("-", 1)[0]].append(r)
        first, second = [], []
        for q in sorted(byq):
            rs = sorted(byq[q], key=lambda r: (pref.get(r.get("source"), 3), r["id"]))
            first.append(rs[0])
            second += rs[1:]
        R.shuffle(first)
        R.shuffle(second)
        pick = (first + second)[:tg]
        nrep = 0
        if a.replay and os.path.exists(a.replay):
            rep = [dict(r, think=False, tools="none") for r in load(a.replay)][:a.replay_max]
            nrep = len(rep)
            pick = pick + rep
            R.shuffle(pick)
        with open(os.path.join(a.out_dir, "chat_mix3.jsonl"), "w", encoding="utf-8") as f:
            for r in pick:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        src = collections.Counter(r.get("source") for r in pick)
        msgs.append("replay %d rows; " % nrep + "chat %d rows (target %d = %.3f of %d incident rows; %d questions; hard %d; %s)" % (
            len(pick) - nrep, tg, a.chat_frac, n_inc, len(byq), sum(1 for r in pick if r.get("hard")), dict(src)))
    msg = "mix3: " + "; ".join(msgs or ["nothing to do"])
    with open(os.path.join(a.out_dir, "mix3.txt"), "a") as f:
        f.write(msg + "\n")
    print(msg)


if __name__ == "__main__":
    main()
