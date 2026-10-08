"""QLoRA fine-tuning of Llama 3.2 3B Instruct as the multi-role domain agent.

* Measures real throughput with a no-update pilot (forward+backward, no optimizer step),
  then sizes the run so it finishes before --deadline (minus --reserve-hours for eval+merge).
* Plan A: all 5 roles (air_quality, water, power, occupancy, weather), pattern-balanced.
  Plan B (auto fallback): air_quality only, trained fully.
* A time-guard callback stops training cleanly if the projected finish slips past the deadline.
* Prompts are tokenized exactly as the device sends them (raw Llama-3 string, add_special_tokens=False);
  loss only on the assistant JSON + <|eot_id|>.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import torch
from torch.utils.data import Dataset
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq,
                          Trainer, TrainerCallback, TrainingArguments)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

BASE_ID = "meta-llama/Llama-3.2-3B-Instruct"
ROLES = ("air_quality", "water", "power", "occupancy", "weather")


def log(msg, fh=None):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    if fh:
        fh.write(line + "\n"); fh.flush()


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def stratified(rows, n_per_role, roles, seed):
    rng = random.Random(seed)
    out = []
    for role in roles:
        by_p = defaultdict(list)
        for r in rows:
            if r["role"] == role:
                by_p[r["pattern"]].append(r)
        pats = sorted(by_p)
        for p in pats:
            rng.shuffle(by_p[p])
        take, i = [], 0
        while len(take) < n_per_role and any(by_p[p] for p in pats):
            p = pats[i % len(pats)]
            if by_p[p]:
                take.append(by_p[p].pop())
            i += 1
        out.extend(take)
    rng.shuffle(out)
    return out


class SFTData(Dataset):
    def __init__(self, rows, tok, max_len):
        self.items = []
        for r in rows:
            p = tok(r["prompt"], add_special_tokens=False)["input_ids"]
            c = tok(r["completion"], add_special_tokens=False)["input_ids"]
            ids = p + c
            if len(ids) > max_len:
                raise SystemExit(f"example longer than max_len={max_len}: {len(ids)} tokens ({r['role']}/{r['pattern']})")
            self.items.append({"input_ids": ids, "attention_mask": [1] * len(ids), "labels": [-100] * len(p) + c})

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def tokens(self):
        return sum(len(x["input_ids"]) for x in self.items)


def sliced_loss(model, input_ids, attention_mask, labels):
    """Loss on the assistant tokens only, computing logits ONLY for those positions
    (num_logits_to_keep) -> avoids materialising 128k-vocab logits for the whole prompt (OOM on 6 GB)."""
    c = int((labels[0] != -100).sum())
    out = model(input_ids=input_ids, attention_mask=attention_mask, num_logits_to_keep=c + 1)
    logits = out.logits[:, :-1, :].float()
    target = labels[:, -c:]
    return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), target.reshape(-1)), out


class SlicedTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        loss, out = sliced_loss(model, inputs["input_ids"], inputs["attention_mask"], inputs["labels"])
        return (loss, out) if return_outputs else loss


def gpu_temp():
    """GPU temperature in C via nvidia-smi (no admin needed); None if unavailable."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15)
        m = re.search(r"\d+", out.stdout)
        return int(m.group()) if m else None
    except Exception:
        return None


class ThermalGuard(TrainerCallback):
    """Pauses training while the GPU is hot.

    The laptop force-hibernates when ACPI zone TZ01 reaches 100 C (observed 2026-10-07, 21 times),
    which kills the run and blanks the display. Holding the GPU below `pause_at` keeps the whole
    chassis far from that limit. Pausing costs time but never changes the maths of a step, so
    accuracy is unaffected.
    """

    def __init__(self, pause_at, resume_at, fh, every=2):
        self.pause_at, self.resume_at, self.fh, self.every = pause_at, resume_at, fh, every
        self.paused_s, self.pauses, self.peak = 0.0, 0, 0

    def on_step_end(self, args, state, control, **kw):
        if state.global_step % self.every:
            return
        t = gpu_temp()
        if t is None:
            return
        self.peak = max(self.peak, t)
        if t < self.pause_at:
            return
        self.pauses += 1
        t0 = time.time()
        log(f"THERMAL: GPU {t} C >= {self.pause_at} C, pausing until {self.resume_at} C", self.fh)
        while time.time() - t0 < 300:
            time.sleep(10)
            t = gpu_temp()
            if t is None or t <= self.resume_at:
                break
        self.paused_s += time.time() - t0
        log(f"THERMAL: resumed at {t} C after {time.time() - t0:.0f}s (total paused {self.paused_s / 60:.1f} min)", self.fh)
        if self.pauses in (5, 20, 50):
            log("THERMAL: pausing often. This laptop locks the GPU power limit, so the levers left are: "
                "raise the back of the laptop, clear the vents, set fans to max in OMEN Gaming Hub.", self.fh)


