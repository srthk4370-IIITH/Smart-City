"""train_agt3.py: agt_v3 QLoRA from base Llama-3.2-3B-Instruct (V3_DESIGN.md §5.1). One run, resumable across Kaggle sessions.

Recipe (fixed in recipe.json at step 0; a resume with different values stops): NF4 double-quant base, fp16 compute + GradScaler
on T4 (no fast bf16), LoRA r32 / alpha32 / dropout 0.05 on q,k,v,o,gate,up,down, LR 2e-4, warm-up 3 %, cosine to 0.1x,
rows_per_step 32 (= micro 4 x accum x GPUs), max_len 1536 (a longer row stops the run: nothing truncated, nothing skipped),
<= 2 epochs, loss on completion tokens only (token mean over the whole step, identical for 1 or 2 GPUs), no curriculum,
per-step family quotas (systematic interleave) and length-grouped micro-batches.

Multi-GPU: torchrun; every rank trains its share of the step's rows (balanced by tokens, deterministic), then ONE all-reduce of
the LoRA gradients (no DDP wrapper), so a step means the same on 1 or 2 GPUs.
--oom-stop: an OOM in a micro-batch clears this rank's step gradients and retries its rows one per forward; a row that still
OOMs stops the run at the state before the step (exit 7). Steps are never skipped.
Every --save-every steps: ckpt_latest (adapter fp32 + optimizer + scheduler + scaler + step + RNG; schedule.json is the cursor).
Every --snap-every steps: snap_XXXX (adapter only) for the laptop's merged-Q4_0 selection, plus a generation dev score
(greedy, prefill, rows split over ranks) for early stop (--patience evals without gain -> exit 6).
Exit: 0 done (epochs) | 3 hours limit | 6 early stop | 7 OOM stop | 2 bad input/recipe.
Laptop helpers: --tokfp-only (token fingerprint + max-length check, CPU) ; CPU smoke: --quant none --dtype fp32 --optim adamw.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rows as RW  # noqa: E402

T0 = time.time()
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
RECIPE_KEYS = ("rank", "alpha", "dropout", "lr", "warmup", "min_lr_ratio", "rows_per_step", "micro", "max_len", "epochs",
               "seed", "quant", "train_md5")


def md5f(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


class Log:
    def __init__(self, out, rank):
        self.rank, self.f = rank, (open(os.path.join(out, "train.log"), "a") if rank == 0 else None)

    def __call__(self, m):
        if self.rank:
            return
        line = "[%s +%.2fh] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), (time.time() - T0) / 3600, m)
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def args_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--dev", required=True, help="gen-dev rows (early stop score)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--warmup", type=float, default=0.03)
    ap.add_argument("--min-lr-ratio", type=float, default=0.1)
    ap.add_argument("--rows-per-step", type=int, default=32)
    ap.add_argument("--micro", type=int, default=4)
    ap.add_argument("--max-len", type=int, default=1536)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--quant", choices=["nf4", "none"], default="nf4")
    ap.add_argument("--dtype", choices=["fp16", "bf16", "fp32"], default="fp16")
    ap.add_argument("--optim", choices=["adamw8bit", "adamw"], default="adamw8bit")
    ap.add_argument("--hours", type=float, default=1e9, help="session budget: checkpoint + exit 3 before it")
    ap.add_argument("--save-every", type=int, default=50)
    ap.add_argument("--snap-every", type=int, default=250)
    ap.add_argument("--gen-n", type=int, default=150)
    ap.add_argument("--gen-batch", type=int, default=8)
    ap.add_argument("--max-new", type=int, default=400)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--min-gain", type=float, default=0.002)
    ap.add_argument("--oom-stop", action="store_true")
    ap.add_argument("--no-grad-ckpt", action="store_true")
    ap.add_argument("--max-steps-session", type=int, default=0, help="test only: exit 3 after N steps this session")
    ap.add_argument("--call-rep", type=int, default=4, help="round 2: tool-call rows repeated this many times per epoch")
    ap.add_argument("--first-w", type=float, default=10.0, help="round 2: loss weight of the first 2 completion tokens (the call-vs-direct decision)")
    ap.add_argument("--tokfp-only", action="store_true")
    return ap.parse_args()


# ---------------------------------------------------------------- data
def tokenize(rows, tok, max_len):
    items, too_long = [], []
    for r in rows:
        p = tok(r["prompt"], add_special_tokens=False)["input_ids"]
        c = tok(r["completion"], add_special_tokens=False)["input_ids"]
        if len(p) + len(c) > max_len:
            too_long.append((r["id"], len(p) + len(c)))
        items.append({"id": r["id"], "p": p, "c": c, "fam": r["family"], "turn": r.get("turn")})
    return items, too_long


def tokfp(items):
    h = hashlib.md5()
    for it in items[:512]:
        h.update(json.dumps([it["p"], it["c"]]).encode())
    return {"n": len(items), "tokens": sum(len(i["p"]) + len(i["c"]) for i in items), "md5_first512": h.hexdigest()}


def build_schedule(items, a):
    """per epoch: every family shuffled, rows ordered by (k + u) / n_family (systematic interleave = per-step family quotas),
    chunked into rows_per_step; the last partial step of an epoch is merged into the next epoch's order (no row dropped)."""
    rng = random.Random(a.seed)
    fams = {}
    n_exp = 0
    for i, it in enumerate(items):
        k = a.call_rep if it.get("turn") == "call" else 1
        fams.setdefault(it["fam"], []).extend([i] * k)
        n_exp += k
    n_ep = math.ceil(a.epochs)
    order = []
    for ep in range(n_ep):
        keyed = []
        for f in sorted(fams):
            ids = fams[f][:]
            rng.shuffle(ids)
            n = len(ids)
            keyed += [((k + rng.random()) / n, i) for k, i in enumerate(ids)]
        keyed.sort()
        order += [i for _, i in keyed]
    total = int(n_exp * a.epochs)
    order = order[:total]
    steps = [order[s:s + a.rows_per_step] for s in range(0, len(order) - a.rows_per_step + 1, a.rows_per_step)]
    return {"ids": [[items[i]["id"] for i in st] for st in steps], "n_steps": len(steps),
            "steps_per_epoch": n_exp / a.rows_per_step}


