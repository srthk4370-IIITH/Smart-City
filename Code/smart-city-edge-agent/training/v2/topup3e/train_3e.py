"""3e: on-policy preference fine-tuning of the v2 adapter on v2's OWN mistakes (DPO + NLL, i.e. RPO), with gold replay.

Items (train3e.jsonl from build_3e.py):
  pair : prompt, gold completion (chosen), the model's own value for the first wrong decision (rejected), reference
         (= v2, before training) log-probs of both spans (mine_3e.py). Loss = -logsigmoid(beta*((pc-rc)-(pr-rr)))
         + rpo_alpha * mean CE(chosen completion).
  sft  : gold replay rows (answered correctly by v2): mean CE over the completion.
Batch 1 x grad-accum, cosine LR with warm-up, nf4 base + LoRA (v2 adapter, trainable), checkpoints every
--save-every steps, thermal pauses, STOP file, deadline. Stats (dpo loss, reward margin, pair accuracy, nll) are
logged to stats.jsonl.

  python train_3e.py --out ~/smartcity_runs/agents_v2_topup3e/run1 --data .../train3e.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import Trainer, TrainerCallback, TrainingArguments

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
import common3e as K  # noqa: E402
from train_agents import ThermalGuard, gpu_temp, log  # noqa: E402
from train_v2 import SessionGuard  # noqa: E402


class DS(torch.utils.data.Dataset):
    def __init__(self, rows, tok):
        self.items = []
        for r in rows:
            p = K.tok_ids(tok, r["prompt"])
            if r["type"] == "pair":
                pr = r["pair"]
                assert pr["c_ids"] == K.tok_ids(tok, r["completion"])
                self.items.append({"type": 1, "p": p, **pr})
            else:
                self.items.append({"type": 0, "p": p, "c_ids": K.tok_ids(tok, r["completion"])})

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def collate(b):
    assert len(b) == 1
    return {"item": b[0]}


class PTrainer(Trainer):
    beta, alpha, stats = 0.1, 1.0, []

    def _fwd(self, model, p, ids):
        x = torch.tensor([p + ids], device=model.device)
        out = model(input_ids=x, attention_mask=torch.ones_like(x), num_logits_to_keep=len(ids) + 1)
        return out.logits[0, :-1].float()

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        it = inputs["item"]
        c = it["c_ids"]
        lg = self._fwd(model, it["p"], c)
        tgt = torch.tensor(c, device=lg.device)
        nll = F.cross_entropy(lg, tgt)
        if it["type"] == 0:
            self.stats.append({"t": 0, "nll": float(nll)})
            return nll
        lo = it["lo"]
        pc = torch.log_softmax(lg[lo:it["c_hi"]], -1).gather(1, tgt[lo:it["c_hi"], None]).sum()
        r = it["r_ids"]
        lr_ = self._fwd(model, it["p"], r)
        rt = torch.tensor(r, device=lr_.device)
        pr = torch.log_softmax(lr_[lo:it["r_hi"]], -1).gather(1, rt[lo:it["r_hi"], None]).sum()
        z = self.beta * ((pc - it["ref_c"]) - (pr - it["ref_r"]))
        dpo = -F.logsigmoid(z)
        self.stats.append({"t": 1, "nll": float(nll), "dpo": float(dpo), "margin": float(z / self.beta),
                           "acc": float(pc > pr), "pc": float(pc), "pr": float(pr)})
        return dpo + self.alpha * nll


class StatLog(TrainerCallback):
    def __init__(self, out, trainer_cls):
        self.p, self.T = out / "stats.jsonl", trainer_cls

    def on_log(self, args, state, control, logs=None, **kw):
        s = self.T.stats
        if not s:
            return
        pairs = [x for x in s if x["t"] == 1]
        rec = {"step": state.global_step, "at": f"{datetime.now():%H:%M:%S}", "lr": (logs or {}).get("learning_rate"),
               "n_pair": len(pairs), "n_sft": len(s) - len(pairs),
               "nll_sft": round(sum(x["nll"] for x in s if x["t"] == 0) / max(1, len(s) - len(pairs)), 5)}
        if pairs:
            for k in ("dpo", "margin", "acc", "nll"):
                rec[k + "_pair"] = round(sum(x[k] for x in pairs) / len(pairs), 4)
        with open(self.p, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.T.stats.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--init-adapter", default=K.V2_ADAPTER)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--warmup-ratio", type=float, default=0.1)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--rpo-alpha", type=float, default=1.0)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--thermal-pause-at", type=int, default=76)
    ap.add_argument("--thermal-resume-at", type=int, default=68)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "STOP").unlink(missing_ok=True)
    fh = open(out / "train.log", "a", encoding="utf-8")
    log(f"=== 3e preference session start; GPU {gpu_temp()} C; args {vars(a)}", fh)
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    rows = K.read_jsonl(a.data)
    if a.limit:
        rows = rows[:a.limit]
    tok, model = K.load_model(a.init_adapter, trainable=True)
    params = [p for p in model.parameters() if p.requires_grad]
    ds = DS(rows, tok)
    steps = max(1, math.ceil(len(ds) * a.epochs / a.grad_accum))
    plan = {"rows": len(ds), "pairs": sum(1 for x in ds.items if x["type"] == 1), "max_steps": steps, **vars(a),
            "trainable_M": round(sum(p.numel() for p in params) / 1e6, 1), "planned_at": f"{datetime.now():%Y-%m-%d %H:%M}"}
    if not (out / "plan.json").exists():
        (out / "plan.json").write_text(json.dumps(plan, indent=1))
    log(f"plan {plan}", fh)
    targs = TrainingArguments(
        output_dir=str(out / "checkpoints"), max_steps=steps, per_device_train_batch_size=1, gradient_accumulation_steps=a.grad_accum,
        learning_rate=a.lr, lr_scheduler_type="cosine", warmup_steps=max(1, int(a.warmup_ratio * steps)), weight_decay=0.0,
        max_grad_norm=1.0, bf16=True, optim="paged_adamw_8bit", logging_steps=5, eval_strategy="no", save_strategy="steps",
        save_steps=a.save_every, save_total_limit=None, report_to="none", seed=a.seed, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False}, remove_unused_columns=False, dataloader_num_workers=0)
    PTrainer.beta, PTrainer.alpha = a.beta, a.rpo_alpha
    therm = ThermalGuard(a.thermal_pause_at, a.thermal_resume_at, fh)
    tr = PTrainer(model=model, args=targs, train_dataset=ds, data_collator=collate,
                  callbacks=[SessionGuard(out, a.hours, fh), therm, StatLog(out, PTrainer)])
    ck = sorted((out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    t0 = time.time()
    tr.train(resume_from_checkpoint=str(ck[-1]) if ck else None)
    st = tr.state.global_step
    if st >= steps:
        tr.save_model(str(out / "checkpoints" / f"checkpoint-{st}"))
    log(f"session ended at step {st}/{steps} after {(time.time() - t0) / 3600:.2f} h; thermal pauses {therm.pauses}", fh)
    (out / "session_status.json").write_text(json.dumps({"step": st, "max_steps": steps, "done": st >= steps,
                                                         "ended": f"{datetime.now():%Y-%m-%d %H:%M}"}))


if __name__ == "__main__":
    main()
