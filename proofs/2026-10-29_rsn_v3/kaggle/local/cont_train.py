"""rsn_v3 continuation of a trained LoRA adapter (PLAN_V2 stage 3 repair phase: --mode sft; stage 4 preference step: --mode dpo).
Single GPU (laptop). Reuses train_rsn3.py's row encoding (loss on the current turn only), its loss (hidden states once, lm_head
+ CE only at label positions, checkpointed chunks: never the full-vocab logits) and its generation dev score (gen_slices /
gen_score: 40 incident dev rows parse/severity/label + 40 chat dev records verify_chat), so scores compare with epoch 1.

--mode sft  rows file (repair rows + epoch-1 replay, repair_lib.py mix); LR 5e-5 (PLAN_V2), warmup 3 % + cosine to 0.1 x.
--mode dpo  pairs file (repair_lib.py pairs: chosen / rejected message lists on one prompt); DPO (Rafailov et al. 2023) with
            beta --beta; the reference is the starting adapter: its log-probs are computed once before step 1 (ref_logps.jsonl,
            resumable), so only one model is in memory. Dropout off. Per pair the exact DPO gradient is applied in two
            backward passes (chosen, rejected; weight beta * sigmoid(-z) from a no-grad pass), so memory = one sequence.
            Optional --sft-alpha: + alpha x chosen NLL (per token). A --val-frac slice of the pairs is held out for reward
            accuracy / loss at every evaluation.
Both: the starting adapter's dev score is measured first (step 0); best-K checkpoints by the dev score (ckpt_best_XXXX,
best.json) and only checkpoints that beat the start are kept; early stop after --patience evaluations without a better score;
--hours wall cap / STOP file -> ckpt_latest (resume: adapter + optimizer + scheduler + step + RNG; schedule.json = data cursor).
Exit codes (as train_rsn3.py): 0 done (ckpt_final), 3 hours limit / STOP, 6 early stop.
  python cont_train.py --mode sft --base B --adapter CKPT --tools tools_v4.json --data mix.jsonl --out DIR --gen-inc F --gen-chat F"""
import argparse
import json
import math
import os
import random
import sys
import time

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import train_rsn3 as T  # noqa: E402  (encode, prep, loss_fn, gen_slices, gen_score, md5)


def log(out, msg):
    T.log(out, msg)


def prep_pairs(tok, path, tools, max_len, out):
    cache = os.path.join(out, "pairs_%s_tok.pt" % T.md5(path))
    if os.path.exists(cache):
        return torch.load(cache)
    data, skipped = [], {}
    for line in open(path, encoding="utf-8"):
        p = json.loads(line)
        enc = []
        for side in ("chosen", "rejected"):
            r, why = T.encode(tok, {"messages": p[side], "think": p.get("think")}, tools.get(p["tools"]), max_len)
            if r is None:
                skipped[side + "_" + why] = skipped.get(side + "_" + why, 0) + 1
                break
            enc.append(r)
        if len(enc) < 2:
            continue
        data.append({"id": p["id"], "kind": p["tools"], "family": p.get("family", ""),
                     "c_ids": torch.tensor(enc[0][0], dtype=torch.int32), "c_lab": torch.tensor(enc[0][1], dtype=torch.int32),
                     "r_ids": torch.tensor(enc[1][0], dtype=torch.int32), "r_lab": torch.tensor(enc[1][1], dtype=torch.int32)})
    torch.save(data, cache + ".part")
    os.replace(cache + ".part", cache)
    print("prep pairs %s: %d kept, skipped %s" % (os.path.basename(path), len(data), skipped), flush=True)
    return data


