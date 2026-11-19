"""rsn_v3 QLoRA/LoRA SFT of Qwen3.5-4B from the BASE (derived from round-1 train_rsn.py: same loss, LoRA targets, warmup+cosine).
Changes vs round 1: rank 32 / alpha 64; max length 6144; per-row tools (incident -> tools_v4 "incident", chat -> "chat") and
per-row thinking (incident: enable_thinking=False as rsn_v1; chat: True, target holds the <think> block, empty on lookups);
loss only on the current turn; data-parallel over all visible GPUs (torchrun; one gradient all-reduce per optimizer step =
single-GPU accumulation of --accum rows); fp16 + GradScaler on GPUs without bf16 (T4); dev loss every --eval-every steps.

Two data sources and a curriculum (TIME_MODEL.md):
- --inc (bundle A, always) and --chat (bundle B, optional: arrives later). The plan is a list of optimizer-step groups
  (schedule.json, deterministic, resumable). Without chat: epoch 1 = incident rows only (shuffled); when those run out the
  run saves and exits 4 (WAIT_CHAT). When --chat first appears at step s, the incident rows not yet trained on are
  shuffled together with the chat rows into the rest of epoch 1 (groups before s are kept as they were).
- epoch 2 = only the weak/hard rows: incident rows of the --e2-families (rsn_v1's weak families, incl. their +tool/+inject
  variants) + chat rows with hard=true. It runs only with --run-e2; otherwise the run stops after epoch 1 (exit 5) with
  ckpt_epoch1 saved: the normal path when the gate already passes.
- LR: segment 1 (epoch 1) warmup 3% + cosine 1 -> 0.1, so the epoch-1 adapter is fully annealed; segment 2 (epoch 2) warmup
  3% to --e2-peak (0.5) x LR, cosine down to 0.05 x LR.
Probe (--probe-steps N): N optimizer steps on the 2 longest rows + random rows, no save; prints PROBE_RESULT {json} with tok/s
(all ranks, excluding the 2 warm-up rows), peak VRAM, loss, OOM and the projected hours of the plan. --no-fla blocks
flash-linear-attention (torch path) so both can be compared without reinstalling.
Overtraining control: every --gen-every steps a greedy generation eval on fixed slices (40 incident dev rows: parse /
severity / label; 40 chat dev records: verify_chat pass; + 20/20 train rows for the train/dev gap) -> gen_eval.jsonl;
best --keep-best checkpoints by the dev score (ckpt_best_XXXX, best.json); early stop after --patience evals without a
better score (only once chat rows are in the plan). LoRA dropout 0.05, weight decay 0.01.
Checkpoints are portable between Kaggle (fp16 + GradScaler) and the laptop (bf16, no scaler): LoRA weights are fp32 in both;
the scaler state is only restored into an fp16 run; schedule.json + step = the data cursor; torch RNG saved.
Exit codes: 0 plan done, 3 hours limit / STOP file, 4 waiting for chat rows, 5 epoch 1 done (stop after epoch 1), 6 early stop."""
import argparse
import datetime
import hashlib
import json
import math
import os
import random
import sys
import time

import torch

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a",
           "in_proj_b", "out_proj"]
E2_FAMILIES = ["single_glitch", "drift_low", "insufficient", "recovery_gap", "stale_related", "coincidence", "class_fills", "acidic",
               "chatter", "outage", "indoor_emission", "agent_miss"]
RANK = int(os.environ.get("RANK", 0))
WORLD = int(os.environ.get("WORLD_SIZE", 1))
LOCAL = int(os.environ.get("LOCAL_RANK", 0))


def log(out, msg):
    if RANK:
        return
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(out, "train.log"), "a") as f:
        f.write(line + "\n")


