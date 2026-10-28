"""v2 top-up phase 2c: continue from the phase-1 adapter (agents_v2_topup2 checkpoint-500) with
  * decision-weighted loss: completion tokens carrying the VALUES of pattern / status / likely_cause / event_active /
    fault_kind get weight --decision-weight, every other completion token weight 1 (loss = weighted mean);
  * L2-SP anchor: + --anchor * sum((theta - theta_phase1)^2) over the LoRA parameters (keeps phase-1 knowledge);
  * decision-based evaluation instead of the Trainer's loss eval: every --eval-every steps (and at step 0 =
    phase 1) decision_eval on the original dev subset (whole-text loss + greedy pattern/status/cause/event_active)
    and the per-stage dev sets (early / 1.5h / 3h / other);
  * pass rule (coordinator 2026-10-21): vs step 0 (phase 1), original-dev accuracy of pattern, status and cause each
    drops <= 0.5 pt; stage dev (early, 1.5h, 3h) pattern and status accuracy improve on average with no stage
    dropping > 1 pt in either; whole-text original dev loss <= +3 % (also the forgetting guard: above it -> stop).
Resumable, thermal pauses, STOP file, deadline, as train_topup.py. Writes decisions.jsonl, choice.json,
session_status.json (done / choice_passes).

  python train_topup_c.py --out ~/smartcity_runs/agents_v2_topup3c --init-adapter <phase-1 ckpt> ...
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
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainerCallback, TrainingArguments
from peft import PeftModel, prepare_model_for_kbit_training

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
from train_agents import SlicedTrainer, ThermalGuard, gpu_temp, log, read_jsonl  # noqa: E402
from train_v2 import SessionGuard, dev_subset  # noqa: E402
import decision_eval as DE  # noqa: E402

STAGES = ("early", "s15h", "s3h")


class WData(torch.utils.data.Dataset):
    def __init__(self, rows, tok, max_len, w):
        self.items = []
        for r in rows:
            p = tok(r["prompt"], add_special_tokens=False)["input_ids"]
            c, mask = DE.decision_weights(tok, r["completion"])
            ids = p + c
            if len(ids) > max_len:
                raise SystemExit(f"row longer than {max_len}")
            self.items.append({"input_ids": ids, "labels": [-100] * len(p) + c,
                               "weights": [0.0] * len(p) + [w if m else 1.0 for m in mask]})

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def tokens(self):
        return sum(len(x["input_ids"]) for x in self.items)


def collate(b):
    assert len(b) == 1
    x = b[0]
    ids = torch.tensor([x["input_ids"]])
    return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": torch.tensor([x["labels"]]),
            "weights": torch.tensor([x["weights"]])}


class CTrainer(SlicedTrainer):
    anchor = 0.0
    ref = None

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs["labels"]
        c = int((labels[0] != -100).sum())
        out = model(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], num_logits_to_keep=c + 1)
        logits = out.logits[:, :-1, :].float()
        tgt = labels[:, -c:]
        ce = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), reduction="none")
        w = inputs["weights"][:, -c:].reshape(-1).to(ce.dtype)
        loss = (ce * w).sum() / w.sum()
        if self.anchor and self.ref is not None and model.training:
            pen = sum(((p - r) ** 2).sum() for p, r in zip(self.params, self.ref))
            loss = loss + self.anchor * pen
        return (loss, out) if return_outputs else loss


def acc3(m):
    return {k: m.get(f"acc_{k}") for k in ("pattern", "status", "likely_cause")}


def passes(rec, base, forget):
    """the coordinator's decision-based rule; returns (bool, reasons)."""
    why = []
    o, ob = rec["orig"], base["orig"]
    for k in ("pattern", "status", "likely_cause"):
        if o[f"acc_{k}"] < ob[f"acc_{k}"] - 0.005 - 1e-9:
            why.append(f"orig {k} {ob[f'acc_{k}']:.3f}->{o[f'acc_{k}']:.3f}")
    # "stage-dev decision accuracy improves (pattern and status) on average": the mean over the 3 stages x
    # {pattern, status} must rise; no stage may drop > 1 pt in either field
    alld = []
    for k in ("pattern", "status"):
        d = [rec[s][f"acc_{k}"] - base[s][f"acc_{k}"] for s in STAGES]
        alld += d
        for s, x in zip(STAGES, d):
            if x < -0.01 - 1e-9:
                why.append(f"{s} {k} {x * 100:+.1f} pt")
    if sum(alld) / len(alld) <= 0:
        why.append(f"stage pattern+status mean change {sum(alld) / len(alld) * 100:+.2f} pt (must improve)")
    if o["loss_all"] > (1 + forget) * ob["loss_all"]:
        why.append(f"orig loss {o['loss_all'] / ob['loss_all'] * 100 - 100:+.2f}%")
    return not why, why


def score(rec, base):
    return sum(rec[s][f"acc_{k}"] - base[s][f"acc_{k}"] for s in STAGES for k in ("pattern", "status"))


