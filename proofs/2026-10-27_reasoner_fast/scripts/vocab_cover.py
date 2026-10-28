"""How many distinct tokens do the reasoner's answers use? (train_mix gold answers + RWH/dev gold + board outputs)"""
import json, sys, collections
from tokenizers import Tokenizer
tk = Tokenizer.from_file(sys.argv[1])
D = r"C:\Users\hp\Desktop\qidk\proofs\2026-10-25_reasoner_final\data"
def answers(p):
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        for m in r["messages"]:
            if m["role"] == "assistant" and m.get("content"):
                yield m["content"]
train = collections.Counter(); held = collections.Counter()
for t in answers(D + r"\train_mix.jsonl"): train.update(tk.encode(t, add_special_tokens=False).ids)
for f in ("incidents_dev.ok.jsonl", "incidents_rwh.ok.jsonl", "chat_dev.ok.jsonl"):
    for t in answers(D + "\\" + f): held.update(tk.encode(t, add_special_tokens=False).ids)
miss = {k: v for k, v in held.items() if k not in train}
print(f"train answers: {len(train)} distinct tokens, {sum(train.values())} total")
print(f"held-out answers: {len(held)} distinct; {len(miss)} distinct not in train ({sum(miss.values())} of {sum(held.values())} occurrences = {100*sum(miss.values())/sum(held.values()):.3f}%)")
print("examples not in train:", [tk.decode([k]) for k in list(miss)[:30]])