def encode(tok, ex, tools, max_len):
    msgs = ex["messages"]
    kw = dict(tools=tools, tokenize=False, enable_thinking=bool(ex.get("think")))
    full = tok.apply_chat_template(msgs, **kw)
    spans = []
    # loss only on the current turn (assistant messages after the last user message): earlier turns are context, and
    # the template renders them without a think block, so a truncated render would not be a prefix of the full one
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    for i, m in enumerate(msgs):
        if m["role"] != "assistant" or i < last_user:
            continue
        g = tok.apply_chat_template(msgs[:i], add_generation_prompt=True, **kw)
        f = tok.apply_chat_template(msgs[:i + 1], **kw)
        if not (f.startswith(g) and full.startswith(f)):
            return None, "prefix"
        end = f.rindex("<|im_end|>") + len("<|im_end|>")
        spans.append((len(g), end))
    enc = tok(full, return_offsets_mapping=True, add_special_tokens=False)
    ids = enc["input_ids"]
    labels = [-100] * len(ids)
    for k, (a, b) in enumerate(enc["offset_mapping"]):
        for s, e in spans:
            if a >= s and b <= e and b > a:
                labels[k] = ids[k]
    if len(ids) > max_len:
        return None, "too_long"
    if not any(l != -100 for l in labels):
        return None, "no_labels"
    return (ids, labels), None


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:12]


