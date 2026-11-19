"""Tokens per epoch of dataset r4 (train_new + replay): 800-row samples per file and per kind (incident / chat), rendered with the
Qwen3.5-4B chat template (tools by the row's "tools" key, thinking as the row says). CPU only.
  ~/venvs/rsn/bin/python tok_r4.py  -> ../data/final/tokens_r4.json
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
for name in ("train_new.jsonl", "replay.jsonl"):
    rows = [json.loads(l) for l in open(os.path.join(FINAL, name), encoding="utf-8")]
    for kind in ("incident", "chat"):
        rs = [r for r in rows if (r.get("tools") == "incident") == (kind == "incident")]
        if not rs:
            continue
        R = random.Random(7)
        samp = R.sample(rs, min(800, len(rs)))
        ns = []
        for r in samp:
            t = tools.get(r.get("tools")) if r.get("tools") not in (None, "none") else None
            txt = tok.apply_chat_template(r["messages"], tools=t, tokenize=False, enable_thinking=bool(r.get("think")))
            ns.append(len(tok(txt)["input_ids"]))
        mean = sum(ns) / len(ns)
        out["%s:%s" % (name, kind)] = {"rows": len(rs), "sample": len(ns), "mean_tokens": round(mean), "max_tokens": max(ns),
                                       "epoch_tokens_M": round(mean * len(rs) / 1e6, 1)}
        print(name, kind, out["%s:%s" % (name, kind)], flush=True)
out["total_epoch_tokens_M"] = round(sum(v["epoch_tokens_M"] for v in out.values()), 1)
json.dump(out, open(os.path.join(FINAL, "tokens_r4.json"), "w"), indent=1)
print(out["total_epoch_tokens_M"])
