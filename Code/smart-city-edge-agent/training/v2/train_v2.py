"""Domain-agent retrain v2: QLoRA on the full v2 dataset, in resumable laptop sessions (RETRAIN_V2_SPEC.md).

Differences from train_agents.py (v1, kept unchanged for the deployed model):
* all six roles, all 36k train rows, 2 epochs, LoRA r=32 (alpha 64), max length 1152;
* no deadline planner: the step count is fixed once in plan.json (2 epochs over the whole set) and every
  session continues it from the newest checkpoint (optimizer, scheduler, RNG and data order restored by
  the Trainer);
* a session ends cleanly - checkpoint, then exit - when --session-hours run out OR when the file
  <out>/STOP appears (the "stop" answer in the session prompt writes it);
* the best dev-loss adapter is copied to <out>/best_adapter at every eval, because rotating checkpoints
  may delete it before the last session.

Run inside WSL via session_v2.sh. Loss only on the assistant JSON + <|eot_id|>, prompts tokenized exactly as
the device sends them (same SFTData / sliced loss as v1).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import torch
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq,
                          TrainerCallback, TrainingArguments)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from train_agents import BASE_ID, SFTData, SlicedTrainer, ThermalGuard, gpu_temp, log, read_jsonl, sliced_loss  # noqa: E402


def dev_subset(rows, n, seed):
    """n dev rows, round-robin over (role, pattern) so every role and pattern is in the eval loss."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[(r["role"], r["pattern"])].append(r)
    keys = sorted(by)
    for k in keys:
        rng.shuffle(by[k])
    out, i = [], 0
    while len(out) < n and any(by[k] for k in keys):
        k = keys[i % len(keys)]
        if by[k]:
            out.append(by[k].pop())
        i += 1
    return out


class SessionGuard(TrainerCallback):
    """Stops at the session's end or on <out>/STOP, saving a checkpoint first; logs progress and ETA."""

    def __init__(self, out, hours, fh):
        self.out, self.fh = out, fh
        self.end = datetime.now() + timedelta(hours=hours)
        self.t0 = self.s0 = None

    def on_train_begin(self, args, state, control, **kw):
        self.t0, self.s0 = time.time(), state.global_step
        log(f"session: steps {state.global_step}/{state.max_steps} done, session ends by {self.end:%a %H:%M} "
            f"(or when {self.out / 'STOP'} appears)", self.fh)

    def on_step_end(self, args, state, control, **kw):
        stop = (self.out / "STOP").exists()
        done = state.global_step - self.s0
        per = (time.time() - self.t0) / done if done else 0
        if state.global_step % 5 == 0 and done:
            eta = datetime.now() + timedelta(seconds=per * (state.max_steps - state.global_step))
            log(f"step {state.global_step}/{state.max_steps}  {per:.1f}s/step  all-done ETA {eta:%a %d %H:%M} "
                f"(training time only)", self.fh)
        if stop or (per and datetime.now() + timedelta(seconds=per * 2) > self.end):
            log("STOP requested: saving a checkpoint and ending this session" if stop else
                "session time is up: saving a checkpoint and ending this session", self.fh)
            control.should_training_stop = True
            control.should_save = True

    def on_log(self, args, state, control, logs=None, **kw):
        if logs:
            log("metrics " + json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in logs.items()}), self.fh)


class DutyThrottle(TrainerCallback):
    """Background mode: keeps the GPU busy only a fraction of the time so the user's own work stays smooth.
    After each micro-batch it sleeps (1/duty - 1) x that micro-batch's compute time. duty comes from the file
    <out>/DUTY (re-read every micro-batch, so it can be changed live; absent or >= 1 = full speed). Sleeping
    between micro-batches never changes the maths, only the pace."""

    def __init__(self, out):
        self.f, self.t = out / "DUTY", None

    def _duty(self):
        try:
            return min(1.0, max(0.05, float(self.f.read_text().strip())))
        except (OSError, ValueError):
            return 1.0

    def on_step_begin(self, args, state, control, **kw):
        self.t = time.time()

    def _pace(self):
        d = self._duty()
        if self.t is not None and d < 1.0:
            torch.cuda.synchronize()
            time.sleep((time.time() - self.t) * (1 / d - 1))
        self.t = time.time()

    def on_substep_end(self, args, state, control, **kw):
        self._pace()

    def on_step_end(self, args, state, control, **kw):
        self._pace()


