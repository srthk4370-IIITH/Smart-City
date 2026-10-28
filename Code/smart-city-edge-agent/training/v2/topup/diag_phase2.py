"""Phase-2 diagnosis A1: decision-level metrics for several adapters on the original dev subset and the per-stage
dev sets. One nf4 base (as in training), adapters swapped in place. Results appended per (adapter, set) to
<out>/decision_metrics.jsonl and per-row predictions to <out>/preds_<adapter>.jsonl.

  python diag_phase2.py --out <dir> --adapters name=path ...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
from train_agents import read_jsonl  # noqa: E402
from train_v2 import dev_subset  # noqa: E402
import decision_eval as DE  # noqa: E402


def sets(data):
    out = {"orig": dev_subset(read_jsonl(data / "dev.jsonl"), 200, 42)}
    t = read_jsonl(data / "dev_target.jsonl")
    for st, nm in (("early", "early"), ("1.5h", "s15h"), ("3h", "s3h"), ("other", "other")):
        out[nm] = [r for r in t if r.get("stage") == st]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=str(Path.home() / "smartcity_runs/agents_v2_topup3/data"))
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--adapters", nargs="+", required=True)
    ap.add_argument("--batch", type=int, default=12)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    base = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    S = sets(Path(a.data))
    done = set()
    mp = out / "decision_metrics.jsonl"
    if mp.exists():
        done = {(json.loads(l)["adapter"], json.loads(l)["set"]) for l in open(mp)}
    model = None
    for spec in a.adapters:
        name, path = spec.split("=", 1)
        if model is None:
            model = PeftModel.from_pretrained(base, path, adapter_name=name)
        else:
            model.load_adapter(path, adapter_name=name)
        model.set_adapter(name)
        for sn, rows in S.items():
            if (name, sn) in done:
                continue
            t0 = time.time()
            m = DE.evaluate(model, tok, rows, a.batch)
            texts = m.pop("_texts", [])
            with open(out / f"preds_{name}_{sn}.jsonl", "w") as f:
                for r, t in zip(rows, texts):
                    f.write(json.dumps({"id": r["id"], "bucket": r.get("topup_bucket"), "role": r["role"], "d": r.get("d"), "n": r["n"], "gold": DE.gold(r), "pred": DE.parse(t), "text": t}) + "\n")
            m.update(adapter=name, set=sn, path=path, seconds=round(time.time() - t0, 1))
            with open(mp, "a") as f:
                f.write(json.dumps(m) + "\n")
            print(json.dumps(m), flush=True)
        pass


if __name__ == "__main__":
    main()
