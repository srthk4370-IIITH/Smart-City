import json, sys, torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
from accelerate import init_empty_weights
M = "/home/hp_srthk4370/models/qwen3.5-4b"
cfg = AutoConfig.from_pretrained(M)
print(type(cfg).__name__, getattr(cfg, "text_config", None).__class__.__name__)
with init_empty_weights():
    m = AutoModelForCausalLM.from_config(cfg)
print(type(m).__name__)
names = set()
for n, mod in m.named_modules():
    if isinstance(mod, torch.nn.Linear):
        names.add(n.split(".")[-1] + ("@vis" if "visual" in n else ""))
print(sorted(names))
print(sum(p.numel() for p in m.parameters()) / 1e9)
tok = AutoTokenizer.from_pretrained(M)
msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": {"a": 1}}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{\"r\": 2}"}, {"role": "assistant", "content": "done"}]
tools = [{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object", "properties": {"a": {"type": "integer"}}}}}]
for k in (2, 4):
    g = tok.apply_chat_template(msgs[:k], tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    h = tok.apply_chat_template(msgs[:k], tools=tools, tokenize=False, add_generation_prompt=False, enable_thinking=False)
    f = tok.apply_chat_template(msgs[:k + 1], tools=tools, tokenize=False, enable_thinking=False)
    print("---k", k, "prefix ok", f.startswith(h)); print(repr(g[len(h):])); print(repr(f[len(h):]))
