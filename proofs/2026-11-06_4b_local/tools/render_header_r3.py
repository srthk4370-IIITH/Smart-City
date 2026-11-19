"""Render the r3 chat header (Qwen3.5 HF chat template, tools_r3.json["chat"], everything before the system text) with the 2B
and 4B tokenizers (must be identical, thinking on and off) -> chat_header_r3.txt (the backend embeds a byte-identical copy).
  ~/venvs/rsn/bin/python render_header_r3.py
"""
import getpass
import json
import os

from transformers import AutoTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
tools = json.load(open(os.path.join(HERE, "..", "data", "final", "tools_r3.json"), encoding="utf-8"))
res = {}
for model in ["qwen3.5-2b", "qwen3.5-4b"]:
    tok = AutoTokenizer.from_pretrained("/home/%s/models/%s" % (getpass.getuser(), model))
    for think in (False, True):
        txt = tok.apply_chat_template([{"role": "system", "content": "SYSTEMTEXT"}, {"role": "user", "content": "q"}],
                                      tools=tools["chat"], tokenize=False, enable_thinking=think)
        res[(model, think)] = txt[:txt.index("SYSTEMTEXT")]
assert len(set(res.values())) == 1, "renders differ"
h = res[("qwen3.5-4b", True)]
open(os.path.join(HERE, "chat_header_r3.txt"), "w", encoding="utf-8", newline="").write(h)
print("header bytes", len(h.encode()), "tokens", len(tok(h)["input_ids"]))
