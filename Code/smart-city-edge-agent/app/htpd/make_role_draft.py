#!/usr/bin/env python3
"""Write htpd's static per-role draft corpus (HTPD_ROLE_DRAFT_FILE) from TRAIN completions only.

One JSONL line per role: {"match": "You are the Air Quality agent", "texts": [completion, ...]}.
htpd picks the first entry whose "match" occurs in a prompt and builds an n-gram (1..3 tokens) ->
most-frequent-next-token table from the texts, used as a verified draft source (outputs cannot change).
Same sampling as proofs/2026-10-21_v2_research/latency/sim_draft.py (seed 7, p=0.12, <= 1500 per role).

usage: python3 make_role_draft.py [train.jsonl] [out.jsonl]
"""
import json, random, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/sft_v2/train.jsonl"
dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("role_draft_v2.jsonl")
PREFILL = '{"pattern": "'

random.seed(7)
texts, match = defaultdict(list), {}
for line in open(src, encoding="utf-8"):
    if random.random() > 0.12:
        continue
    r = json.loads(line)
    if r.get("split", "train") != "train":
        continue
    role = r["role"]
    m = re.search(r"You are the [A-Za-z ]+? agent", r["prompt"])
    if m:
        match.setdefault(role, m.group(0))
    if len(texts[role]) < 1500:
        c = r["completion"]
        texts[role].append(c[len(PREFILL):] if c.startswith(PREFILL) else c)
with open(dst, "w", encoding="utf-8") as f:
    for role in sorted(texts):
        if role in match:
            f.write(json.dumps({"role": role, "match": match[role], "texts": texts[role]}) + "\n")
            print(role, match[role], len(texts[role]))
print("wrote", dst)