class DecisionEval(TrainerCallback):
    def __init__(self, out, fh, tok, sets, every, forget, batch):
        self.out, self.fh, self.tok, self.sets, self.every, self.forget, self.batch = out, fh, tok, sets, every, forget, batch
        self.path = out / "decisions.jsonl"

    def records(self):
        return [json.loads(l) for l in open(self.path)] if self.path.exists() else []

    def run(self, model, step):
        if any(r["step"] == step for r in self.records()):
            return
        was = model.training
        model.eval()
        model.config.use_cache = True
        t0 = time.time()
        rec = {"step": step, "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
        for name, rows in self.sets.items():
            m = DE.evaluate(model, self.tok, rows, self.batch)
            m.pop("_texts", None)
            rec[name] = m
        rec["seconds"] = round(time.time() - t0, 1)
        model.config.use_cache = False
        if was:
            model.train()
        base = self.records()[0] if self.records() else rec
        ok, why = passes(rec, base, self.forget) if step else (None, [])
        rec["passes"], rec["why_not"] = ok, why
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        s = " | ".join(f"{n}: pat {rec[n]['acc_pattern']:.3f} st {rec[n]['acc_status']:.3f} cause {rec[n]['acc_likely_cause']:.3f}"
                       f" loss {rec[n]['loss_all']:.4f}/{rec[n]['loss_decision']:.4f}" for n in self.sets)
        log(f"DECISION EVAL step {step} ({rec['seconds']:.0f}s): {s}; passes={ok} {why}", self.fh)
        return rec

    def on_step_end(self, args, state, control, model=None, **kw):
        if state.global_step % self.every == 0 and state.global_step:
            rec = self.run(model, state.global_step)
            base = self.records()[0]
            if rec and rec["orig"]["loss_all"] > (1 + self.forget) * base["orig"]["loss_all"]:
                log(f"FORGETTING GUARD: orig loss {rec['orig']['loss_all']:.5f} > +{self.forget * 100:.0f}% of "
                    f"{base['orig']['loss_all']:.5f}: checkpoint and stop", self.fh)
                (self.out / "FORGETTING.json").write_text(json.dumps(rec, indent=1))
                control.should_training_stop = True
                control.should_save = True


def choose(out, max_steps):
    recs = [json.loads(l) for l in open(out / "decisions.jsonl")]
    base, cand = recs[0], [r for r in recs[1:]]
    ok = [r for r in cand if r.get("passes")]
    pick = max(ok, key=lambda r: (score(r, base), -r["orig"]["loss_all"])) if ok else None
    step = pick["step"] if pick else None
    adir = None
    if pick:
        adir = out / "checkpoints" / f"checkpoint-{step}"
        if not (adir / "adapter_model.safetensors").exists():
            adir = out / "adapter"
    c = {"chosen": f"step_{step}" if pick else None, "step": step, "adapter_dir": str(adir) if adir else None,
         "passes": bool(ok), "rule": "decision rule (see passes()); among passing steps the largest stage pattern+status gain",
         "baseline_step0": base, "picked": pick, "candidates": [{"step": r["step"], "passes": r.get("passes"), "why_not": r.get("why_not")} for r in cand],
         "at": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    (out / "choice.json").write_text(json.dumps(c, indent=1, default=str))
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=None)
    ap.add_argument("--init-adapter", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--warmup-steps", type=int, default=30)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=1280)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--eval-every", type=int, default=50)
    ap.add_argument("--decision-weight", type=float, default=4.0)
    ap.add_argument("--anchor", type=float, default=0.0)
    ap.add_argument("--forget-limit", type=float, default=0.03)
    ap.add_argument("--eval-batch", type=int, default=6)
    ap.add_argument("--thermal-pause-at", type=int, default=76)
    ap.add_argument("--thermal-resume-at", type=int, default=68)
    ap.add_argument("--deadline", default=None, help="YYYY-MM-DDTHH:MM")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    data = Path(a.data).expanduser() if a.data else out / "data"
    if a.smoke:
        out = out.parent / (out.name + "_smoke")
    out.mkdir(parents=True, exist_ok=True)
    assert "agents_v2_topup" in str(out)
    (out / "STOP").unlink(missing_ok=True)
    fh = open(out / "train.log", "a", encoding="utf-8")
    log(f"=== v2 top-up 2c session start; GPU temp {gpu_temp()} C", fh)
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    man = json.loads((data / "manifest.json").read_text())
    if not json.loads((data / "validation.json").read_text()).get("all_hard_pass"):
        raise SystemExit("data validation did not pass")
    tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    train_rows = read_jsonl(data / "train.jsonl")
    t = read_jsonl(data / "dev_target.jsonl")
    sets = {"orig": dev_subset(read_jsonl(data / "dev.jsonl"), 200, a.seed),
            "early": [r for r in t if r.get("stage") == "early"], "s15h": [r for r in t if r.get("stage") == "1.5h"],
            "s3h": [r for r in t if r.get("stage") == "3h"], "other": [r for r in t if r.get("stage") == "other"]}
    if a.smoke:
        train_rows = train_rows[:48]
        sets = {k: v[:6] for k, v in sets.items()}
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, quantization_config=quant,
                                                 torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
    cfg = model.peft_config["default"]
    assert cfg.r == 32 and cfg.lora_alpha == 64
    params = [p for p in model.parameters() if p.requires_grad]
    log(f"init adapter {a.init_adapter}: {sum(p.numel() for p in params) / 1e6:.1f} M trainable", fh)
    tds = WData(train_rows, tok, a.max_len, a.decision_weight)
    plan_path = out / "plan.json"
    if plan_path.exists() and not a.smoke:
        plan = json.loads(plan_path.read_text())
        if plan["train_sha256_16"] != man["splits"]["train"]["sha256_16"]:
            raise SystemExit("dataset changed: use a new --out")
    else:
        plan = {"init_adapter": a.init_adapter, "train_rows": len(tds), "train_tokens": tds.tokens(), "epochs": a.epochs,
                "grad_accum": a.grad_accum, "max_steps": math.ceil(len(tds) * a.epochs / a.grad_accum), "lr": a.lr,
                "warmup_steps": a.warmup_steps, "scheduler": "cosine", "decision_weight": a.decision_weight, "anchor": a.anchor,
                "eval_every": a.eval_every, "save_every": a.save_every, "forget_limit": a.forget_limit, "deadline": a.deadline,
                "eval_sets": {k: len(v) for k, v in sets.items()}, "train_sha256_16": man["splits"]["train"]["sha256_16"],
                "planned_at": f"{datetime.now():%Y-%m-%d %H:%M}"}
        if a.smoke:
            plan["max_steps"] = 2
        plan_path.write_text(json.dumps(plan, indent=1))
    log(f"plan {plan}", fh)
    deadline = datetime.strptime(a.deadline, "%Y-%m-%dT%H:%M") if a.deadline else None
    hours = max(0.05, (deadline - datetime.now()).total_seconds() / 3600) if deadline else 1000
    targs = TrainingArguments(
        output_dir=str(out / "checkpoints"), max_steps=plan["max_steps"], per_device_train_batch_size=1,
        gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr, lr_scheduler_type="cosine", warmup_steps=a.warmup_steps,
        weight_decay=0.0, max_grad_norm=1.0, bf16=True, optim="paged_adamw_8bit", logging_steps=5, eval_strategy="no",
        save_strategy="steps", save_steps=1 if a.smoke else a.save_every, save_total_limit=None, report_to="none", seed=a.seed,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}, remove_unused_columns=False,
        dataloader_num_workers=0)
    CTrainer.anchor = a.anchor
    dec = DecisionEval(out, fh, tok, sets, 1 if a.smoke else a.eval_every, a.forget_limit, a.eval_batch)
    therm = ThermalGuard(a.thermal_pause_at, a.thermal_resume_at, fh)
    trainer = CTrainer(model=model, args=targs, train_dataset=tds, data_collator=collate,
                       callbacks=[SessionGuard(out, hours, fh), therm, dec])
    trainer.params = params
    trainer.ref = [p.detach().clone() for p in params] if a.anchor else None  # phase-1 values (before any resume)
    ckpts = sorted((out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    if not dec.records():
        log("step-0 decision eval (= phase 1)", fh)
        dec.run(model, 0)
    if ckpts:
        sp = ckpts[-1] / "trainer_state.json"
        st = json.loads(sp.read_text())
        st.update(save_steps=targs.save_steps, logging_steps=targs.logging_steps)
        sp.write_text(json.dumps(st, indent=2))
    t0 = time.time()
    trainer.train(resume_from_checkpoint=str(ckpts[-1]) if ckpts else None)
    step, total = trainer.state.global_step, plan["max_steps"]
    log(f"session ended at step {step}/{total} after {(time.time() - t0) / 3600:.2f} h; thermal pauses {therm.pauses}", fh)
    forgot = (out / "FORGETTING.json").exists()
    user_stop = (out / "STOP").exists() and not forgot
    dl_stop = bool(deadline) and step < total and not forgot and not user_stop and datetime.now() >= deadline - timedelta(minutes=30)
    status = {"step": step, "max_steps": total, "done": step >= total or forgot or dl_stop, "forgetting_stop": forgot,
              "deadline_stop": dl_stop, "ended": f"{datetime.now():%Y-%m-%d %H:%M}"}
    if status["done"]:
        if step % a.eval_every and not forgot:
            trainer.save_model(str(out / "checkpoints" / f"checkpoint-{step}"))
            dec.run(model, step)
        if step >= total:
            trainer.save_model(str(out / "adapter"))
        c = choose(out, total)
        status["choice_passes"] = c["passes"]
        log(f"CHOSEN {c['chosen']} -> {c['adapter_dir']} (passes={c['passes']})", fh)
    (out / "session_status.json").write_text(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
