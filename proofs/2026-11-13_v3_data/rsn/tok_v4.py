"""Tokens per epoch (Qwen3.5-4B chat template, tools by the row's "tools" key, thinking as the row says), 600-row samples per
(file, block). CPU only.   ~/venvs/rsn/bin/python tok_v4.py data/final  -> data/final/tokens_v4.json"""
import collections
import getpass
import json
import os
import random
import sys

from transformers import AutoTokenizer

D = sys.argv[1]
tok = AutoTokenizer.from_pretrained("/home/%s/models/qwen3.5-4b" % getpass.getuser())
tools = json.load(open(os.path.join(D, "tools_v4.json"), encoding="utf-8"))
out = {}
for name in ("train_new.jsonl", "replay.jsonl"):
    by = collections.defaultdict(list)
    for l in open(os.path.join(D, name), encoding="utf-8"):
        r = json.loads(l)
        by[r.get("block", r.get("tools"))].append(r)
    for b, rs in sorted(by.items()):
        samp = random.Random(7).sample(rs, min(600, len(rs)))
        ns = []
        for r in samp:
            t = tools.get(r.get("tools"))
            msgs = []
            for m in r["messages"]:
                m = dict(m)
                for tc in m.get("tool_calls") or []:
                    if isinstance(tc["function"]["arguments"], str):
                        tc["function"]["arguments"] = json.loads(tc["function"]["arguments"])
                msgs.append(m)
            txt = tok.apply_chat_template(msgs, tools=t, tokenize=False, enable_thinking=bool(r.get("think", True)))
            ns.append(len(tok(txt)["input_ids"]))
        mean = sum(ns) / len(ns)
        out["%s:%s" % (name, b)] = {"rows": len(rs), "sample": len(ns), "mean_tokens": round(mean), "max_tokens": max(ns),
                                    "epoch_tokens_M": round(mean * len(rs) / 1e6, 2)}
        print(name, b, out["%s:%s" % (name, b)], flush=True)
out["total_epoch_tokens_M"] = round(sum(v["epoch_tokens_M"] for v in out.values()), 2)
json.dump(out, open(os.path.join(D, "tokens_v4.json"), "w"), indent=1)
print(out["total_epoch_tokens_M"])
