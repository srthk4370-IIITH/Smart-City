"""Final training/dev mixes from the verified (.ok) files. Chat: at most 2 examples per identical question.
Tool-call arguments are stored as dicts (the Qwen template needs mappings). -> data/train_mix.jsonl, data/dev_mix.jsonl"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prompts import SYSTEM_INCIDENT_SHORT  # noqa: E402

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def load(n):
    return [json.loads(l) for l in open(os.path.join(D, n), encoding="utf-8")]


def fix(ex):
    if ex["tools"] == "incident":
        ex["messages"][0]["content"] = SYSTEM_INCIDENT_SHORT
    for m in ex["messages"]:
        for tc in m.get("tool_calls") or []:
            a = tc["function"]["arguments"]
            if isinstance(a, str):
                tc["function"]["arguments"] = json.loads(a)
    return {"id": ex["id"], "family": ex["family"], "tools": ex["tools"], "messages": ex["messages"]}


def main():
    R = random.Random(5)
    out = {}
    for split, inc, chat in (("train", "incidents_train.ok.jsonl", "chat_train.ok.jsonl"), ("dev", "incidents_dev.ok.jsonl", "chat_dev.ok.jsonl")):
        rows = load(inc)
        cnt = collections.Counter()
        for ex in load(chat):
            q = ex["messages"][1]["content"]
            if cnt[q] < 2:
                cnt[q] += 1
                rows.append(ex)
        rows = [fix(r) for r in rows]
        R.shuffle(rows)
        with open(os.path.join(D, "%s_mix.jsonl" % split), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        fam = collections.Counter(r["family"].split(":")[0].split("+")[0] for r in rows)
        out[split] = (len(rows), sum(1 for r in rows if r["tools"] == "chat"))
    print("mix (total, chat):", out)


if __name__ == "__main__":
    main()