def logp(model, ids, labels, dev):
    """sum of log p(label tokens) = - train_rsn3.loss_fn sum; second value = label token count"""
    s, n = T.loss_fn(model, ids, labels, dev)
    return -s, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["sft", "dpo"])
    ap.add_argument("--base", required=True)
    ap.add_argument("--model-dir", default="", help="pre-quantized NF4 copy of the base (tokenizer from --base)")
    ap.add_argument("--adapter", required=True, help="starting LoRA checkpoint (adapter_config.json + adapter_model.safetensors)")
    ap.add_argument("--tools", required=True)
    ap.add_argument("--data", required=True, help="sft: rows jsonl; dpo: pairs jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lr", type=float, default=0.0, help="default: sft 5e-5 (PLAN_V2), dpo 5e-6")
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--sft-alpha", type=float, default=0.0)
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--warmup", type=float, default=0.03)
    ap.add_argument("--wd", type=float, default=0.01)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--gen-every", type=int, default=50)
    ap.add_argument("--gen-inc", default="")
    ap.add_argument("--gen-chat", default="")
    ap.add_argument("--gen-train-inc", default="")
    ap.add_argument("--gen-train-chat", default="")
    ap.add_argument("--gen-n", type=int, default=40)
    ap.add_argument("--gen-train-n", type=int, default=20)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--keep-best", type=int, default=3)
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--quant", default="nf4", choices=["nf4", "none"])
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16"])
    ap.add_argument("--limit", type=int, default=0, help="first N rows/pairs only (dry runs)")
    a = ap.parse_args()
    a.lr = a.lr or (5e-5 if a.mode == "sft" else 5e-6)
    os.makedirs(a.out, exist_ok=True)
    CPU = not torch.cuda.is_available()          # CPU = dry runs with a tiny model only
    if CPU:
        dev, DT, a.quant = torch.device("cpu"), torch.float32, "none"
    else:
        dev = torch.device("cuda", 0)
        DT = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
        DT = {"fp16": torch.float16, "bf16": torch.bfloat16}.get(a.dtype, DT)
    SC = torch.amp.GradScaler("cuda", enabled=(DT == torch.float16))
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    tok = AutoTokenizer.from_pretrained(a.base)
    tools = json.load(open(a.tools, encoding="utf-8"))
    tools["none"] = None
    if a.mode == "sft":
        data, _ = T.prep(tok, a.data, tools, a.max_len, a.out, "cont")
    else:
        data = prep_pairs(tok, a.data, tools, a.max_len, a.out)
    if a.limit:
        data = data[:a.limit]
    rows = {d["id"]: d for d in data}
    val = []
    if a.mode == "dpo" and a.val_frac > 0:
        ids = sorted(rows)
        random.Random(77).shuffle(ids)
        val = ids[:max(1, int(a.val_frac * len(ids)))] if len(ids) > 20 else []
    train_ids = [k for k in sorted(rows) if k not in set(val)]

    ck = os.path.join(a.out, "ckpt_latest")
    resume = os.path.exists(os.path.join(ck, "state.pt"))
    torch.manual_seed(1234)
    qc = None
    if a.quant == "nf4":
        qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=DT)
    src = a.model_dir or a.base
    kw = dict(dtype=DT, device_map={"": "cpu" if CPU else 0}, low_cpu_mem_usage=True)
    if not a.model_dir:
        kw["quantization_config"] = qc
    model = AutoModelForCausalLM.from_pretrained(src, **kw)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = PeftModel.from_pretrained(model, ck if resume else a.adapter, is_trainable=True)
    if a.mode == "dpo":                          # deterministic policy = reference when weights are equal
        for m in model.modules():
            if isinstance(m, torch.nn.Dropout):
                m.p = 0.0
    params = [p for p in model.parameters() if p.requires_grad]
    if DT == torch.float16:
        for p in params:
            p.data = p.data.float()
    if CPU:
        opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.999))
    else:
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(params, lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.999))

    spath = os.path.join(a.out, "schedule.json")
    if os.path.exists(spath):
        S = json.load(open(spath))
    else:
        keys = []
        for e in range(a.epochs):
            k = list(train_ids)
            random.Random(404 + e).shuffle(k)
            keys += k
        S = {"mode": a.mode, "groups": T.chunk(keys, a.accum), "val": val, "data_md5": T.md5(a.data), "adapter": a.adapter}
        json.dump(S, open(spath + ".part", "w"))
        os.replace(spath + ".part", spath)
    groups, val = S["groups"], S["val"]
    NS = len(groups)

    def lr_lambda(s):
        w = max(1, int(a.warmup * NS))
        return min(1.0, (s + 1) / w) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, s / NS))))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    step = 0
    if resume:
        st = torch.load(os.path.join(ck, "state.pt"), weights_only=False, map_location="cpu")
        step = st["step"]
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        if st.get("scaler") and SC.is_enabled():
            SC.load_state_dict(st["scaler"])
        if st.get("rng") is not None:
            torch.set_rng_state(st["rng"])
        log(a.out, "resumed %s at step %d/%d" % (a.mode, step, NS))
    else:
        log(a.out, "start %s from %s: %d %s (%d val), %d steps x %d, lr %g%s, max_len %d" % (
            a.mode, a.adapter, len(train_ids), "rows" if a.mode == "sft" else "pairs", len(val), NS, a.accum, a.lr,
            ", beta %g, sft_alpha %g" % (a.beta, a.sft_alpha) if a.mode == "dpo" else "", a.max_len))

    # ---- DPO reference log-probs (starting adapter, once, resumable)
    ref = {}
    if a.mode == "dpo":
        rp = os.path.join(a.out, "ref_logps.jsonl")
        if os.path.exists(rp):
            for l in open(rp):
                o = json.loads(l)
                ref[o["id"]] = (o["c"], o["r"])
        todo = [k for k in rows if k not in ref]
        if todo:
            if resume:
                raise SystemExit("ref log-probs incomplete after training started: delete the run dir and restart")
            model.eval()
            t0 = time.time()
            with torch.no_grad(), open(rp, "a") as f:
                for i, k in enumerate(todo):
                    d = rows[k]
                    c, _ = logp(model, d["c_ids"], d["c_lab"], dev)
                    r, _ = logp(model, d["r_ids"], d["r_lab"], dev)
                    ref[k] = (float(c), float(r))
                    f.write(json.dumps({"id": k, "c": ref[k][0], "r": ref[k][1]}) + "\n")
                    if (i + 1) % 100 == 0:
                        f.flush()
                        log(a.out, "ref log-probs %d/%d (%.0f s)" % (i + 1, len(todo), time.time() - t0))
                    if os.path.exists(os.path.join(a.out, "STOP")):
                        log(a.out, "EXIT (STOP) during ref log-probs at %d/%d" % (i + 1, len(todo)))
                        return 3
            log(a.out, "ref log-probs done: %d pairs" % len(ref))
        model.train()

    def save(tag="latest", extra=None):
        d = os.path.join(a.out, "ckpt_" + tag)
        tmp = d + ".part"
        os.makedirs(tmp, exist_ok=True)
        model.save_pretrained(tmp)
        if tag == "latest":
            torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": SC.state_dict() if SC.is_enabled() else {},
                        "step": step, "rng": torch.get_rng_state(), "dtype": str(DT)}, os.path.join(tmp, "state.pt"))
        if os.path.exists(d):
            os.system("rm -rf '%s'" % d)
        os.rename(tmp, d)
        json.dump(dict({"step": step, "steps": NS, "mode": a.mode, "t": time.time()}, **(extra or {})),
                  open(os.path.join(a.out, "status.json"), "w"))

    def dpo_terms(d, grad):
        """returns z, loss; with grad=True applies the exact DPO gradient (two backward passes)"""
        rc, rr = ref[d["id"]]
        with torch.no_grad():
            pc, nc = logp(model, d["c_ids"], d["c_lab"], dev)
            pr, _ = logp(model, d["r_ids"], d["r_lab"], dev)
        z = a.beta * ((float(pc) - rc) - (float(pr) - rr))
        loss = -torch.nn.functional.logsigmoid(torch.tensor(z)).item()
        if grad:
            wgt = a.beta * (1.0 / (1.0 + math.exp(z)))        # d loss / d logp_chosen = -w ; / d logp_rejected = +w
            c, nc = logp(model, d["c_ids"], d["c_lab"], dev)
            lc = -wgt * c + (a.sft_alpha * (-c) / max(1, nc) if a.sft_alpha else 0.0)
            SC.scale(lc / a.accum).backward()
            r, _ = logp(model, d["r_ids"], d["r_lab"], dev)
            SC.scale(wgt * r / a.accum).backward()
        return z, loss

    GS = T.gen_slices(a) if (a.gen_inc or a.gen_chat) else None
    bpath = os.path.join(a.out, "best.json")
    best = json.load(open(bpath)) if os.path.exists(bpath) else {"start": None, "top": [], "best": None, "since_best": 0, "evals": 0}

    def evaluate():
        """dev score (train_rsn3.gen_score) + DPO validation; True = early stop"""
        rec = {"step": step, "t": time.time()}
        model.eval()
        if val:
            zs, ls = [], []
            for k in val:
                z, l = dpo_terms(rows[k], False)
                zs.append(z)
                ls.append(l)
            rec["val_reward_acc"] = round(sum(z > 0 for z in zs) / len(zs), 3)
            rec["val_loss"] = round(sum(ls) / len(ls), 4)
            rec["val_margin"] = round(sum(zs) / len(zs) / a.beta, 3)
        sc = None
        if GS:
            model.config.use_cache = True
            for name, (ir, cr) in GS.items():
                if not ir and not cr:
                    continue
                v = T.gen_score(model, tok, tools, ir, cr, dev)
                inc_s = float(v[1] + v[2] + v[3]) / max(1.0, 3 * float(v[0]))
                ch_s = float(v[5]) / max(1.0, float(v[4]))
                parts = [x for x, n in ((inc_s, v[0]), (ch_s, v[4])) if n > 0]
                rec[name] = {"n_inc": int(v[0]), "parse": round(float(v[1]) / max(1.0, float(v[0])), 3),
                             "severity": round(float(v[2]) / max(1.0, float(v[0])), 3), "label": round(float(v[3]) / max(1.0, float(v[0])), 3),
                             "n_chat": int(v[4]), "chat_pass": round(ch_s, 3), "score": round(sum(parts) / max(1, len(parts)), 4)}
            model.config.use_cache = False
            sc = rec.get("dev", {}).get("score")
            if "train" in rec and sc is not None:
                rec["gap"] = round(rec["train"]["score"] - sc, 4)
        model.train()
        log(a.out, "GEN step %d %s" % (step, json.dumps(rec)))
        with open(os.path.join(a.out, "gen_eval.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        if sc is None:
            return False
        if step == 0:
            best["start"] = sc
            json.dump(best, open(bpath, "w"), indent=1)
            return False
        best["evals"] += 1
        start = best["start"] if best["start"] is not None else -1.0
        if sc > max(start, best["best"] if best["best"] is not None else -1.0):
            best["best"], best["since_best"] = sc, 0
        else:
            best["since_best"] += 1
        if sc > start:                                           # only checkpoints that beat the starting adapter
            top = sorted(best["top"] + [[sc, step]], key=lambda x: (-x[0], -x[1]))
            keep, drop = top[:a.keep_best], top[a.keep_best:]
            if [sc, step] in keep:
                save("best_%04d" % step)
            for _, s_ in drop:
                os.system("rm -rf '%s'" % os.path.join(a.out, "ckpt_best_%04d" % s_))
            best["top"] = keep
        json.dump(best, open(bpath, "w"), indent=1)
        return best["since_best"] >= a.patience

    if step == 0 and best["start"] is None and GS:
        evaluate()
    model.train()
    deadline = time.time() + a.hours * 3600
    t0, run_loss, run_n, run_acc, tokc = time.time(), 0.0, 0, 0, 0
    while True:
        if best["since_best"] >= a.patience:
            log(a.out, "EARLY STOP already reached (start %s, top %s)" % (best["start"], best["top"]))
            return 6
        if step >= NS:
            save()
            save("final")
            if GS:
                evaluate()
            log(a.out, "TRAINING DONE step %d (start %s, top %s)" % (step, best["start"], best["top"]))
            return 0
        if time.time() > deadline or os.path.exists(os.path.join(a.out, "STOP")):
            save()
            log(a.out, "EXIT (hours limit / STOP) at step %d" % step)
            return 3
        oom = False
        gl, gacc = 0.0, 0
        for k in groups[step]:
            d = rows[k]
            try:
                if a.mode == "sft":
                    l, n = T.loss_fn(model, d["ids"], d["labels"], dev)
                    SC.scale(l / max(1, n) / a.accum).backward()
                    gl += float(l) / max(1, n)
                    tokc += len(d["ids"])
                else:
                    z, l = dpo_terms(d, True)
                    gl += l
                    gacc += int(z > 0)
                    tokc += len(d["c_ids"]) + len(d["r_ids"])
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                oom = True
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM on %s: optimizer step skipped" % k)
                break
        if oom:
            step += 1
            continue
        SC.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        SC.step(opt)
        SC.update()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        run_loss += gl / len(groups[step - 1])
        run_acc += gacc
        run_n += 1
        if step % 5 == 0 or step == NS:
            el = time.time() - t0
            rec = {"step": step, "loss": run_loss / run_n, "lr": sched.get_last_lr()[0], "tok_s": tokc / max(1e-6, el), "t": time.time()}
            if a.mode == "dpo":
                rec["reward_acc"] = run_acc / max(1, sum(len(groups[s]) for s in range(step - run_n, step)))
            log(a.out, "step %d/%d loss %.4f lr %.2e %.0f tok/s%s" % (step, NS, rec["loss"], rec["lr"], rec["tok_s"],
                                                                     " reward_acc %.3f" % rec["reward_acc"] if a.mode == "dpo" else ""))
            with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                f.write(json.dumps(rec) + "\n")
            t0, run_loss, run_n, run_acc, tokc = time.time(), 0.0, 0, 0, 0
        if step % a.save_every == 0:
            save()
        if (GS or val) and step % a.gen_every == 0 and step < NS:
            if evaluate():
                save(extra={"stopped": "early_stop"})
                log(a.out, "EARLY STOP at step %d: dev score not better for %d evals (start %s, top %s)" % (
                    step, a.patience, best["start"], best["top"]))
                return 6


if __name__ == "__main__":
    sys.exit(main())