def split_ranks(step_items, world):
    """deterministic LPT split by tokens (every rank computes the same); rows sorted by length inside a rank"""
    order = sorted(range(len(step_items)), key=lambda j: (-(len(step_items[j]["p"]) + len(step_items[j]["c"])), step_items[j]["id"]))
    load, parts = [0] * world, [[] for _ in range(world)]
    for j in order:
        r = min(range(world), key=lambda k: (load[k], len(parts[k]), k))
        parts[r].append(step_items[j])
        load[r] += len(step_items[j]["p"]) + len(step_items[j]["c"])
    return parts


# ---------------------------------------------------------------- model
def load_model(a, dev):
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    dt = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[a.dtype]
    kw = {"dtype": dt}
    if a.quant == "nf4":
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                       bnb_4bit_compute_dtype=dt)
        kw["device_map"] = {"": dev}
    m = AutoModelForCausalLM.from_pretrained(a.base, attn_implementation="sdpa", **kw)
    if a.quant != "nf4":
        m.to(dev)
    m.config.use_cache = False
    gc = not a.no_grad_ckpt
    if a.quant == "nf4":
        m = prepare_model_for_kbit_training(m, use_gradient_checkpointing=gc, gradient_checkpointing_kwargs={"use_reentrant": False})
    elif gc:
        m.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        m.enable_input_require_grads()
    lat = os.path.join(a.out, "ckpt_latest")
    if os.path.exists(os.path.join(lat, "adapter_model.safetensors")):
        m = PeftModel.from_pretrained(m, lat, is_trainable=True)
    else:
        m = get_peft_model(m, LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=a.dropout, target_modules=TARGETS,
                                         bias="none", task_type="CAUSAL_LM"))
    for n, p in m.named_parameters():
        if p.requires_grad:
            p.data = p.data.float()           # LoRA masters fp32 (GradScaler needs fp32 grads)
    return m


FIRST_W = 10.0


