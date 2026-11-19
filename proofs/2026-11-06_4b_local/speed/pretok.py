"""tokenize the test rows ONCE (trainer's encode, real tokenizer, tools_r3) -> rows.pt, so the equivalence runs do not load the
tokenizer. Ids are remapped to a compact vocabulary (order-preserving map of the ids that occur): identical sequences, identical
common prefixes and label positions, but a tiny embedding/lm_head (host RAM). usage: pretok.py <trainer.py> <out.pt>"""
import importlib.util
import json
import os
import sys

import torch

spec = importlib.util.spec_from_file_location("tr", sys.argv[1])
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
from transformers import AutoTokenizer  # noqa: E402

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "final")
tok = AutoTokenizer.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b"))
tools = json.load(open(os.path.join(D, "tools_r3.json"), encoding="utf-8"))
rows = []
for f, n in (("incidents_train.jsonl", 14), ("chat_train_r3.jsonl", 10)):
    k = 0
    for line in open(os.path.join(D, f), encoding="utf-8"):
        if k >= n:
            break
        ex = json.loads(line)
        r, why = T.encode(tok, ex, tools.get(ex["tools"]), 10 ** 6)
        if r is None:
            continue
        rows.append({"id": ex["id"], "kind": ex["tools"], "line": line, "ids": torch.tensor(r[0]), "labels": torch.tensor(r[1])})
        k += 1
vocab = torch.unique(torch.cat([r["ids"] for r in rows]))
remap = torch.full((int(vocab.max()) + 1,), -1, dtype=torch.long)
remap[vocab] = torch.arange(len(vocab))
for r in rows:
    r["ids"] = remap[r["ids"]].to(torch.int32)
    r["labels"] = torch.where(r["labels"] == -100, torch.tensor(-100), remap[r["labels"].clamp_min(0)]).to(torch.int32)
torch.save({"rows": rows, "vocab": vocab}, sys.argv[2])
print(len(rows), "rows,", len(vocab), "distinct ids;", [(r["kind"], len(r["ids"])) for r in rows])
