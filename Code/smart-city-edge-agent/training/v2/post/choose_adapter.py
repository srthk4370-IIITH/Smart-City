"""Pick the v2 adapter to deploy: best_adapter/ (lowest dev loss seen during training) vs adapter/ (final step).

Training evaluated dev loss every 300 steps on dev_subset(dev, 200, seed 42), so the final step (4494) has no
dev loss of its own. Both adapters are therefore scored here on exactly that dev subset with exactly the
training loss (train_agents.sliced_loss: assistant tokens only, nf4 base as in QLoRA training). The lower
loss wins; a tie within 0.0005 goes to the final adapter (it saw the whole schedule).

Writes <post>/choice.json. Read-only on the run dir.
  python choose_adapter.py --run ~/smartcity_runs/agents_v2 --post ~/smartcity_runs/agents_v2/post
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
sys.path.insert(0, str(HERE.parent))        # training/v2
sys.path.insert(0, str(HERE.parents[1]))    # training
from train_agents import SFTData, read_jsonl, sliced_loss  # noqa: E402
from train_v2 import dev_subset  # noqa: E402


@torch.no_grad()
def dev_loss(model, ds):
    model.eval()
    tot, ntok, per_ex = 0.0, 0, []
    for ex in ds.items:
        b = {k: torch.tensor([v], device="cuda") for k, v in ex.items()}
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss, _ = sliced_loss(model, b["input_ids"], b["attention_mask"], b["labels"])
        c = sum(1 for x in ex["labels"] if x != -100)
        tot += float(loss) * c
        ntok += c
        per_ex.append(float(loss))
    # the Trainer's eval_loss (batch size 1) is the mean of per-example losses: that is what best.json holds
    return sum(per_ex) / len(per_ex), tot / ntok, ntok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--post", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--data", default=str(HERE.parents[2] / "data" / "sft_v2"))
    ap.add_argument("--dev-n", type=int, default=200)   # start_v2.sh trained with --dev-n 200
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-len", type=int, default=1280)
    a = ap.parse_args()
    run, post = Path(a.run), Path(a.post)
    post.mkdir(parents=True, exist_ok=True)
    if (post / "choice.json").exists():
        print("already chosen:", (post / "choice.json").read_text())
        return
    status = json.loads((run / "session_status.json").read_text())
    if not status.get("done"):
        raise SystemExit(f"training not complete: {status}")
    best_meta = json.loads((run / "best.json").read_text())

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    dev = dev_subset(read_jsonl(Path(a.data) / "dev.jsonl"), a.dev_n, a.seed)
    ds = SFTData(dev, tok, a.max_len)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    base = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model = PeftModel.from_pretrained(base, str(run / "best_adapter"), adapter_name="best")
    model.load_adapter(str(run / "adapter"), adapter_name="final")
    res = {}
    for name in ("best", "final"):
        model.set_adapter(name)
        t0 = time.time()
        loss, tok_loss, ntok = dev_loss(model, ds)
        res[name] = {"dev_loss": round(loss, 5), "dev_loss_token_weighted": round(tok_loss, 5), "tokens": ntok,
                     "seconds": round(time.time() - t0, 1)}
        print(name, res[name], flush=True)
    pick = "final" if res["final"]["dev_loss"] <= res["best"]["dev_loss"] + 0.0005 else "best"
    choice = {"chosen": pick, "adapter_dir": str(run / ("adapter" if pick == "final" else "best_adapter")),
              "rule": "lower dev loss on dev_subset(dev, 200, seed 42) (the training eval set); tie (<=0.0005) -> final",
              "measured": res, "best_json_from_training": best_meta, "final_step": status["step"],
              "dev_rows": len(dev), "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    (post / "choice.json").write_text(json.dumps(choice, indent=1))
    print(json.dumps(choice, indent=1))


if __name__ == "__main__":
    main()
