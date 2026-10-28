"""Prompt token counts of the v2 roles (Llama 3.2 tokenizer, laptop only, no device).
Sources: Go/Python parity fixtures (all 6 roles, any N) and app synthesizer prompts from refine_v7.
Prints per role and window: total tokens, cached system turn (up to the first <|eot_id|>), uncached tail.
  py -3 prompt_tokens.py  -> prompt_tokens.json
"""
import json, glob, statistics as st
from pathlib import Path
from tokenizers import Tokenizer
H = Path(__file__).resolve().parent
Q = Path(r"C:\Users\hp\Desktop\qidk")
tok = Tokenizer.from_file(str(Q / "qidk_backup/ckpt_ftgptq16/tokenizer.json"))
n_tok = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
fx = json.load(open(Q / "Code/smart-city-edge-agent/app/backend/testdata/v2_prompt_fixtures.json", encoding="utf-8"))["fixtures"]
rows = {}
for f in fx:
    p = f["prompt"]
    sys_turn = p[: p.index("<|eot_id|>") + len("<|eot_id|>")]
    t, s = n_tok(p), n_tok(sys_turn)
    rows.setdefault((f["role"], f["n"]), []).append((t, s, t - s))
out = {"agents": {}, "synth": []}
for (role, n), v in sorted(rows.items()):
    if n not in (48, 96, 144):
        continue
    out["agents"][f"{role}@{n}"] = dict(cases=len(v), total_med=st.median(x[0] for x in v), total_max=max(x[0] for x in v),
                                        system_turn=st.median(x[1] for x in v), uncached_med=st.median(x[2] for x in v))
for f in sorted(glob.glob(str(Q / "proofs/2026-10-21_v2_app/refine_v7/INC-*_early.json"))):
    j = json.load(open(f, encoding="utf-8"))
    fin = j.get("final") or {}
    if fin.get("prompt"):
        p = fin["prompt"]
        s = p[: p.index("<|eot_id|>") + len("<|eot_id|>")] if "<|eot_id|>" in p else ""
        out["synth"].append(dict(incident=j["id"], sensors=len(j.get("sensors") or []), tokens=n_tok(p), system_turn=n_tok(s),
                                 gen_tokens=fin.get("gen_tokens"), ttft_ms=fin.get("ttft_ms"), latency_ms=fin.get("latency_ms")))
json.dump(out, open(H / "prompt_tokens.json", "w"), indent=1)
for k, v in out["agents"].items():
    print(f"{k:22s} total med {v['total_med']:6.0f} max {v['total_max']:5d}  system {v['system_turn']:5.0f}  uncached {v['uncached_med']:5.0f}  (n={v['cases']})")
for s in out["synth"]:
    print("synth", s)