class TimeGuard(TrainerCallback):
    def __init__(self, deadline, fh):
        self.deadline, self.fh, self.t0 = deadline, fh, None

    def on_train_begin(self, args, state, control, **kw):
        self.t0 = time.time()

    def on_step_end(self, args, state, control, **kw):
        if state.global_step % 5 == 0 and state.global_step > 0:
            el = time.time() - self.t0
            per = el / state.global_step
            eta = datetime.now() + timedelta(seconds=per * (state.max_steps - state.global_step))
            log(f"step {state.global_step}/{state.max_steps}  {per:.1f}s/step  ETA {eta:%a %H:%M}", self.fh)
            if datetime.now() + timedelta(seconds=per * 2) > self.deadline:
                log("TIME GUARD: deadline reached, stopping and saving", self.fh)
                control.should_training_stop = True
                control.should_save = True

    def on_log(self, args, state, control, logs=None, **kw):
        if logs:
            log("metrics " + json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in logs.items()}), self.fh)


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--data", default=str(root / "data" / "sft"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--deadline", required=True, help="local time 'YYYY-MM-DD HH:MM' when eval+merge must be done")
    ap.add_argument("--reserve-hours", type=float, default=1.25, help="time kept for eval + merge after training")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--max-per-role", type=int, default=1296)
    ap.add_argument("--min-per-role", type=int, default=450, help="below this, fall back to one role")
    ap.add_argument("--fallback-role", default="air_quality")
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--pilot-micro", type=int, default=24)
    ap.add_argument("--force-plan", choices=["A", "B"], default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="tiny end-to-end check (3 ex/role, 1 epoch)")
    ap.add_argument("--plan-only", action="store_true", help="run the pilot, print the plan, exit")
    ap.add_argument("--thermal-pause-at", type=int, default=81, help="pause training above this GPU temp (C)")
    ap.add_argument("--thermal-resume-at", type=int, default=73, help="resume training below this GPU temp (C)")
    ap.add_argument("--thermal-derate", type=float, default=0.75,
                    help="fraction of pilot speed assumed when planning, to leave room for thermal pauses")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    fh = open(out / "train.log", "a", encoding="utf-8")
    deadline = datetime.strptime(a.deadline, "%Y-%m-%d %H:%M")
    train_end = deadline - timedelta(hours=a.reserve_hours)
    log(f"deadline {deadline}, training must end by {train_end}", fh)
    if not torch.cuda.is_available():
        raise SystemExit("CUDA not available")
    log(f"GPU {torch.cuda.get_device_name(0)}, {torch.cuda.get_device_properties(0).total_memory / 2**30:.1f} GiB", fh)
    random.seed(a.seed); torch.manual_seed(a.seed)

    tok = AutoTokenizer.from_pretrained(BASE_ID, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>" if "<|finetune_right_pad_id|>" in tok.get_vocab() else tok.eos_token
    train_rows = read_jsonl(Path(a.data) / "train.jsonl")
    dev_rows = read_jsonl(Path(a.data) / "dev.jsonl")

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    log("loading base model (4-bit) ...", fh)
    model = AutoModelForCausalLM.from_pretrained(BASE_ID, local_files_only=True, quantization_config=quant,
                                                 torch_dtype=torch.bfloat16, device_map={"": 0},
                                                 attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    lora = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"LoRA trainable params: {trainable / 1e6:.1f} M", fh)

    plan_path = out / "plan.json"
    if a.smoke:
        plan = {"plan": "SMOKE", "roles": list(ROLES), "per_role": 4, "epochs": 1.0}
        a.grad_accum = 4
        plan_path.write_text(json.dumps(plan, indent=1))
        log(f"SMOKE plan {plan}", fh)
    elif a.resume and plan_path.exists():
        plan = json.loads(plan_path.read_text())
        log(f"resuming with existing plan {plan}", fh)
    else:
        # ---------------- pilot: real tokens/s on this GPU, no weight updates
        pilot_rows = stratified(train_rows, a.pilot_micro // len(ROLES) + 1, ROLES, a.seed + 1)[: a.pilot_micro]
        pds = SFTData(pilot_rows, tok, a.max_len)
        model.train()
        torch.cuda.reset_peak_memory_stats()
        t_tok, t_time = 0, 0.0
        for i, ex in enumerate(pds.items):
            batch = {k: torch.tensor([v], device="cuda") for k, v in ex.items()}
            torch.cuda.synchronize(); t0 = time.time()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss, _ = sliced_loss(model, batch["input_ids"], batch["attention_mask"], batch["labels"])
            loss.backward()
            torch.cuda.synchronize()
            if i >= 3:  # skip warm-up
                t_time += time.time() - t0; t_tok += len(ex["input_ids"])
        model.zero_grad(set_to_none=True)
        tps = t_tok / t_time
        peak = torch.cuda.max_memory_allocated() / 2**30
        log(f"PILOT: {tps:.0f} tokens/s fwd+bwd, peak VRAM {peak:.2f} GiB", fh)

        avg_tok = SFTData(stratified(train_rows, 40, ROLES, a.seed), tok, a.max_len).tokens() / (40 * len(ROLES))
        avail = (train_end - datetime.now()).total_seconds() * 0.92  # 8 % margin for optimizer/eval/checkpoints
        log(f"avg tokens/example {avg_tok:.0f}; usable training time {avail / 3600:.2f} h", fh)
        if avail <= 0:
            raise SystemExit("deadline already passed for training")
        budget_examples = avail * tps * a.thermal_derate / (avg_tok * a.epochs)
        log(f"planning at {a.thermal_derate:.0%} of pilot speed to leave room for thermal pauses", fh)
        per_role_A = int(min(a.max_per_role, budget_examples / len(ROLES)))
        if a.force_plan == "A" or (a.force_plan is None and per_role_A >= a.min_per_role):
            plan = {"plan": "A", "roles": list(ROLES), "per_role": per_role_A, "epochs": a.epochs}
        else:
            n_fb = sum(1 for r in train_rows if r["role"] == a.fallback_role)
            ep = 3.0 if budget_examples / 3.0 >= min(n_fb, 900) else a.epochs
            per = int(min(n_fb, budget_examples / ep))
            if per < 200:
                ep = 1.0; per = int(min(n_fb, budget_examples))
            plan = {"plan": "B", "roles": [a.fallback_role], "per_role": per, "epochs": ep}
        plan.update({"thermal_derate": a.thermal_derate, "pilot_tokens_per_s": round(tps, 1), "pilot_peak_vram_gib": round(peak, 2),
                     "avg_tokens_per_example": round(avg_tok, 1), "planned_at": f"{datetime.now():%Y-%m-%d %H:%M}",
                     "train_end_by": f"{train_end:%Y-%m-%d %H:%M}"})
        plan_path.write_text(json.dumps(plan, indent=1))
        log(f"PLAN {plan}", fh)
        if a.plan_only:
            return

    rows = stratified(train_rows, plan["per_role"], plan["roles"], a.seed)
    dev = stratified(dev_rows, 16, plan["roles"], a.seed)
    tds, dds = SFTData(rows, tok, a.max_len), SFTData(dev, tok, a.max_len)
    steps = math.ceil(len(tds) * plan["epochs"] / a.grad_accum)
    log(f"train examples {len(tds)} ({tds.tokens() / 1e6:.2f} M tokens), dev {len(dds)}, optimizer steps {steps}", fh)
    (out / "train_ids.json").write_text(json.dumps([f"{r['node']}|{r['metric']}|{r['end_epoch']}|{r['pattern']}" for r in rows]))

    eval_every = max(20, min(50, steps // 12))  # checkpoint ~every 20 min so a crash costs little
    targs = TrainingArguments(
        output_dir=str(out / "checkpoints"), max_steps=steps, per_device_train_batch_size=1,
        per_device_eval_batch_size=1, gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr,
        lr_scheduler_type="cosine", warmup_ratio=0.03, weight_decay=0.0, max_grad_norm=1.0,
        bf16=True, optim="paged_adamw_8bit", logging_steps=5, eval_strategy="steps", eval_steps=eval_every,
        save_strategy="steps", save_steps=eval_every, save_total_limit=3, load_best_model_at_end=True,
        metric_for_best_model="eval_loss", greater_is_better=False, report_to="none", seed=a.seed,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        remove_unused_columns=False, dataloader_num_workers=0, group_by_length=False,
        prediction_loss_only=True)
    collator = DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100)
    therm = ThermalGuard(a.thermal_pause_at, a.thermal_resume_at, fh)
    log(f"thermal guard: pause at {a.thermal_pause_at} C, resume at {a.thermal_resume_at} C (GPU now {gpu_temp()} C)", fh)
    trainer = SlicedTrainer(model=model, args=targs, train_dataset=tds, eval_dataset=dds, data_collator=collator,
                      callbacks=[TimeGuard(train_end, fh), therm])
    ckpts = sorted((out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1])) if a.resume else []
    t0 = time.time()
    trainer.train(resume_from_checkpoint=str(ckpts[-1]) if ckpts else None)
    log(f"training finished in {(time.time() - t0) / 3600:.2f} h; thermal pauses {therm.pauses} "
        f"({therm.paused_s / 60:.1f} min), peak GPU {therm.peak} C", fh)
    adapter_dir = out / "adapter"
    trainer.save_model(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    hist = [h for h in trainer.state.log_history]
    meta = {"base_model": BASE_ID, "plan": plan,
            "thermal": {"pauses": therm.pauses, "paused_minutes": round(therm.paused_s / 60, 1), "peak_gpu_c": therm.peak}, "train_examples": len(tds), "optimizer_steps": trainer.state.global_step,
            "best_checkpoint": trainer.state.best_model_checkpoint, "best_eval_loss": trainer.state.best_metric,
            "lora": {"r": a.rank, "alpha": 2 * a.rank, "targets": lora.target_modules and sorted(lora.target_modules)},
            "lr": a.lr, "max_len": a.max_len, "finished": f"{datetime.now():%Y-%m-%d %H:%M}", "log_history": hist}
    (adapter_dir / "training_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    log(f"adapter saved to {adapter_dir}", fh)


if __name__ == "__main__":
    main()