def prep(tok, path, tools, max_len, out, name):
    """tokenize once per input file (cache keyed by the file's md5); rows keep id, kind, family, hard"""
    cache = os.path.join(out, "%s_%s_tok.pt" % (name, md5(path)))
    if os.path.exists(cache):
        return torch.load(cache), cache
    data, skipped = [], {}
    for line in open(path, encoding="utf-8"):
        ex = json.loads(line)
        r, why = encode(tok, ex, tools.get(ex["tools"]), max_len)
        if r is None:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        data.append({"id": ex["id"], "kind": ex["tools"], "family": ex.get("family", ""), "hard": bool(ex.get("hard")),
                     "ids": torch.tensor(r[0], dtype=torch.int32), "labels": torch.tensor(r[1], dtype=torch.int32)})
    torch.save(data, cache + ".part")
    os.replace(cache + ".part", cache)
    L = sorted(int(d["ids"].numel()) for d in data)
    print("prep %s: %d kept, skipped %s; tokens mean %d p50 %d p90 %d max %d, total %.1fM" % (
        os.path.basename(path), len(data), skipped, sum(L) / len(L), L[len(L) // 2], L[int(len(L) * .9)], L[-1], sum(L) / 1e6), flush=True)
    return data, cache


def loss_fn(model, ids, labels, dev):
    """hidden states once; lm_head + CE only at label positions, in checkpointed chunks (never full 248k-vocab logits)"""
    from torch.utils.checkpoint import checkpoint
    inner = model.get_base_model()
    x = ids.long().unsqueeze(0).to(dev)
    y = torch.cat([labels[1:].long(), torch.tensor([-100])]).to(dev)
    keep = (y != -100).nonzero().squeeze(1)
    h = inner.model(input_ids=x, use_cache=False).last_hidden_state[0]
    hs, ys = h[keep], y[keep]
    head = inner.lm_head

    def ce(hc, yc):
        return torch.nn.functional.cross_entropy(head(hc).float(), yc, reduction="sum")
    tot = 0.0
    for i in range(0, hs.shape[0], 128):
        tot = tot + checkpoint(ce, hs[i:i + 128], ys[i:i + 128], use_reentrant=False)
    return tot, int(keep.numel())


def allreduce(t, op=None):
    if WORLD > 1:
        torch.distributed.all_reduce(t, op=op or torch.distributed.ReduceOp.SUM)
    return t


def barrier():
    if WORLD > 1:
        torch.distributed.barrier()


def chunk(keys, n):
    return [keys[i:i + n] for i in range(0, len(keys), n)]


def is_e2(row):
    if row["kind"] == "chat":
        return row["hard"]
    return row["family"].split(":")[0].split("+")[0] in E2_FAMILIES


def plan_schedule(path, inc, chat, accum, step_now):
    """deterministic step groups; see module doc. Returns the schedule dict (written to path by rank 0)."""
    S = json.load(open(path)) if os.path.exists(path) else None
    ik = [d["id"] for d in inc]
    ck = [d["id"] for d in chat] if chat else []
    if S is None:
        if ck:
            keys = ik + ck
            random.Random(101).shuffle(keys)
            S = {"state": "mixed", "groups": chunk(keys, accum), "merged_at": 0}
        else:
            keys = list(ik)
            random.Random(101).shuffle(keys)
            S = {"state": "inc_only", "groups": chunk(keys, accum), "merged_at": None}
    elif S["state"] == "inc_only" and ck:
        s = min(step_now, len(S["groups"]))
        rest = [k for g in S["groups"][s:] for k in g] + ck
        random.Random(202 + s).shuffle(rest)
        S = {"state": "mixed", "groups": S["groups"][:s] + chunk(rest, accum), "merged_at": s}
    if S["state"] == "mixed" and "e2" not in S:
        rows = {d["id"]: d for d in inc + (chat or [])}
        e2 = [k for k in rows if is_e2(rows[k])]
        random.Random(303).shuffle(e2)
        S["e2"] = chunk(e2, accum)
    return S


def _parse_report(t):
    a, b = t.find("{"), t.rfind("}")
    try:
        return json.loads(t[a:b + 1]) if a >= 0 and b > a else None
    except Exception:
        return None


def gen_slices(a):
    """fixed generation-eval slices (same rows every eval, every rank): incident rows without tool rounds, chat3 records"""
    def inc(p, n, seed):
        if not p or not os.path.exists(p):
            return []
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        rs = [r for r in rs if r.get("tools") == "incident" and not any(m["role"] == "tool" for m in r["messages"])]
        random.Random(seed).shuffle(rs)
        return rs[:n]

    def chat(p, n, seed):
        if not p or not os.path.exists(p):
            return []
        rs = [json.loads(l) for l in open(p, encoding="utf-8")]
        random.Random(seed).shuffle(rs)
        return rs[:n]
    return {"dev": (inc(a.gen_inc, a.gen_n, 11), chat(a.gen_chat, a.gen_n, 12)),
            "train": (inc(a.gen_train_inc, a.gen_train_n, 13), chat(a.gen_train_chat, a.gen_train_n, 14))}


def gen_score(model, tok, tools, inc_rows, chat_recs, dev):
    """greedy generation; incidents: parse / severity / label vs the gold report; chat: verify_chat pass. Returns sums
    [n_inc, parse, severity, label, n_chat, chat_pass] for this rank's share."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import chatloop as CL
    import verify_chat as VC
    from tools_v3_impl import ToolsV3
    out = torch.zeros(6, device=dev, dtype=torch.float64)
    be = CL.HFBackend(model, tok, temperature=0.0, max_new=900, tok_budget=24000, max_batch=8, log=lambda m: None)
    if inc_rows:
        prompts = [tok.apply_chat_template(r["messages"][:2], tools=tools["incident"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False) for r in inc_rows]
        for r, (txt, _) in zip(inc_rows, be.generate(prompts, [False] * len(prompts))):
            g = json.loads(r["messages"][-1]["content"])
            p = _parse_report(txt)
            out[0] += 1
            if isinstance(p, dict):
                out[1] += 1
                out[2] += float(p.get("severity") == g.get("severity"))
                out[3] += float(p.get("label") == g.get("label"))
    if chat_recs:
        be.max_new = 420
        ss = [CL.Sample(r, 0, r.get("hard")) for r in chat_recs]
        CL.run_samples(be, tok, tools["chat"], ss, ToolsV3, VC.parse_turn)
        ex = ToolsV3()
        for s in ss:
            ex.qid = 0
            out[4] += 1
            out[5] += float(VC.verify(s.rec, CL.candidate(s), executor=ex)["pass"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tools", required=True, help="tools_v4.json ({incident, chat})")
    ap.add_argument("--inc", required=True, help="incident rows (bundle A)")
    ap.add_argument("--chat", default="", help="chat rows (bundle B); absent/empty = incident part of epoch 1 only")
    ap.add_argument("--expect-chat", type=int, default=7200, help="planned chat rows (LR plan before bundle B arrives)")
    ap.add_argument("--dev", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--r", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--e2-peak", type=float, default=0.5)
    ap.add_argument("--run-e2", action="store_true", help="train epoch 2 (hard rows); default: stop after epoch 1")
    ap.add_argument("--accum", type=int, default=16, help="rows per optimizer step (all GPUs together)")
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--keep-every", type=int, default=500)
    ap.add_argument("--eval-every", type=int, default=100)
    ap.add_argument("--hours", type=float, default=11)
    ap.add_argument("--probe-steps", type=int, default=0)
    ap.add_argument("--probe-len", type=int, default=0, help="probe: the 2 warm-up rows become synthetic rows of this many tokens (fit test)")
    ap.add_argument("--model-dir", default="", help="load weights from here (e.g. the laptop's pre-quantized NF4 copy); tokenizer from --base")
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16"], help="auto: bf16 on Ampere+, fp16 + GradScaler on T4")
    ap.add_argument("--quant", default="nf4", choices=["nf4", "none"], help="nf4 = QLoRA 4-bit; none = 16-bit base LoRA (more VRAM)")
    ap.add_argument("--no-fla", action="store_true", help="block flash-linear-attention (torch Gated-DeltaNet path)")
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--wd", type=float, default=0.01)
    # generation dev score (overtraining control): every --gen-every steps, greedy generation on fixed slices
    ap.add_argument("--gen-every", type=int, default=200)
    ap.add_argument("--gen-inc", default="", help="incident dev rows (gold report as last message)")
    ap.add_argument("--gen-chat", default="", help="chat3 dev records (verify_chat gold)")
    ap.add_argument("--gen-train-inc", default="", help="incident train rows for the train/dev gap")
    ap.add_argument("--gen-train-chat", default="", help="chat3 train records for the train/dev gap")
    ap.add_argument("--gen-n", type=int, default=40)
    ap.add_argument("--gen-train-n", type=int, default=20)
    ap.add_argument("--patience", type=int, default=3, help="early stop after this many generation evals without a better dev score")
    ap.add_argument("--keep-best", type=int, default=3)
    a = ap.parse_args()
    if a.no_fla:
        sys.modules["fla"] = None
    os.makedirs(a.out, exist_ok=True)
    if WORLD > 1:
        torch.distributed.init_process_group("nccl", timeout=datetime.timedelta(hours=3))
    CPU = not torch.cuda.is_available()          # CPU = dry runs with a tiny model only (fp32, no 4-bit, torch AdamW)
    if CPU:
        dev, DT, a.quant = torch.device("cpu"), torch.float32, "none"
    else:
        torch.cuda.set_device(LOCAL)
        dev = torch.device("cuda", LOCAL)
        DT = torch.bfloat16 if torch.cuda.get_device_capability(LOCAL)[0] >= 8 else torch.float16
        DT = {"fp16": torch.float16, "bf16": torch.bfloat16}.get(a.dtype, DT)
    SC = torch.amp.GradScaler("cuda", enabled=(DT == torch.float16))
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import load_file
    import bitsandbytes as bnb

    tok = AutoTokenizer.from_pretrained(a.base)
    tools = json.load(open(a.tools, encoding="utf-8"))
    tools["none"] = None
    has_chat = bool(a.chat) and os.path.exists(a.chat) and os.path.getsize(a.chat) > 0
    caches = {}
    if RANK == 0:
        inc, caches["inc"] = prep(tok, a.inc, tools, a.max_len, a.out, "inc")
        chat, caches["chat"] = prep(tok, a.chat, tools, a.max_len, a.out, "chat") if has_chat else ([], None)
        dvl, caches["dev"] = prep(tok, a.dev, tools, a.max_len, a.out, "dev") if a.dev else ([], None)
        json.dump(caches, open(os.path.join(a.out, "caches.json"), "w"))
    barrier()
    if RANK:
        caches = json.load(open(os.path.join(a.out, "caches.json")))
        inc = torch.load(caches["inc"])
        chat = torch.load(caches["chat"]) if caches["chat"] else []
        dvl = torch.load(caches["dev"]) if caches["dev"] else []
    rows = {d["id"]: d for d in inc + chat}

    torch.manual_seed(1234)
    qc = None
    if a.quant == "nf4":
        qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=DT)
    if a.model_dir:      # pre-quantized NF4 (round-1 prequant.py): carries its own quantization config, low host RAM
        model = AutoModelForCausalLM.from_pretrained(a.model_dir, dtype=DT, device_map={"": "cpu" if CPU else LOCAL}, low_cpu_mem_usage=True)
    else:
        model = AutoModelForCausalLM.from_pretrained(a.base, dtype=DT, device_map={"": "cpu" if CPU else LOCAL}, quantization_config=qc, low_cpu_mem_usage=True)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=a.alpha, lora_dropout=a.lora_dropout, target_modules=TARGETS, bias="none",
                                             task_type="CAUSAL_LM"))
    params = [p for p in model.parameters() if p.requires_grad]
    if DT == torch.float16:     # trainable LoRA weights in fp32 under the scaler (fp16 masters would underflow)
        for p in params:
            p.data = p.data.float()
    log(a.out, "model loaded on %d GPU(s), dtype %s, quant %s, fla %s: VRAM %.2f GiB" % (
        WORLD, DT, a.quant, "off" if a.no_fla else "auto", 0 if CPU else torch.cuda.memory_allocated(dev) / 2 ** 30))
    opt = (torch.optim.AdamW if CPU else bnb.optim.AdamW8bit)(params, lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.999))

    # ---- resume state, then the schedule (it may merge newly arrived chat rows at the current step)
    step, ck = 0, os.path.join(a.out, "ckpt_latest")
    st = None
    if os.path.exists(os.path.join(ck, "state.pt")) and not a.probe_steps:
        st = torch.load(os.path.join(ck, "state.pt"), weights_only=False, map_location="cpu")
        step = st["step"]
    spath = os.path.join(a.out, "schedule.json")
    if a.probe_steps:
        longest = sorted(rows, key=lambda k: -len(rows[k]["ids"]))[:2]
        if a.probe_len:
            for j, k in enumerate(list(longest)):
                src = rows[k]["ids"]
                ids = src.repeat(a.probe_len // len(src) + 1)[:a.probe_len].clone()
                lab = torch.full_like(ids, -100)
                lab[-500:] = ids[-500:]
                rows["_synth%d" % j] = {"id": "_synth%d" % j, "kind": "incident", "family": "", "hard": False, "ids": ids, "labels": lab}
                longest[j] = "_synth%d" % j
        rest = [k for k in rows if k not in longest]
        random.Random(7).shuffle(rest)
        S = {"state": "probe", "groups": chunk(longest + rest[:a.accum * a.probe_steps - 2], a.accum), "e2": []}
    else:
        if RANK == 0:
            S = plan_schedule(spath, inc, chat, a.accum, step)
            json.dump(S, open(spath + ".part", "w"))
            os.replace(spath + ".part", spath)
        barrier()
        S = json.load(open(spath))
    mixed = S["state"] == "mixed"
    G1 = S["groups"]
    if mixed:
        E1 = len(G1)
        E2 = len(S["e2"])
    else:                                   # LR plan before the chat rows exist: planned sizes
        ninc_e2 = sum(1 for d in inc if is_e2(d))
        E1 = math.ceil((len(inc) + a.expect_chat) / a.accum)
        E2 = math.ceil((ninc_e2 + 0.42 * a.expect_chat) / a.accum)
    groups = G1 + (S["e2"] if (mixed and a.run_e2) else [])

    def lr_lambda(s):
        if s < E1:
            w = max(1, int(0.03 * E1))
            return min(1.0, (s + 1) / w) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, s / E1))))
        s2 = s - E1
        w = max(1, int(0.03 * E2))
        ramp = 0.1 + (a.e2_peak - 0.1) * min(1.0, (s2 + 1) / w)
        return ramp if s2 < w else a.e2_peak * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, (s2 - w) / max(1, E2 - w)))))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    if st is not None:
        set_peft_model_state_dict(model, load_file(os.path.join(ck, "adapter_model.safetensors"), device="cpu" if CPU else "cuda:%d" % LOCAL))
        if DT == torch.float16:
            for p in params:
                p.data = p.data.float()
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        if st.get("scaler") and SC.is_enabled():   # bf16 runs have no scaler state; fp16 after a bf16 ckpt starts a fresh scaler
            SC.load_state_dict(st["scaler"])
        if st.get("rng") is not None:
            torch.set_rng_state(st["rng"])
        log(a.out, "resumed at step %d (schedule %s, epoch-1 steps %d, epoch-2 steps %d, merged at %s)" % (step, S["state"], E1, E2, S.get("merged_at")))
    elif not a.probe_steps:
        log(a.out, "start: %d incident + %d chat rows, schedule %s: %d step groups now, epoch 1 = %d steps, epoch 2 = %d steps (%s); "
                   "trainable %.1fM, r=%d alpha=%d lr=%g max_len=%d" % (len(inc), len(chat), S["state"], len(G1), E1, E2,
                   "on" if a.run_e2 else "off", sum(p.numel() for p in params) / 1e6, a.r, a.alpha, a.lr, a.max_len))
    tok_inc = sum(len(d["ids"]) for d in inc)
    tok_chat = sum(len(d["ids"]) for d in chat) if chat else int(a.expect_chat * 3700)
    tok_e2 = sum(len(d["ids"]) for d in inc if is_e2(d)) + (sum(len(d["ids"]) for d in chat if d["hard"]) if chat else int(0.42 * a.expect_chat * 3700))
    if RANK == 0:
        json.dump({"incident_rows": len(inc), "chat_rows": len(chat), "schedule": S["state"], "e1_steps": E1, "e2_steps": E2,
                   "tokens_e1": tok_inc + tok_chat, "tokens_e2": tok_e2, "world": WORLD, "quant": a.quant, "no_fla": a.no_fla},
                  open(os.path.join(a.out, "plan.json"), "w"), indent=1)

    def status(extra=None):
        d = {"step": step, "e1_steps": E1, "e2_steps": E2, "schedule": S["state"], "epoch1_done": mixed and step >= E1,
             "done": mixed and step >= E1 + (E2 if a.run_e2 else 0) and a.run_e2, "t": time.time()}
        d.update(extra or {})
        json.dump(d, open(os.path.join(a.out, "status.json"), "w"))

    def save(tag="latest", extra=None):
        if RANK == 0:
            d = os.path.join(a.out, "ckpt_" + tag)
            tmp = d + ".part"
            os.makedirs(tmp, exist_ok=True)
            model.save_pretrained(tmp)
            if tag == "latest":
                torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": SC.state_dict() if SC.is_enabled() else {}, "step": step,
                            "rng": torch.get_rng_state(), "dtype": str(DT), "world": WORLD, "host": os.uname().nodename},
                           os.path.join(tmp, "state.pt"))
            if os.path.exists(d):
                os.system("rm -rf '%s'" % d)
            os.rename(tmp, d)
            status(extra)
        barrier()

    def dev_eval():
        if not dvl:
            return
        model.eval()
        acc = torch.zeros(4, device=dev, dtype=torch.float64)    # inc loss, inc tok, chat loss, chat tok
        with torch.no_grad():
            for d in dvl[RANK::WORLD]:
                try:
                    l, n = loss_fn(model, d["ids"], d["labels"], dev)
                except (torch.OutOfMemoryError, RuntimeError) as e:  # "CUDA driver error: out of memory" is a RuntimeError
                    if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                        raise
                    torch.cuda.empty_cache()
                    continue
                j = 0 if d["kind"] == "incident" else 2
                acc[j] += float(l)
                acc[j + 1] += n
        allreduce(acc)
        model.train()
        r = {"step": step, "dev_incident": round(float(acc[0] / max(1, acc[1])), 4), "dev_chat": round(float(acc[2] / max(1, acc[3])), 4), "t": time.time()}
        log(a.out, "DEV step %d incident %.4f chat %.4f" % (step, r["dev_incident"], r["dev_chat"]))
        if RANK == 0:
            with open(os.path.join(a.out, "dev.jsonl"), "a") as f:
                f.write(json.dumps(r) + "\n")

    GS = gen_slices(a) if (a.gen_inc or a.gen_chat) and not a.probe_steps else None
    bpath = os.path.join(a.out, "best.json")
    best = json.load(open(bpath)) if os.path.exists(bpath) else {"top": [], "best": None, "since_best": 0, "evals": 0}

    def gen_hook():
        """generation dev score -> gen_eval.jsonl; best-K checkpoints (ckpt_best_XXXX); True = early stop (patience)"""
        if not GS:
            return False
        model.eval()
        model.config.use_cache = True
        res = {}
        for name, (ir, cr) in GS.items():
            if not ir and not cr:
                continue
            v = allreduce(gen_score(model, tok, tools, ir[RANK::WORLD], cr[RANK::WORLD], dev))
            inc_s = float(v[1] + v[2] + v[3]) / max(1.0, 3 * float(v[0]))
            ch_s = float(v[5]) / max(1.0, float(v[4]))
            parts = [x for x, n in ((inc_s, v[0]), (ch_s, v[4])) if n > 0]
            res[name] = {"n_inc": int(v[0]), "parse": round(float(v[1]) / max(1.0, float(v[0])), 3),
                         "severity": round(float(v[2]) / max(1.0, float(v[0])), 3), "label": round(float(v[3]) / max(1.0, float(v[0])), 3),
                         "n_chat": int(v[4]), "chat_pass": round(ch_s, 3), "score": round(sum(parts) / max(1, len(parts)), 4)}
        model.config.use_cache = False
        model.train()
        sc = res.get("dev", {}).get("score")
        rec = {"step": step, "t": time.time(), **res}
        if "train" in res and sc is not None:
            rec["gap"] = round(res["train"]["score"] - sc, 4)
        log(a.out, "GEN step %d %s" % (step, json.dumps(rec)))
        if RANK == 0:
            with open(os.path.join(a.out, "gen_eval.jsonl"), "a") as f:
                f.write(json.dumps(rec) + "\n")
        if sc is None or not mixed:          # best-K / patience only once the chat rows are in the plan
            return False
        best["evals"] += 1
        if best["best"] is None or sc > best["best"]:
            best["best"], best["since_best"] = sc, 0
        else:
            best["since_best"] += 1
        top = sorted(best["top"] + [[sc, step]], key=lambda x: (-x[0], -x[1]))
        keep, drop = top[:a.keep_best], top[a.keep_best:]
        if [sc, step] in keep:
            save("best_%04d" % step)
        if RANK == 0:
            for _, s_ in drop:
                os.system("rm -rf '%s'" % os.path.join(a.out, "ckpt_best_%04d" % s_))
        best["top"] = keep
        if RANK == 0:
            json.dump(best, open(bpath, "w"), indent=1)
        return best["since_best"] >= a.patience

    model.train()
    t0, tok_count, run_loss, run_n = time.time(), 0, 0.0, 0
    tstart, ptok, ptime, poom, ploss = time.time(), 0, 0.0, 0, []
    deadline = time.time() + a.hours * 3600
    if step == 0 and not a.probe_steps and not os.path.exists(os.path.join(a.out, "dev.jsonl")):
        dev_eval()
    while True:
        # ---- plan boundaries
        if a.probe_steps and step >= len(groups):
            break
        if not a.probe_steps:
            if mixed and best["since_best"] >= a.patience:
                log(a.out, "EARLY STOP already reached (best %s): nothing to train" % best["top"])
                return 6
            if mixed and step == E1 and not os.path.exists(os.path.join(a.out, "ckpt_epoch1")):
                save()
                save("epoch1")
                dev_eval()
                log(a.out, "EPOCH 1 DONE at step %d: ckpt_epoch1 saved" % step)
            if mixed and step >= E1 and not a.run_e2:
                status({"stopped": "after_epoch1"})
                log(a.out, "STOP after epoch 1 (no --run-e2)")
                return 5
            if step >= len(groups):
                if not mixed:
                    save(extra={"waiting": "chat"})
                    log(a.out, "WAIT_CHAT: incident part of epoch 1 done at step %d; add bundle B (chat rows) and resume" % step)
                    return 4
                save()
                save("final")
                dev_eval()
                log(a.out, "TRAINING DONE step %d" % step)
                return 0
        flag = torch.zeros(1, device=dev)
        if RANK == 0 and (time.time() > deadline or os.path.exists(os.path.join(a.out, "STOP"))):
            flag[0] = 1
        allreduce(flag)
        if flag[0] > 0:
            if not a.probe_steps:
                save()
            log(a.out, "EXIT (hours limit / STOP) at step %d" % step)
            return 3
        group = groups[step]
        mine = group[RANK::WORLD]
        lsum = torch.zeros(3, device=dev, dtype=torch.float64)   # loss sum, label tokens, oom
        for j, k in enumerate(mine):
            ex = rows[k]
            tq = time.time()
            try:
                l, n = loss_fn(model, ex["ids"], ex["labels"], dev)
                SC.scale(l / max(1, n) / a.accum).backward()
                lsum[0] += float(l) / max(1, n)
                lsum[1] += n
                tok_count += len(ex["ids"])
                if a.probe_steps and not (step == 0 and RANK * 1 + j * WORLD < 2):   # skip the 2 longest (warm-up) rows
                    ptok += len(ex["ids"])
                    ptime += time.time() - tq
                ploss.append(float(l) / max(1, n))
            except (torch.OutOfMemoryError, RuntimeError) as e:  # "CUDA driver error: out of memory" is a RuntimeError
                if not isinstance(e, torch.OutOfMemoryError) and "out of memory" not in str(e):
                    raise
                lsum[2] += 1
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM on %s (%d tokens): optimizer step skipped" % (ex["id"], len(ex["ids"])))
                break
        allreduce(lsum)
        if lsum[2] > 0:
            opt.zero_grad(set_to_none=True)
            step += 1
            poom += 1
            continue
        if WORLD > 1:   # one flat all-reduce of the LoRA gradients (sum over ranks = single-GPU accumulation)
            gs = [p.grad if p.grad is not None else torch.zeros_like(p) for p in params]
            flat = torch._utils._flatten_dense_tensors(gs)
            torch.distributed.all_reduce(flat)
            for p, g in zip(params, torch._utils._unflatten_dense_tensors(flat, gs)):
                p.grad = g
        SC.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        SC.step(opt)
        SC.update()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        run_loss += float(lsum[0]) / len(group)
        run_n += 1
        if a.probe_steps:
            continue
        if step % 5 == 0:
            el = time.time() - t0
            tk = torch.tensor([float(tok_count)], device=dev)
            allreduce(tk)
            seg_end = E1 if step < E1 else E1 + E2
            eta = (el / run_n) * (seg_end - step)
            log(a.out, "step %d/%d (%s) loss %.4f lr %.2e %.0f tok/s ETA %s %.1f h scale %.0f" % (
                step, seg_end, "e1" if step <= E1 else "e2", run_loss / run_n, sched.get_last_lr()[0], float(tk[0]) / el,
                "epoch1" if step < E1 else "epoch2", eta / 3600, SC.get_scale() if SC.is_enabled() else 1))
            if RANK == 0:
                with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                    f.write(json.dumps({"step": step, "loss": run_loss / run_n, "lr": sched.get_last_lr()[0], "tok_s": float(tk[0]) / el,
                                        "t": time.time()}) + "\n")
            run_loss, run_n = 0.0, 0
            t0, tok_count = time.time(), 0
        if step % a.save_every == 0:
            save()
            if step % a.keep_every == 0:
                save("step%04d" % step)
            log(a.out, "checkpoint step %d" % step)
        if step % a.eval_every == 0:
            dev_eval()
        if step % a.gen_every == 0 or (mixed and step == E1):
            if gen_hook():
                save(extra={"stopped": "early_stop", "best": best})
                log(a.out, "EARLY STOP at step %d: dev generation score not better for %d evals (best %s)" % (step, a.patience, best["top"]))
                return 6
    # ---- probe result: aggregate speed over ranks (each rank measures its own rows; the ranks run concurrently)
    pt = torch.tensor([float(ptok), ptime, 0.0 if CPU else float(torch.cuda.max_memory_allocated(dev)) / 2 ** 30], device=dev, dtype=torch.float64)
    tot = allreduce(pt.clone())
    mx = allreduce(pt.clone(), torch.distributed.ReduceOp.MAX if WORLD > 1 else None)
    tps = float(tot[0]) / max(1e-6, float(mx[1]))          # all tokens / the slowest rank's busy time
    lv = sum(ploss) / max(1, len(ploss))
    res = {"world": WORLD, "quant": a.quant, "fla": not a.no_fla, "dtype": str(DT).split(".")[-1], "tok_s": round(tps, 1),
           "peak_vram_gib": round(float(mx[2]), 2), "loss": round(lv, 4), "oom_steps": poom,
           "longest_tokens": max(len(rows[k]["ids"]) for k in groups[0]),
           "proj_e1_h": round((tok_inc + tok_chat) / max(1, tps) / 3600, 1), "proj_e2_h": round(tok_e2 / max(1, tps) / 3600, 1)}
    log(a.out, "PROBE_RESULT " + json.dumps(res))
    return 0


if __name__ == "__main__":
    rc = main()
    if WORLD > 1 and torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()
    sys.exit(rc)