class BestAdapter(TrainerCallback):
    """Keeps the lowest-dev-loss adapter across sessions (best.json survives restarts)."""

    def __init__(self, out, fh):
        self.out, self.fh = out, fh
        p = out / "best.json"
        self.best = json.loads(p.read_text()) if p.exists() else {"eval_loss": None, "step": None}

    def on_evaluate(self, args, state, control, metrics=None, model=None, **kw):
        loss = (metrics or {}).get("eval_loss")
        if loss is None or model is None:
            return
        if self.best["eval_loss"] is None or loss < self.best["eval_loss"]:
            self.best = {"eval_loss": loss, "step": state.global_step, "at": f"{datetime.now():%Y-%m-%d %H:%M}"}
            tmp = self.out / "best_adapter.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            model.save_pretrained(str(tmp))
            shutil.rmtree(self.out / "best_adapter", ignore_errors=True)
            tmp.rename(self.out / "best_adapter")
            (self.out / "best.json").write_text(json.dumps(self.best, indent=1))
            log(f"new best dev loss {loss:.4f} at step {state.global_step} -> best_adapter", self.fh)


def main():
    root = HERE.parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(root / "data" / "sft_v2"))
    ap.add_argument("--base", default=BASE_ID, help="HF id or local folder of Llama-3.2-3B-Instruct")
    ap.add_argument("--out", required=True)
    ap.add_argument("--session-hours", type=float, default=7.0)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=1280)  # HVAC 12 h prompts reach ~1.1k tokens + ~120 completion
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--dev-n", type=int, default=300)
    ap.add_argument("--save-every", type=int, default=25, help="optimizer steps between checkpoints (~15 min)")
    ap.add_argument("--eval-every", type=int, default=150)
    ap.add_argument("--smoke", action="store_true", help="64 rows, a few steps: end-to-end check")
    ap.add_argument("--pilot", action="store_true", help="measure tokens/s and peak VRAM on the longest rows, then exit")
    ap.add_argument("--thermal-pause-at", type=int, default=81)
    ap.add_argument("--thermal-resume-at", type=int, default=73)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "STOP").unlink(missing_ok=True)  # a STOP left from the previous session must not end this one
    fh = open(out / "train.log", "a", encoding="utf-8")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA not available")
    log(f"=== v2 session start; GPU {torch.cuda.get_device_name(0)}, GPU temp {gpu_temp()} C", fh)
    random.seed(a.seed)
    torch.manual_seed(a.seed)

    man = json.loads((Path(a.data) / "manifest.json").read_text())
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>" if "<|finetune_right_pad_id|>" in tok.get_vocab() else tok.eos_token
    train_rows = read_jsonl(Path(a.data) / "train.jsonl")
    dev_rows = read_jsonl(Path(a.data) / "dev.jsonl")
    if a.smoke:
        train_rows, dev_rows = train_rows[:64], dev_rows[:16]

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                 torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    lora = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    log(f"LoRA r={a.rank}: {sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.1f} M trainable", fh)

    if a.pilot:
        # the longest examples decide whether 6 GB is enough
        rows = sorted(train_rows, key=lambda r: len(r["prompt"]) + len(r["completion"]))[-12:]
        pds = SFTData(rows, tok, a.max_len)
        model.train()
        torch.cuda.reset_peak_memory_stats()
        t_tok, t_time = 0, 0.0
        for i, ex in enumerate(pds.items):
            b = {k: torch.tensor([v], device="cuda") for k, v in ex.items()}
            torch.cuda.synchronize()
            t0 = time.time()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss, _ = sliced_loss(model, b["input_ids"], b["attention_mask"], b["labels"])
            loss.backward()
            torch.cuda.synchronize()
            if i >= 2:
                t_time += time.time() - t0
                t_tok += len(ex["input_ids"])
        tps = t_tok / t_time
        tds = SFTData(train_rows, tok, a.max_len)
        hours = tds.tokens() * a.epochs / tps / 3600
        res = {"tokens_per_s": round(tps), "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
               "longest_tokens": max(len(x["input_ids"]) for x in pds.items), "train_tokens": tds.tokens(),
               "est_training_hours": round(hours, 1), "est_sessions_of_7h": math.ceil(hours / 7)}
        (out / "pilot.json").write_text(json.dumps(res, indent=1))
        log(f"PILOT {res}", fh)
        return

    tds = SFTData(train_rows, tok, a.max_len)
    dds = SFTData(dev_subset(dev_rows, a.dev_n, a.seed), tok, a.max_len)
    plan_path = out / "plan.json"
    if plan_path.exists() and not a.smoke:
        plan = json.loads(plan_path.read_text())
        if plan["train_sha256_16"] != man["splits"]["train"]["sha256_16"] or plan["rank"] != a.rank:
            raise SystemExit("the dataset or rank changed since this run was planned: use a new --out")
    else:
        plan = {"train_rows": len(tds), "train_tokens": tds.tokens(), "epochs": a.epochs, "grad_accum": a.grad_accum,
                "max_steps": math.ceil(len(tds) * a.epochs / a.grad_accum), "rank": a.rank, "lr": a.lr,
                "max_len": a.max_len, "train_sha256_16": man["splits"]["train"]["sha256_16"],
                "dev_sha256_16": man["splits"]["dev"]["sha256_16"], "planned_at": f"{datetime.now():%Y-%m-%d %H:%M}"}
        if a.smoke:
            plan["max_steps"] = 6
        plan_path.write_text(json.dumps(plan, indent=1))
    log(f"plan {plan}", fh)

    targs = TrainingArguments(
        output_dir=str(out / "checkpoints"), max_steps=plan["max_steps"], per_device_train_batch_size=1,
        per_device_eval_batch_size=1, gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr,
        lr_scheduler_type="cosine", warmup_ratio=0.03, weight_decay=0.0, max_grad_norm=1.0, bf16=True,
        optim="paged_adamw_8bit", logging_steps=5, eval_strategy="steps", eval_steps=2 if a.smoke else a.eval_every,
        save_strategy="steps", save_steps=2 if a.smoke else a.save_every, save_total_limit=4, load_best_model_at_end=False,
        report_to="none", seed=a.seed, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        remove_unused_columns=False, dataloader_num_workers=0, group_by_length=False, prediction_loss_only=True)
    therm = ThermalGuard(a.thermal_pause_at, a.thermal_resume_at, fh)
    trainer = SlicedTrainer(model=model, args=targs, train_dataset=tds, eval_dataset=dds,
                            data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                            callbacks=[SessionGuard(out, 2 if a.smoke else a.session_hours, fh), BestAdapter(out, fh), therm,
                                       DutyThrottle(out)])
    ckpts = sorted((out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    if ckpts:
        # the Trainer restores save/eval/logging intervals from the checkpoint's trainer_state.json, so a new
        # --save-every would be ignored on resume (seen 2026-10-17: kept 25 instead of 14); write ours into it
        sp = ckpts[-1] / "trainer_state.json"
        st = json.loads(sp.read_text())
        st.update(save_steps=targs.save_steps, eval_steps=targs.eval_steps, logging_steps=targs.logging_steps)
        sp.write_text(json.dumps(st, indent=2))
    t0 = time.time()
    trainer.train(resume_from_checkpoint=str(ckpts[-1]) if ckpts else None)
    step, total = trainer.state.global_step, plan["max_steps"]
    log(f"session ended at step {step}/{total} after {(time.time() - t0) / 3600:.2f} h; thermal pauses {therm.pauses} "
        f"({therm.paused_s / 60:.1f} min), peak GPU {therm.peak} C", fh)
    status = {"step": step, "max_steps": total, "done": step >= total, "ended": f"{datetime.now():%Y-%m-%d %H:%M}"}
    if step >= total:
        trainer.save_model(str(out / "adapter"))
        tok.save_pretrained(str(out / "adapter"))
        meta = {"base_model": a.base, "plan": plan, "best": json.loads((out / "best.json").read_text()) if (out / "best.json").exists() else None,
                "lora": {"r": a.rank, "alpha": 2 * a.rank, "targets": sorted(lora.target_modules)},
                "finished": status["ended"], "log_history": trainer.state.log_history}
        (out / "adapter" / "training_meta.json").write_text(json.dumps(meta, indent=1, default=str))
        log("TRAINING COMPLETE: final adapter in adapter/, best dev-loss adapter in best_adapter/", fh)
    (out / "session_status.json").write_text(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
