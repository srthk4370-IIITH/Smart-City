"""Do v2 prompts + outputs fit smaller per-stream contexts (e.g. 13 x 1024)?  And how long is each role's
shared system turn?  Inputs: app/backend/testdata/v2_prompt_fixtures.json (Go-parity prompts, all 6 roles,
N 24..144) and v2 device outputs (max generated tokens).  WSL: ~/venvs/train/bin/python fit_check.py"""
import json, os, glob, collections, statistics as st
from tokenizers import Tokenizer
H = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(H, "..", "..", ".."))
tok = Tokenizer.from_file(os.path.expanduser("~/models/llama-3.2-3b-instruct/tokenizer.json"))
n = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
fx = json.load(open(os.path.join(ROOT, "Code/smart-city-edge-agent/app/backend/testdata/v2_prompt_fixtures.json"), encoding="utf-8"))
items = [v for k, v in fx.items() if k != "meta"]
items = items[0] if len(items) == 1 and isinstance(items[0], list) else [x for v in items for x in (v if isinstance(v, list) else [v])]
res = collections.defaultdict(list); sysl = collections.defaultdict(set)
for it in items:
    if not isinstance(it, dict) or "prompt" not in it: continue
    p = it["prompt"]; i = p.find("<|eot_id|>")
    res[it["role"]].append((it.get("n"), n(p))); sysl[it["role"]].add(n(p[: i + 10]))
out = {"prompt_tokens_by_role": {}, "system_turn_tokens": {k: sorted(v) for k, v in sysl.items()}}
for r, v in res.items():
    big = [t for N, t in v if N and N >= 132]
    out["prompt_tokens_by_role"][r] = dict(count=len(v), max=max(t for _, t in v), max_n_ge_132=max(big) if big else None,
                                           median=st.median(t for _, t in v))
mx = []
for f in glob.glob(os.path.join(ROOT, "proofs/2026-10-20_v2_post/device/*/samples.jsonl")):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); mx.append(r["tokens"])
mx.sort()
out["output_tokens"] = dict(n=len(mx), p50=mx[len(mx)//2], p99=mx[int(len(mx)*.99)], p999=mx[int(len(mx)*.999)], max=mx[-1])
print(json.dumps(out, indent=1)); json.dump(out, open(os.path.join(H, "fit_check.json"), "w"), indent=1)

# per-role max prompt tokens by window length bucket (4 h early alerts vs 8/12 h refinements)
bk = collections.defaultdict(int)
for r, v in res.items():
    for N, t in v:
        b = "n<=48" if N <= 48 else "n<=96" if N <= 96 else "n<=144"
        bk[(r, b)] = max(bk[(r, b)], t)
out["max_prompt_by_role_and_window"] = {f"{r}/{b}": t for (r, b), t in sorted(bk.items())}
print(json.dumps(out["max_prompt_by_role_and_window"], indent=1)); json.dump(out, open(os.path.join(H, "fit_check.json"), "w"), indent=1)
