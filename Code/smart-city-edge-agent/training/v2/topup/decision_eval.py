"""Decision-level evaluation of a v2 agent adapter (phase-2 diagnosis + phase-2c pass rule).

For a list of rows (prompt, completion):
  * decision-token loss: mean cross-entropy over the completion tokens that carry the VALUES of pattern / status /
    likely_cause / event_active / fault_kind (teacher-forced, exactly the training tokenisation), plus the
    whole-completion loss (the training metric) for reference;
  * greedy accuracy: generate from the prompt (no prefill, greedy) until the '"onset"' key appears (or 110 tokens)
    and compare pattern / status / likely_cause / event_active / fault_kind with the gold target.
Usable as a library (evaluate()) and from the CLI (diag_phase2.py).
"""
from __future__ import annotations

import json
import re

import torch

DECISION_KEYS = ("pattern", "status", "likely_cause", "event_active", "fault_kind")
_RX = {k: re.compile(r'"%s":\s*"([^"]*)"' % k) for k in ("pattern", "status", "likely_cause", "fault_kind")}
_RX["event_active"] = re.compile(r'"event_active":\s*(true|false)')


def value_spans(c):
    """char spans of the decision values inside a completion string."""
    out = {}
    for k in DECISION_KEYS:
        m = _RX[k].search(c)
        if m:
            out[k] = m.span(1)
    return out


def parse(text):
    return {k: (m.group(1) if (m := _RX[k].search(text)) else None) for k in DECISION_KEYS}


def gold(r):
    t = json.loads(r["completion"][: -len("<|eot_id|>")] if r["completion"].endswith("<|eot_id|>") else r["completion"])
    return {"pattern": t.get("pattern"), "status": t.get("status"), "likely_cause": t.get("likely_cause"),
            "event_active": None if t.get("event_active") is None else ("true" if t["event_active"] else "false"),
            "fault_kind": t.get("fault_kind")}


def field_tokens(tok, completion):
    """completion token ids and {field: [token indices of its value]}."""
    enc = tok(completion, add_special_tokens=False, return_offsets_mapping=True)
    f = {k: [i for i, (a, b) in enumerate(enc["offset_mapping"]) if a < e and b > s0]
         for k, (s0, e) in value_spans(completion).items()}
    return enc["input_ids"], f


def decision_weights(tok, completion):
    """(completion token ids, per-token 0/1 decision mask) with the training tokenisation."""
    enc = tok(completion, add_special_tokens=False, return_offsets_mapping=True)
    spans = list(value_spans(completion).values())
    mask = [1 if any(a < e and b > s for s, e in spans) else 0 for a, b in enc["offset_mapping"]]
    return enc["input_ids"], mask


@torch.no_grad()
def token_losses(model, tok, rows):
    """per row: (whole-completion mean CE, decision-token mean CE, n decision tokens, {field: all value tokens argmax-correct})
    Teacher-forced decision accuracy: with the gold prefix, is every token of the field's value the argmax? For pattern
    (the first key) this equals greedy decoding exactly; later fields are conditioned on the gold earlier fields."""
    model.eval()
    res = []
    for r in rows:
        p = tok(r["prompt"], add_special_tokens=False)["input_ids"]
        c, fields = field_tokens(tok, r["completion"])
        mask = [0] * len(c)
        for idx in fields.values():
            for i in idx:
                mask[i] = 1
        ids = torch.tensor([p + c], device="cuda")
        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = model(input_ids=ids, attention_mask=torch.ones_like(ids), num_logits_to_keep=len(c) + 1)
        logits = out.logits[0, :-1].float()
        ce = torch.nn.functional.cross_entropy(logits, torch.tensor(c, device="cuda"), reduction="none")
        m = torch.tensor(mask, device="cuda", dtype=torch.float)
        am = logits.argmax(-1).tolist()
        ok = {k: all(am[i] == c[i] for i in idx) for k, idx in fields.items() if idx}
        res.append((float(ce.mean()), float((ce * m).sum() / m.sum()) if m.sum() else None, int(m.sum()), ok))
    return res


@torch.no_grad()
def greedy(model, tok, rows, batch=12, max_new=110):
    model.eval()
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = "<|finetune_right_pad_id|>"
    outs = []
    stop = tok.encode('"onset"', add_special_tokens=False)
    for i in range(0, len(rows), batch):
        prompts = [r["prompt"] for r in rows[i:i + batch]]
        enc = tok(prompts, add_special_tokens=False, return_tensors="pt", padding=True).to("cuda")
        with torch.autocast("cuda", dtype=torch.bfloat16):
            g = model.generate(**enc, max_new_tokens=max_new, do_sample=False, temperature=None, top_p=None,
                               pad_token_id=tok.pad_token_id, eos_token_id=[tok.convert_tokens_to_ids("<|eot_id|>")],
                               stop_strings=['"onset"'], tokenizer=tok)
        for j in range(len(prompts)):
            outs.append(tok.decode(g[j, enc["input_ids"].shape[1]:], skip_special_tokens=True))
    return outs


def evaluate(model, tok, rows, batch=12, do_loss=True, do_greedy=False):
    """metrics for one row set: acc_* = teacher-forced decision accuracy, gacc_* = greedy (optional, slow)."""
    m = {"n": len(rows)}
    if do_loss:
        L = token_losses(model, tok, rows)
        m["loss_all"] = round(sum(x[0] for x in L) / len(L), 6)
        dl = [x[1] for x in L if x[1] is not None]
        m["loss_decision"] = round(sum(dl) / len(dl), 6) if dl else None
        for k in DECISION_KEYS:
            v = [x[3][k] for x in L if k in x[3]]
            m[f"acc_{k}"] = round(sum(v) / len(v), 4) if v else None
            m[f"n_{k}"] = len(v)
    if do_greedy:
        texts = greedy(model, tok, rows, batch)
        acc = {k: [0, 0] for k in DECISION_KEYS}
        for r, t in zip(rows, texts):
            g, p = gold(r), parse(t)
            for k in DECISION_KEYS:
                if k == "fault_kind" and g[k] is None and p[k] is None:
                    continue
                if k == "fault_kind" and g[k] is None:
                    acc[k][1] += 1  # predicted a fault kind where none was due
                    continue
                acc[k][1] += 1
                acc[k][0] += int(p[k] == g[k])
        for k, (a, n) in acc.items():
            m[f"gacc_{k}"] = round(a / n, 4) if n else None
        m["invalid"] = sum(1 for t in texts if parse(t)["pattern"] is None)
        m["_texts"] = texts
    return m
