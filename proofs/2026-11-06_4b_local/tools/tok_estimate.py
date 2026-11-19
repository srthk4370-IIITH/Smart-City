"""Tokens per epoch of dataset r3: 800-row random samples of each training file rendered with the Qwen3.5-4B chat template
(tools from tools_r3.json by the row's "tools" key, thinking as the row says), mean x rows. CPU only.
  ~/venvs/rsn/bin/python tok_estimate.py  -> ../data/final/tokens_r3.json
"""
import getpass
import json
import os
import random

from transformers import AutoTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
FINAL = os.path.join(HERE, "..", "data", "final")
tok = AutoTokenizer.from_pretrained("/home/%s/models/qwen3.5-4b" % getpass.getuser())
tools = json.load(open(os.path.join(FINAL, "tools_r3.json"), encoding="utf-8"))
out = {}
for name in ("chat_train_r3.jsonl", "incidents_train.jsonl"):
    rows = [l for l in open(os.path.join(FINAL, name), encoding="utf-8")]
    R = random.Random(7)
    samp = [json.loads(l) for l in R.sample(rows, min(800, len(rows)))]
    ns = []
    for r in samp:
        t = tools.get(r.get("tools")) if r.get("tools") not in (None, "none") else None
        txt = tok.apply_chat_template(r["messages"], tools=t, tokenize=False, enable_thinking=bool(r.get("think")))
        ns.append(len(tok(txt)["input_ids"]))
    mean = sum(ns) / len(ns)
    out[name] = {"rows": len(rows), "sample": len(ns), "mean_tokens": round(mean), "max_tokens": max(ns), "epoch_tokens_M": round(mean * len(rows) / 1e6, 1)}
    print(name, out[name])
out["total_epoch_tokens_M"] = round(sum(v["epoch_tokens_M"] for v in out.values()), 1)
json.dump(out, open(os.path.join(FINAL, "tokens_r3.json"), "w"), indent=1)
print(out["total_epoch_tokens_M"])
