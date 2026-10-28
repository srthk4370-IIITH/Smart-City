"""Shared pieces of 3e mining + preference training (same tokenisation in both, so reference log-probs match)."""
from __future__ import annotations

import json
import re

import torch

BASE = "/home/hp_srthk4370/models/llama-3.2-3b-instruct"
V2_ADAPTER = "/home/hp_srthk4370/smartcity_runs/agents_v2/adapter"
FIELDS = ("pattern", "status")          # decisions in completion order that are preference-trained
_RX = {k: re.compile(r'"%s":\s*"([^"]*)"' % k) for k in FIELDS}


def value_span(completion, field):
    m = _RX[field].search(completion)
    return m.span(1) if m else None


def tok_ids(tok, text):
    return tok(text, add_special_tokens=False)["input_ids"]


def make_pair(tok, completion, field, pred):
    """chosen = gold completion; rejected = gold completion with this field's value replaced by `pred` (the model's
    own greedy value, earlier fields are gold so the context is identical up to the value). The DPO span of each
    side = from the first token where the two sequences differ through the last token touching the value."""
    s, e = value_span(completion, field)
    rej = completion[:s] + pred + completion[e:]
    c = tok(completion, add_special_tokens=False, return_offsets_mapping=True)
    r = tok(rej, add_special_tokens=False, return_offsets_mapping=True)
    L = 0
    while L < min(len(c["input_ids"]), len(r["input_ids"])) and c["input_ids"][L] == r["input_ids"][L]:
        L += 1
    c_hi = max(i for i, (a, b) in enumerate(c["offset_mapping"]) if a < e) + 1
    r_hi = max(i for i, (a, b) in enumerate(r["offset_mapping"]) if a < s + len(pred)) + 1
    c_hi, r_hi = max(c_hi, L + 1), max(r_hi, L + 1)
    return {"c_ids": c["input_ids"], "r_ids": r["input_ids"][:r_hi], "lo": L, "c_hi": c_hi, "r_hi": r_hi}


def span_logp(model, p_ids, ids, lo, hi, grad=False):
    """sum log p(ids[lo:hi] | prompt + ids[:i]) and (if needed) the full-forward logits for ids."""
    x = torch.tensor([p_ids + ids], device="cuda")
    with torch.set_grad_enabled(grad):
        out = model(input_ids=x, attention_mask=torch.ones_like(x), num_logits_to_keep=len(ids) + 1)
        lg = out.logits[0, :-1].float()            # lg[j] predicts ids[j]
        lp = torch.log_softmax(lg[lo:hi], -1).gather(1, torch.tensor(ids[lo:hi], device="cuda")[:, None]).sum()
    return lp, lg


def load_model(adapter=V2_ADAPTER, trainable=False):
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel, prepare_model_for_kbit_training
    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                           bnb_4bit_compute_dtype=torch.bfloat16)
    m = AutoModelForCausalLM.from_pretrained(BASE, local_files_only=True, quantization_config=q, torch_dtype=torch.bfloat16,
                                             device_map={"": 0}, attn_implementation="sdpa")
    if trainable:
        m.config.use_cache = False
        m = prepare_model_for_kbit_training(m, use_gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False})
    m = PeftModel.from_pretrained(m, adapter, is_trainable=trainable)
    return tok, m


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]
