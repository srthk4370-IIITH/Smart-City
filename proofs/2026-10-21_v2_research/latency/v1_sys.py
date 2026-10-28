"""v1 system-turn length and prompt tokens (window study prompts) for the prefill fit. WSL train venv."""
import json, os, collections, statistics as st
from tokenizers import Tokenizer
tok = Tokenizer.from_file(os.path.expanduser("~/models/llama-3.2-3b-instruct/tokenizer.json"))
n = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../2026-10-16_window_study/prompts.jsonl")
sysl = collections.Counter(); seen = 0
for l in open(p, encoding="utf-8"):
    r = json.loads(l); pr = r.get("prompt", "")
    i = pr.find("<|eot_id|>"); sysl[n(pr[: i + 10])] += 1; seen += 1
    if seen >= 300: break
print("v1 system turn tokens:", sysl.most_common(5))
