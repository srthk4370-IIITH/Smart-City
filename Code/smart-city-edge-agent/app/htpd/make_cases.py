#!/usr/bin/env python3
"""Corpus for test_logic.cpp: every v2 device output (proofs/2026-10-20_v2_post/device) as
{"src","id","stop","sys","text"}, text = generation after the agent prefill, sys = the prompt's system turn
(placement_v2 only; host400/test_all have no prompts saved, so sys is empty and only the stop-rule checks run).

usage: python3 make_cases.py [out.jsonl]
"""
import json, sys
from pathlib import Path

D = Path(__file__).resolve().parents[4] / "proofs/2026-10-20_v2_post/device"
PRE = '{"pattern": "'
out = open(sys.argv[1] if len(sys.argv) > 1 else "cases.jsonl", "w")
n = 0
for sub in ("placement_v2", "host400", "test_all"):
    prompts = {}
    if (D / sub / "prompts.jsonl").exists():
        prompts = {(r["id"], r.get("d")): r["prompt"] for r in map(json.loads, open(D / sub / "prompts.jsonl", encoding="utf-8"))}
    for line in open(D / sub / "samples.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if not r["text"].startswith(PRE):
            continue
        p = prompts.get((r["id"], r.get("d")), "")
        out.write(json.dumps({"src": sub, "id": r.get("id"), "stop": r.get("stop"), "sys": p.split("<|eot_id|>")[0],
                              "text": r["text"][len(PRE):]}) + "\n")
        n += 1
print(n, "cases")
