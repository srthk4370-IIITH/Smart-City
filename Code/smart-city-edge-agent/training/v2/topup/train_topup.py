"""v2 top-up: continue the finished v2 LoRA (agents_v2/adapter, step 4494) for a short targeted run.

* Same QLoRA setup as train_v2.py (nf4 base, r=32/alpha 64 on all 7 projections, sliced loss on the assistant
  tokens, max_len 1280, grad-accum 16, paged AdamW 8-bit) - the LoRA weights START from the v2 adapter
  (is_trainable), the optimizer is fresh: LR 0.4x the original (8e-5), 20 warmup steps, cosine to 0.
* One pass over gen_topup's train.jsonl (68% replay of the original train set, 32% targeted).
* Checkpoint every 25 steps (all kept); every 50 steps dev loss on BOTH the original dev subset
  (dev_subset(dev, 200, 42), exactly the v2 training eval set) and a targeted dev subset (dev_target, 160).
  Step 0 is evaluated first (baseline). Forgetting guard: orig dev loss > 1.03 x baseline -> checkpoint + stop.
* Stop cleanly on <out>/STOP; thermal pauses as start_v2.sh (76 / 68 C). Resumable from the newest checkpoint.
* At the end: final adapter in adapter/, evals.jsonl, choice.json (rule: lowest targeted dev loss among steps whose
  original dev loss <= 1.02 x baseline; else the lowest original dev loss).

  python train_topup.py --out ~/smartcity_runs/agents_v2_topup
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import torch
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq,
                          TrainerCallback, TrainingArguments)
from peft import PeftModel, prepare_model_for_kbit_training

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
from train_agents import SFTData, SlicedTrainer, ThermalGuard, gpu_temp, log, read_jsonl  # noqa: E402
from train_v2 import SessionGuard, dev_subset  # noqa: E402


class EvalLog(TrainerCallback):
    """Records every evaluation (both dev sets) and enforces the forgetting guard."""

    def __init__(self, out, fh, limit, tw=None):
        self.out, self.fh, self.limit = out, fh, limit
        self.tw = tw or {}  # per-stage targeted sets: {"eval_t_early_loss": rows, ...} -> eval_target_loss = weighted mean
        self.base = json.loads((out / "baseline.json").read_text()) if (out / "baseline.json").exists() else None

    def on_evaluate(self, args, state, control, metrics=None, **kw):
        m = metrics or {}
        keys = [k for k in m if k.startswith("eval_") and k.endswith("_loss")]
        if not keys:
            return
        rec = {"step": state.global_step, "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
        for k in keys:
            rec[k] = round(float(m[k]), 6)
        # the Trainer calls on_evaluate once per eval set: merge per step
        p = self.out / "evals.jsonl"
        rows = [json.loads(l) for l in open(p)] if p.exists() else []
        cur = next((r for r in rows if r["step"] == rec["step"]), None)
        if cur:
            cur.update(rec)
        else:
            rows.append(rec)
            cur = rec
        if self.tw and "eval_target_loss" not in cur and all(k in cur for k in self.tw):
            cur["eval_target_loss"] = round(sum(cur[k] * w for k, w in self.tw.items()) / sum(self.tw.values()), 6)
            rec["eval_target_loss"] = cur["eval_target_loss"]
            log(f"EVAL step {rec['step']}: per stage " + ", ".join(f"{k[7:-5]} {cur[k]:.5f}" for k in self.tw), self.fh)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        if self.base and "eval_orig_loss" in rec:
            rel = rec["eval_orig_loss"] / self.base["eval_orig_loss"] - 1
            log(f"EVAL step {rec['step']}: orig dev {rec['eval_orig_loss']:.5f} ({rel * 100:+.2f}% vs baseline "
                f"{self.base['eval_orig_loss']:.5f})", self.fh)
            if rel > self.limit:
                log(f"FORGETTING GUARD: original dev loss up {rel * 100:.2f}% (> {self.limit * 100:.0f}%): "
                    "checkpoint and stop", self.fh)
                (self.out / "FORGETTING.json").write_text(json.dumps({"step": rec["step"], "rel": rel, **rec}, indent=1))
                (self.out / "STOP").write_text("forgetting guard")
                control.should_training_stop = True
                control.should_save = True
        if "eval_target_loss" in rec:
            log(f"EVAL step {rec['step']}: targeted dev {rec['eval_target_loss']:.5f}", self.fh)


def choose(out, base, max_steps):
    rows = [json.loads(l) for l in open(out / "evals.jsonl")]
    rows = [r for r in rows if "eval_orig_loss" in r and "eval_target_loss" in r and r["step"] > 0]
    ok = [r for r in rows if r["eval_orig_loss"] <= 1.02 * base["eval_orig_loss"]
          and r["eval_target_loss"] < base["eval_target_loss"]]
    pick = min(ok, key=lambda r: (r["eval_target_loss"], -r["step"])) if ok else min(rows, key=lambda r: r["eval_orig_loss"])
    step = pick["step"]
    adir = out / "adapter" if step >= max_steps else out / "checkpoints" / f"checkpoint-{step}"
    choice = {"chosen": f"step_{step}", "step": step, "adapter_dir": str(adir), "passes": bool(ok),
              "passes_rule": "original dev loss <= 1.02 x baseline AND targeted dev loss < baseline (post pipeline only if true)",
              "rule": "lowest targeted dev loss among evaluated steps with original dev loss <= 1.02 x baseline "
                      "(step 0 = v2 adapter step 4494); none -> lowest original dev loss",
              "baseline": base, "picked": pick, "candidates": rows, "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    (out / "choice.json").write_text(json.dumps(choice, indent=1))
    return choice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=None, help="default <out>/data")
    ap.add_argument("--init-adapter", default=str(Path.home() / "smartcity_runs/agents_v2/adapter"))
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--lr", type=float, default=8e-5)          # 0.4 x the original 2e-4
    ap.add_argument("--warmup-steps", type=int, default=20)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=1280)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--eval-every", type=int, default=50)
    ap.add_argument("--dev-n", type=int, default=200)
    ap.add_argument("--target-dev-n", type=int, default=160)
    ap.add_argument("--forget-limit", type=float, default=0.03)
    ap.add_argument("--thermal-pause-at", type=int, default=76)
    ap.add_argument("--thermal-resume-at", type=int, default=68)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--init-step", type=int, default=4494, help="recorded in plan.json only")
    ap.add_argument("--deadline", default=None, help="YYYY-MM-DDTHH:MM: checkpoint, evaluate and finish by then")
    ap.add_argument("--stage-evals", action="store_true", help="targeted dev = all dev_target rows, one eval set per stage")
    a = ap.parse_args()

    out = Path(a.out).expanduser()
    data = Path(a.data).expanduser() if a.data else out / "data"
    if a.smoke:
        out = out.parent / (out.name + "_smoke")
    out.mkdir(parents=True, exist_ok=True)
    assert "agents_v2_topup" in str(out), "refusing to write outside an agents_v2_topup run dir"
    (out / "STOP").unlink(missing_ok=True)
    fh = open(out / "train.log", "a", encoding="utf-8")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA not available")
    log(f"=== v2 top-up session start; GPU {torch.cuda.get_device_name(0)}, GPU temp {gpu_temp()} C", fh)
    random.seed(a.seed)
    torch.manual_seed(a.seed)

    man = json.loads((data / "manifest.json").read_text())
    val = json.loads((data / "validation.json").read_text())
    if not val.get("all_hard_pass"):
        raise SystemExit("data validation did not pass: run validate_topup.py")
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>" if "<|finetune_right_pad_id|>" in tok.get_vocab() else tok.eos_token
    train_rows = read_jsonl(data / "train.jsonl")
    dev_rows = dev_subset(read_jsonl(data / "dev.jsonl"), a.dev_n, a.seed)
    tdev_all = read_jsonl(data / "dev_target.jsonl")
    tdev_rows = tdev_all if a.stage_evals else dev_subset(tdev_all, a.target_dev_n, a.seed)
    if a.smoke:
        train_rows, dev_rows, tdev_rows = train_rows[:48], dev_rows[:8], tdev_rows[:8]

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                 torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
    cfg = model.peft_config["default"]
    log(f"init adapter {a.init_adapter}: r={cfg.r} alpha={cfg.lora_alpha} targets={sorted(cfg.target_modules)}; "
        f"{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.1f} M trainable", fh)
    assert cfg.r == 32 and cfg.lora_alpha == 64

    tds = SFTData(train_rows, tok, a.max_len)
    eval_sets = {"orig": SFTData(dev_rows, tok, a.max_len)}
    tw = {}
    if a.stage_evals:
        for stg, nm in (("early", "t_early"), ("1.5h", "t_15h"), ("3h", "t_3h"), ("other", "t_other")):
            rs = [r for r in tdev_rows if r.get("stage") == stg]
            if rs:
                eval_sets[nm] = SFTData(rs, tok, a.max_len)
                tw[f"eval_{nm}_loss"] = len(rs)
    else:
        eval_sets["target"] = SFTData(tdev_rows, tok, a.max_len)
    deadline = datetime.strptime(a.deadline, "%Y-%m-%dT%H:%M") if a.deadline else None
    hours = max(0.05, (deadline - datetime.now()).total_seconds() / 3600) if deadline else 1000
    plan_path = out / "plan.json"
    if plan_path.exists() and not a.smoke:
        plan = json.loads(plan_path.read_text())
        if plan["train_sha256_16"] != man["splits"]["train"]["sha256_16"]:
            raise SystemExit("the top-up dataset changed since this run was planned: use a new --out")
    else:
        plan = {"init_adapter": a.init_adapter, "init_step": a.init_step, "stage_evals": tw, "deadline": a.deadline, "train_rows": len(tds), "train_tokens": tds.tokens(),
                "epochs": a.epochs, "grad_accum": a.grad_accum, "max_steps": math.ceil(len(tds) * a.epochs / a.grad_accum),
                "rank": 32, "lr": a.lr, "warmup_steps": a.warmup_steps, "scheduler": "cosine", "max_len": a.max_len,
                "eval_every": a.eval_every, "save_every": a.save_every, "dev_orig_rows": len(dev_rows),
                "dev_target_rows": len(tdev_rows), "forget_limit": a.forget_limit,
                "train_sha256_16": man["splits"]["train"]["sha256_16"], "dev_target_sha256_16": man["splits"]["dev_target"]["sha256_16"],
                "dev_sha256_16": man["splits"]["dev"]["sha256_16"], "planned_at": f"{datetime.now():%Y-%m-%d %H:%M}"}
        if a.smoke:
            plan["max_steps"] = 4
        plan_path.write_text(json.dumps(plan, indent=1))
    log(f"plan {plan}", fh)

    targs = TrainingArguments(
        output_dir=str(out / "checkpoints"), max_steps=plan["max_steps"], per_device_train_batch_size=1,
        per_device_eval_batch_size=1, gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr,
        lr_scheduler_type="cosine", warmup_steps=a.warmup_steps, weight_decay=0.0, max_grad_norm=1.0, bf16=True,
        optim="paged_adamw_8bit", logging_steps=5, eval_strategy="steps", eval_steps=2 if a.smoke else a.eval_every,
        save_strategy="steps", save_steps=2 if a.smoke else a.save_every, save_total_limit=None, load_best_model_at_end=False,
        report_to="none", seed=a.seed, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        remove_unused_columns=False, dataloader_num_workers=0, group_by_length=False, prediction_loss_only=True)
    therm = ThermalGuard(a.thermal_pause_at, a.thermal_resume_at, fh)
    trainer = SlicedTrainer(model=model, args=targs, train_dataset=tds, eval_dataset=eval_sets,
                            data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                            callbacks=[SessionGuard(out, hours, fh), therm])
    ckpts = sorted((out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    if not (out / "baseline.json").exists():
        log("baseline eval (step 0 = v2 adapter step 4494) on both dev sets", fh)
        t0 = time.time()
        m = trainer.evaluate()
        if tw:
            m["eval_target_loss"] = sum(m[k] * w for k, w in tw.items()) / sum(tw.values())
        base = {"eval_orig_loss": float(m["eval_orig_loss"]), "eval_target_loss": float(m["eval_target_loss"]),
                **{k: float(m[k]) for k in tw}, "seconds": round(time.time() - t0, 1), "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
        (out / "baseline.json").write_text(json.dumps(base, indent=1))
        with open(out / "evals.jsonl", "a") as f:
            f.write(json.dumps({"step": 0, "eval_orig_loss": round(base["eval_orig_loss"], 6),
                                **{k: round(v, 6) for k, v in base.items() if k.startswith("eval_") and k != "eval_orig_loss"}, "at": base["at"]}) + "\n")
        log(f"BASELINE {base}", fh)
    trainer.add_callback(EvalLog(out, fh, a.forget_limit, tw))
    if ckpts:
        sp = ckpts[-1] / "trainer_state.json"
        st = json.loads(sp.read_text())
        st.update(save_steps=targs.save_steps, eval_steps=targs.eval_steps, logging_steps=targs.logging_steps)
        sp.write_text(json.dumps(st, indent=2))
    t0 = time.time()
    trainer.train(resume_from_checkpoint=str(ckpts[-1]) if ckpts else None)
    step, total = trainer.state.global_step, plan["max_steps"]
    log(f"session ended at step {step}/{total} after {(time.time() - t0) / 3600:.2f} h; thermal pauses {therm.pauses} "
        f"({therm.paused_s / 60:.1f} min), peak GPU {therm.peak} C", fh)
    forgot = (out / "FORGETTING.json").exists()
    user_stop = (out / "STOP").exists() and not forgot
    dl_stop = bool(deadline) and step < total and not forgot and not user_stop and datetime.now() >= deadline - timedelta(minutes=30)
    if dl_stop:
        log("DEADLINE reached: evaluating the last checkpoint and finishing", fh)
        evs = [json.loads(l) for l in open(out / "evals.jsonl")]
        if not any(e["step"] == step and "eval_target_loss" in e for e in evs):
            trainer.evaluate()
    status = {"step": step, "max_steps": total, "done": step >= total or forgot or dl_stop, "forgetting_stop": forgot,
              "deadline_stop": dl_stop,
              "ended": f"{datetime.now():%Y-%m-%d %H:%M}"}
    if step >= total:
        m = trainer.evaluate()  # the final step is usually not a multiple of eval_every
        trainer.save_model(str(out / "adapter"))
        tok.save_pretrained(str(out / "adapter"))
        meta = {"base_model": a.base, "plan": plan, "finished": status["ended"], "log_history": trainer.state.log_history}
        (out / "adapter" / "training_meta.json").write_text(json.dumps(meta, indent=1, default=str))
        log("TRAINING COMPLETE: final adapter in adapter/", fh)
    if status["done"]:
        base = json.loads((out / "baseline.json").read_text())
        c = choose(out, base, total)
        log(f"CHOSEN {c['chosen']} -> {c['adapter_dir']} (orig {c['picked']['eval_orig_loss']}, target {c['picked']['eval_target_loss']})", fh)
        status["choice_passes"] = c["passes"]
    (out / "session_status.json").write_text(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