def tok_w(n):
    return [FIRST_W if j < 2 else 1.0 for j in range(n)]


def micro_loss_sum(m, batch, dev, ac):
    """sum of token CE over the completion tokens of these rows (logits only at those positions: no 128k x L logits)"""
    L = max(len(it["p"]) + len(it["c"]) for it in batch)
    ids = torch.full((len(batch), L), 128009, dtype=torch.long)
    att = torch.zeros((len(batch), L), dtype=torch.long)
    pos_b, pos_t, tgt, wt = [], [], [], []
    for b, it in enumerate(batch):
        x = it["p"] + it["c"]
        ids[b, :len(x)] = torch.tensor(x)
        att[b, :len(x)] = 1
        for j in range(len(it["p"]), len(x)):
            pos_b.append(b)
            pos_t.append(j - 1)
            tgt.append(x[j])
            wt.append(FIRST_W if j - len(it["p"]) < 2 else 1.0)
    ids, att = ids.to(dev), att.to(dev)
    lm = m.get_base_model()
    with ac():
        h = lm.model(input_ids=ids, attention_mask=att).last_hidden_state
        hs = h[torch.tensor(pos_b, device=dev), torch.tensor(pos_t, device=dev)]
        logits = lm.lm_head(hs).float()
    ce = torch.nn.functional.cross_entropy(logits, torch.tensor(tgt, device=dev), reduction="none")
    return (ce * torch.tensor(wt, device=dev, dtype=ce.dtype)).sum()


def is_oom(e):
    return isinstance(e, torch.cuda.OutOfMemoryError) or "out of memory" in str(e).lower()


# ---------------------------------------------------------------- gen dev score
def score_row(r, t):
    turn = r["raw"].get("turn")
    if turn not in ("call", "direct"):
        return dict(RW.score(r["gold"], t), grp="final" if turn == "final" else "hard")
    d = RW.parse(t.replace("<|eot_id|>", "").strip())
    isc = isinstance(d, dict) and "tool" in d
    s = {"json": isinstance(d, dict), "grp": "t1", "turn": turn, "status": None, "pattern": None, "cause": None, "dq": None, "ok": None}
    s["ok"] = bool(isc and d.get("tool") == r["gold"].get("tool") and d.get("args") == r["gold"].get("args")) if turn == "call" else (not isc)
    return s


def combo_score(sc):
    g = {}
    for s in sc:
        g.setdefault(s.get("grp", "hard"), []).append(s)
    v = [(sum(bool(s["ok"]) for s in x) / len(x)) if k == "t1" else RW.gen_score(x) for k, x in g.items()]
    return sum(v) / len(v) if v else 0.0


@torch.no_grad()
def gen_eval(m, tok, rows, a, dev, rank, world, ac, dist):
    m.eval()
    lm = m.get_base_model()
    lm.config.use_cache = True
    mine = rows[rank::world]
    out = []
    tok.padding_side = "left"
    for s in range(0, len(mine), a.gen_batch):
        b = mine[s:s + a.gen_batch]
        pres = ['{"' if r["raw"].get("turn") in ("call", "direct") else RW.prefill(r["completion"]) for r in b]
        texts = [r["prompt"] + p for r, p in zip(b, pres)]
        enc = tok(texts, add_special_tokens=False, return_tensors="pt", padding=True).to(dev)
        try:
            with ac():
                g = m.generate(**enc, max_new_tokens=a.max_new, do_sample=False, eos_token_id=[128009, 128001],
                               pad_token_id=128009)
            for r, p, seq in zip(b, pres, g[:, enc["input_ids"].shape[1]:]):
                t = p + tok.decode(seq, skip_special_tokens=True)
                out.append(dict(score_row(r, t), id=r["id"]))
        except RuntimeError as e:
            if not is_oom(e):
                raise
            torch.cuda.empty_cache()
            out += [dict(RW.score(r["gold"], ""), id=r["id"], oom=True) for r in b]
    lm.config.use_cache = False
    m.train()
    if world > 1:
        allv = [None] * world
        dist.all_gather_object(allv, out)
        out = [x for v in allv for x in v]
    return out


