"""Score a top-up adapter (checkpoint dir) on the same two dev sets as train_topup.py: original dev_subset(dev, 200, 42)
and targeted dev_subset(dev_target, 160, 42). Loss = mean of per-example sliced losses (= the Trainer's eval_loss at
batch size 1). Appends the result to <run>/evals_offline.jsonl and prints it.

  python eval_ckpt.py --run ~/smartcity_runs/agents_v2_topup --adapter ~/smartcity_runs/agents_v2_topup/checkpoints/checkpoint-25
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
from train_agents import SFTData, read_jsonl, sliced_loss  # noqa: E402
from train_v2 import dev_subset  # noqa: E402


@torch.no_grad()
def mean_loss(model, ds):
    model.eval()
    v = []
    for ex in ds.items:
        b = {k: torch.tensor([x], device="cuda") for k, x in ex.items()}
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss, _ = sliced_loss(model, b["input_ids"], b["attention_mask"], b["labels"])
        v.append(float(loss))
    return sum(v) / len(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    a = ap.parse_args()
    run = Path(a.run).expanduser()
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    dev = SFTData(dev_subset(read_jsonl(run / "data" / "dev.jsonl"), 200, 42), tok, 1280)
    tdev = SFTData(dev_subset(read_jsonl(run / "data" / "dev_target.jsonl"), 160, 42), tok, 1280)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    base = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model = PeftModel.from_pretrained(base, a.adapter)
    t0 = time.time()
    res = {"adapter": a.adapter, "eval_orig_loss": round(mean_loss(model, dev), 6),
           "eval_target_loss": round(mean_loss(model, tdev), 6), "seconds": round(time.time() - t0, 1),
           "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    b = json.loads((run / "baseline.json").read_text())
    res["orig_rel"] = round(res["eval_orig_loss"] / b["eval_orig_loss"] - 1, 4)
    res["target_rel"] = round(res["eval_target_loss"] / b["eval_target_loss"] - 1, 4)
    with open(run / "evals_offline.jsonl", "a") as f:
        f.write(json.dumps(res) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
