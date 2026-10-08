"""Evaluate tuned agent vs base model vs Mode-1 rule classifier on held-out Nov-Dec windows.

Metrics per role: valid JSON, pattern accuracy, status accuracy, cause accuracy, action accuracy,
evidence validity (all cited ids exist in the prompt), mean output tokens.
Writes <run>/eval.json and <run>/eval.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

BASE_ID = "meta-llama/Llama-3.2-3B-Instruct"


def extract_json(text):
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    for i in range(s, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def score(rows, outputs):
    agg = defaultdict(lambda: defaultdict(float))
    for r, (text, ntok) in zip(rows, outputs):
        gold = json.loads(r["completion"].replace("<|eot_id|>", ""))
        pred = extract_json(text)
        for key in (r["role"], "ALL"):
            a = agg[key]
            a["n"] += 1
            a["tokens"] += ntok
            if not isinstance(pred, dict):
                continue
            a["json_valid"] += 1
            for k in ("pattern", "status", "likely_cause", "action"):
                a[k] += pred.get(k) == gold[k]
            ids = re.findall(r"E\d+", " ".join(map(str, pred.get("observations", []))))
            valid_ids = {f"E{i}" for i in range(1, 9)}
            a["evidence_valid"] += bool(ids) and all(i in valid_ids for i in ids)
    res = {}
    for key, a in agg.items():
        n = a["n"]
        res[key] = {"n": int(n), **{k: round(a[k] / n, 3) for k in
                    ("json_valid", "pattern", "status", "likely_cause", "action", "evidence_valid")},
                    "mean_out_tokens": round(a["tokens"] / n, 1)}
    return res


@torch.no_grad()
def generate(model, tok, rows, bs, max_new):
    outs = []
    tok.padding_side = "left"
    for i in range(0, len(rows), bs):
        chunk = rows[i:i + bs]
        enc = tok([r["prompt"] for r in chunk], add_special_tokens=False, return_tensors="pt", padding=True).to("cuda")
        gen = model.generate(**enc, max_new_tokens=max_new, do_sample=False, temperature=None, top_p=None,
                             eos_token_id=[128001, 128008, 128009], pad_token_id=tok.pad_token_id)
        for j in range(len(chunk)):
            new = gen[j, enc["input_ids"].shape[1]:]
            new = new[new != tok.pad_token_id]
            outs.append((tok.decode(new, skip_special_tokens=True), int(len(new))))
        print(f"  {min(i + bs, len(rows))}/{len(rows)}", flush=True)
    return outs


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", default=str(root / "data" / "sft"))
    ap.add_argument("--per-role", type=int, default=30)
    ap.add_argument("--bs", type=int, default=6)
    ap.add_argument("--max-new", type=int, default=220)
    ap.add_argument("--skip-base", action="store_true")
    a = ap.parse_args()
    run = Path(a.run)
    plan = json.loads((run / "plan.json").read_text())
    rows_all = [json.loads(l) for l in open(Path(a.data) / "test.jsonl", encoding="utf-8")]
    rows = []
    for role in plan["roles"]:
        rr = [r for r in rows_all if r["role"] == role]
        by_p = defaultdict(list)
        for r in rr:
            by_p[r["pattern"]].append(r)
        pats = sorted(by_p); i = 0
        take = []
        while len(take) < a.per_role and any(by_p.values()):
            p = pats[i % len(pats)]
            if by_p[p]:
                take.append(by_p[p].pop(0))
            i += 1
        rows.extend(take)
    print(f"eval on {len(rows)} held-out examples ({', '.join(plan['roles'])})", flush=True)

    # Mode-1 rule baseline (pattern only)
    rule = defaultdict(lambda: [0, 0])
    for r in rows:
        ok = F.rule_pattern(r["role"], r["metric"], r["xs"], r["end_epoch"]) == r["pattern"]
        for k in (r["role"], "ALL"):
            rule[k][0] += ok; rule[k][1] += 1
    results = {"rules_pattern_acc": {k: round(v[0] / v[1], 3) for k, v in rule.items()}}

    tok = AutoTokenizer.from_pretrained(BASE_ID, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    base = AutoModelForCausalLM.from_pretrained(BASE_ID, local_files_only=True, quantization_config=quant,
                                                torch_dtype=torch.bfloat16, device_map={"": 0})
    model = PeftModel.from_pretrained(base, str(run / "adapter"))
    model.eval()
    t0 = time.time()
    print("tuned model ...", flush=True)
    results["tuned"] = score(rows, generate(model, tok, rows, a.bs, a.max_new))
    results["tuned_seconds"] = round(time.time() - t0)
    if not a.skip_base:
        print("base model (adapter disabled) ...", flush=True)
        t0 = time.time()
        with model.disable_adapter():
            results["base"] = score(rows, generate(model, tok, rows, a.bs, a.max_new))
        results["base_seconds"] = round(time.time() - t0)
    (run / "eval.json").write_text(json.dumps(results, indent=1))

    lines = ["# Agent evaluation (held-out Nov-Dec 2025 windows, host 4-bit)", "",
             f"Plan {plan['plan']}: roles {', '.join(plan['roles'])}; {len(rows)} examples.", "",
             "| role | model | JSON valid | pattern | status | cause | action | evidence ok | out tokens |",
             "|---|---|---|---|---|---|---|---|---|"]
    for key in list(plan["roles"]) + ["ALL"]:
        for name in ("tuned", "base"):
            if name in results and key in results[name]:
                m = results[name][key]
                lines.append(f"| {key} | {name} | {m['json_valid']} | {m['pattern']} | {m['status']} | {m['likely_cause']} | "
                             f"{m['action']} | {m['evidence_valid']} | {m['mean_out_tokens']} |")
        lines.append(f"| {key} | rules (Mode 1) | - | {results['rules_pattern_acc'].get(key, '-')} | - | - | - | - | 0 |")
    (run / "eval.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