# ---------------------------------------------------------------- checkpoint
def save_ckpt(m, opt, sch, scaler, step, a, name="ckpt_latest", full=True):
    d = os.path.join(a.out, name)
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    m.save_pretrained(tmp)
    if full:
        torch.save({"step": step, "opt": opt.state_dict(), "sch": sch.state_dict(),
                    "scaler": scaler.state_dict() if scaler is not None else None,
                    "rng_py": random.getstate(), "rng_torch": torch.get_rng_state()}, os.path.join(tmp, "state.pt"))
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)


def jdump(o, p):
    with open(p + ".tmp", "w") as f:
        json.dump(o, f, indent=1)
    os.replace(p + ".tmp", p)


# ---------------------------------------------------------------- main
def main():
    global FIRST_W
    a = args_()
    FIRST_W = a.first_w
    os.makedirs(a.out, exist_ok=True)
    world = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    dist = None
    cuda = torch.cuda.is_available()
    if world > 1:
        import torch.distributed as dist
        dist.init_process_group("nccl" if cuda else "gloo", timeout=datetime.timedelta(hours=2))
    dev = torch.device("cuda", int(os.environ.get("LOCAL_RANK", "0"))) if cuda else torch.device("cpu")
    if cuda:
        torch.cuda.set_device(dev)
    log = Log(a.out, rank)

    def fail(msg, rc=2):
        log("STOP: " + msg)
        if dist:
            dist.destroy_process_group()
        sys.exit(rc)

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.base)
    tok.pad_token_id = 128009
    train_rows = [RW.norm(r) for r in RW.read_jsonl(a.train)]
    dev_rows = [RW.norm(r) for r in RW.read_jsonl(a.dev)][:a.gen_n]
    items, too_long = tokenize(train_rows, tok, a.max_len)
    fp = tokfp(items)
    if a.tokfp_only:
        print(json.dumps(dict(fp, too_long=len(too_long), too_long_ids=too_long[:20],
                              max_tokens=max(len(i["p"]) + len(i["c"]) for i in items))))
        sys.exit(1 if too_long else 0)
    if too_long:
        fail("%d rows longer than max_len %d (e.g. %s): nothing is truncated or skipped" % (len(too_long), a.max_len, too_long[:3]))
    byid = {it["id"]: it for it in items}
    if len(byid) != len(items):
        fail("duplicate row ids in %s" % a.train)

    recipe = {k: getattr(a, k) for k in RECIPE_KEYS if k != "train_md5"}
    recipe["train_md5"] = md5f(a.train)
    rp, sp, fpp = (os.path.join(a.out, f) for f in ("recipe.json", "schedule.json", "tokfp.json"))
    if os.path.exists(rp):
        old = json.load(open(rp))
        diff = {k: (old.get(k), recipe[k]) for k in RECIPE_KEYS if old.get(k) != recipe[k]}
        if diff:
            fail("recipe differs from the lineage: %s" % diff)
        if os.path.exists(fpp) and json.load(open(fpp)) != fp:
            fail("token fingerprint differs from the lineage (tokenizer / package drift): %s vs %s" % (json.load(open(fpp)), fp))
    elif rank == 0:
        jdump(recipe, rp)
        jdump(fp, fpp)
    if os.path.exists(sp):
        sched = json.load(open(sp))
    else:
        sched = build_schedule(items, a)
        if rank == 0:
            jdump(sched, sp)
    n_steps = sched["n_steps"]

    torch.manual_seed(a.seed)
    m = load_model(a, dev)
    params = [p for p in m.parameters() if p.requires_grad]
    log("trainable params %.1f M; world %d; device %s; rows %d; steps %d (%.1f / epoch); tokens %d" % (
        sum(p.numel() for p in params) / 1e6, world, dev, len(items), n_steps, sched["steps_per_epoch"], fp["tokens"]))
    if a.optim == "adamw8bit":
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(params, lr=a.lr, betas=(0.9, 0.999), weight_decay=0.0)
    else:
        opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    warm = max(1, int(a.warmup * n_steps))

    def lr_at(s):
        if s < warm:
            return (s + 1) / warm
        q = (s - warm) / max(1, n_steps - warm)
        return a.min_lr_ratio + (1 - a.min_lr_ratio) * 0.5 * (1 + math.cos(math.pi * min(1.0, q)))
    sch = torch.optim.lr_scheduler.LambdaLR(opt, lr_at)
    scaler = torch.amp.GradScaler("cuda") if (cuda and a.dtype == "fp16") else None
    step = 0
    st_p = os.path.join(a.out, "ckpt_latest", "state.pt")
    if os.path.exists(st_p):
        st = torch.load(st_p, map_location="cpu", weights_only=False)
        step = st["step"]
        opt.load_state_dict(st["opt"])
        sch.load_state_dict(st["sch"])
        if scaler is not None and st.get("scaler"):
            scaler.load_state_dict(st["scaler"])
        random.setstate(st["rng_py"])
        torch.set_rng_state(st["rng_torch"])
        log("resumed at step %d" % step)
    if cuda and a.dtype != "fp32":
        dt = torch.float16 if a.dtype == "fp16" else torch.bfloat16

        def ac():
            return torch.autocast("cuda", dtype=dt)
    else:
        import contextlib

        def ac():
            return contextlib.nullcontext()

    bestp = os.path.join(a.out, "best.json")
    best = json.load(open(bestp)) if os.path.exists(bestp) else {"best": None, "best_step": None, "since": 0, "evals": []}
    statp = os.path.join(a.out, "status.json")
    m.train()
    t_sess, tok_sess, s_sess = time.time(), 0, 0

    def allr(x):
        if world == 1:
            return x
        t = torch.tensor([x], device=dev, dtype=torch.float64)
        dist.all_reduce(t)
        return t.item()

    def finish(rc, why):
        if rank == 0:
            save_ckpt(m, opt, sch, scaler, step, a)
            stt = {"step": step, "n_steps": n_steps, "rc": rc, "why": why, "best": best, "t": time.time(),
                   "tok_s": round(tok_sess / max(1e-6, time.time() - t_sess), 1)}
            if rc in (0, 6):
                stt["stopped"] = "done" if rc == 0 else "early_stop"
            jdump(stt, statp)
        log({0: "TRAINING DONE", 3: "EXIT (hours limit)", 6: "EARLY STOP", 7: "OOM STOP"}.get(rc, "EXIT") + " at step %d: %s" % (step, why))
        if dist:
            dist.barrier()
            dist.destroy_process_group()
        sys.exit(rc)

    while True:
        if step >= n_steps:
            if rank == 0 and not os.path.exists(os.path.join(a.out, "snap_%04d" % step)):
                save_ckpt(m, None, None, None, step, a, name="snap_%04d" % step, full=False)
            finish(0, "all %d steps (%.2f epochs)" % (n_steps, a.epochs))
        el_h = (time.time() - T0) / 3600
        stop_h = allr(1.0 if (el_h >= a.hours or (a.max_steps_session and s_sess >= a.max_steps_session)) else 0.0)
        if stop_h:
            finish(3, "session budget %.2f h used (%.2f h)" % (a.hours, el_h))
        st_items = [byid[i] for i in sched["ids"][step]]
        n_comp = sum(sum(tok_w(len(it["c"]))) for it in st_items)            # the step's loss = token mean over ALL its completion tokens
        mine = split_ranks(st_items, world)[rank]
        opt.zero_grad(set_to_none=True)
        lsum, oom_stop = 0.0, 0.0

        def run(batches):
            s = 0.0
            for b in batches:
                ls = micro_loss_sum(m, b, dev, ac)
                (scaler.scale(ls / n_comp) if scaler is not None else ls / n_comp).backward()
                s += ls.item()
            return s
        try:
            lsum = run([mine[i:i + a.micro] for i in range(0, len(mine), a.micro)])
        except RuntimeError as e:
            if not is_oom(e):
                raise
            log("OOM in a micro-batch at step %d (rank %d): retrying this rank's %d rows one per forward" % (step, rank, len(mine)))
            opt.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            try:
                lsum = run([[it] for it in mine])
            except RuntimeError as e2:
                if not is_oom(e2):
                    raise
                if not a.oom_stop:
                    raise
                oom_stop = 1.0
        if allr(oom_stop):
            opt.zero_grad(set_to_none=True)
            finish(7, "a row did not fit even alone at step %d; state = before this step" % step)
        if world > 1:
            grads = [p.grad if p.grad is not None else torch.zeros_like(p) for p in params]
            flat = torch.cat([g.reshape(-1) for g in grads])
            dist.all_reduce(flat)
            o = 0
            for p in params:
                n = p.numel()
                p.grad = flat[o:o + n].view_as(p).clone()
                o += n
            lsum = allr(lsum)
        if scaler is not None:
            scaler.unscale_(opt)
        gn = torch.nn.utils.clip_grad_norm_(params, 1.0).item()
        if scaler is not None:
            sc0 = scaler.get_scale()
            scaler.step(opt)
            scaler.update()
            skipped = scaler.get_scale() < sc0
        else:
            opt.step()
            skipped = False
        sch.step()
        step += 1
        s_sess += 1
        ntok = sum(len(it["p"]) + len(it["c"]) for it in st_items)
        tok_sess += ntok
        if rank == 0:
            with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                f.write(json.dumps({"step": step, "loss": round(lsum / n_comp, 5), "gn": round(gn, 4), "lr": sch.get_last_lr()[0],
                                    "tok": ntok, "fp16_overflow": bool(skipped),
                                    "scale": scaler.get_scale() if scaler is not None else None, "t": round(time.time(), 1)}) + "\n")
            if step % 10 == 0 or step <= 3:
                log("step %d/%d loss %.4f gn %.3f lr %.2e %.0f tok/s%s" % (step, n_steps, lsum / n_comp, gn, sch.get_last_lr()[0],
                    tok_sess / (time.time() - t_sess), " (fp16 overflow: scaler skipped the update)" if skipped else ""))
        if step % a.save_every == 0 and rank == 0:
            save_ckpt(m, opt, sch, scaler, step, a)
        if step % a.snap_every == 0 and step < n_steps:
            if rank == 0:
                save_ckpt(m, None, None, None, step, a, name="snap_%04d" % step, full=False)
            t1 = time.time()
            sc = gen_eval(m, tok, dev_rows, a, dev, rank, world, ac, dist)
            g = combo_score(sc)
            agg = {k: round(sum(bool(s[k]) for s in sc if s.get(k) is not None) / max(1, sum(s.get(k) is not None for s in sc)), 4)
                   for k in ("json", "status", "pattern", "cause", "dq")}
            tc = [s for s in sc if s.get("turn") == "call"]
            td = [s for s in sc if s.get("turn") == "direct"]
            agg["call_ok"] = round(sum(bool(s["ok"]) for s in tc) / max(1, len(tc)), 4)
            agg["direct_ok"] = round(sum(bool(s["ok"]) for s in td) / max(1, len(td)), 4)
            last = best["evals"][-1]["score"] if best["evals"] else None
            if best["best"] is None or g > best["best"]:
                best.update(best=g, best_step=step)
            best["since"] = best["since"] + 1 if (last is not None and g < last - 0.001) else 0
            if step < sched["steps_per_epoch"] or agg["call_ok"] < 0.5:     # round 2: no early stop before 1 full epoch, nor while the tool call is not learned
                best["since"] = 0
            best["evals"].append({"step": step, "score": round(g, 4), **agg, "n": len(sc), "s": round(time.time() - t1)})
            if rank == 0:
                jdump(best, bestp)
                with open(os.path.join(a.out, "gen_dev.jsonl"), "a") as f:
                    f.write(json.dumps({"step": step, "score": g, **agg, "rows": sc}) + "\n")
            log("gen dev @%d: score %.4f %s (best %.4f @%s, %d without gain) %.0f s" % (step, g, agg, best["best"], best["best_step"],
                                                                                    best["since"], time.time() - t1))
            if best["since"] >= a.patience:
                finish(6, "%d gen-dev evals without gain (best %.4f at step %s)" % (best["since"], best["best"], best["best_step"]))


if __name__ == "__main__":
    main()
