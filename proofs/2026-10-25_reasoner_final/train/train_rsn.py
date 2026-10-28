"""QLoRA SFT of Qwen3.5-4B as the cross-domain reasoner (SPEC.md §6). Resumable, one GPU job, agent-owned.
  python train_rsn.py --out ~/smartcity_runs/reasoner_v1/run1 [--probe 20] [--hours 14]
- data: data/train_mix.jsonl rendered with the model's own chat template (tools attached, thinking off); loss only on
  assistant spans (tool calls and final answers); logits computed only at label positions (248k vocab).
- checkpoint (adapter + optimizer + scheduler + cursor + RNG) every --save-every optimizer steps; resume from latest.
- exits (after saving) on: HEARTBEAT older than 15 min, STOP file, --hours, SIGTERM. Thermal pause at 76 C / resume 68 C.
"""
import argparse
import json
import math
import os
import random
import signal
import subprocess
import sys
import time

import torch

ROOT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final"
P0 = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_reasoner_research/P0/host_bench"
M = os.path.expanduser("~/models/qwen3.5-4b")
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj", "in_proj_qkv", "in_proj_z", "in_proj_a",
           "in_proj_b", "out_proj"]
STOP = {"flag": None}
PAUSE_FILE = ROOT + "/PAUSE_GPU"          # written by PAUSE_GPU.cmd (owner); removed by the agent to resume


def stale_limit():
    """owner rule: 4 h heartbeat tolerance at night (22:00-08:00 IST), 15 min by day"""
    h = time.gmtime(time.time() + 19800).tm_hour
    return 14400 if (h >= 22 or h < 8) else 900


def log(out, msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(os.path.join(out, "train.log"), "a") as f:
        f.write(line + "\n")


def tools_for(kind):
    if kind == "none":
        return None
    return json.load(open(ROOT + "/pipeline/tools_v3.json"))[kind]


def encode(tok, ex, tools, max_len):
    msgs = ex["messages"]
    kw = dict(tools=tools, tokenize=False, enable_thinking=False)
    full = tok.apply_chat_template(msgs, **kw)
    spans = []
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        g = tok.apply_chat_template(msgs[:i], add_generation_prompt=True, **kw)
        f = tok.apply_chat_template(msgs[:i + 1], **kw)
        if not (f.startswith(g) and full.startswith(f)):
            return None
        end = f.rindex("<|im_end|>") + len("<|im_end|>")
        spans.append((len(g), end))
    enc = tok(full, return_offsets_mapping=True, add_special_tokens=False)
    ids = enc["input_ids"]
    labels = [-100] * len(ids)
    for k, (a, b) in enumerate(enc["offset_mapping"]):
        for s, e in spans:
            if a >= s and b <= e and b > a:
                labels[k] = ids[k]
    if len(ids) > max_len or not any(l != -100 for l in labels):
        return None
    return ids, labels


def prep(tok, path, max_len, cache):
    if os.path.exists(cache):
        return torch.load(cache)
    tl = {"incident": tools_for("incident"), "chat": tools_for("chat"), "none": None}
    data, skipped = [], 0
    for line in open(path, encoding="utf-8"):
        ex = json.loads(line)
        r = encode(tok, ex, tl[ex["tools"]], max_len)
        if r is None:
            skipped += 1
            continue
        data.append({"id": ex["id"], "ids": r[0], "labels": r[1]})
    torch.save(data, cache)
    L = sorted(len(d["ids"]) for d in data)
    print("prep %s: %d kept, %d skipped; tokens p50 %d p90 %d max %d" % (os.path.basename(path), len(data), skipped,
          L[len(L) // 2], L[int(len(L) * .9)], L[-1]), flush=True)
    return data


def gpu_temp():
    try:
        return int(subprocess.check_output(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]).decode().strip())
    except Exception:
        return 0


def loss_fn(model, ids, labels):
    """hidden states once; lm_head + CE only at label positions, in checkpointed chunks (never full 248k-vocab logits)"""
    from torch.utils.checkpoint import checkpoint
    inner = model.get_base_model()
    x = torch.tensor([ids], device="cuda")
    y = torch.tensor(labels[1:] + [-100], device="cuda")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default=ROOT + "/data/train_mix.jsonl")
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--keep-every", type=int, default=100)
    ap.add_argument("--hours", type=float, default=14)
    ap.add_argument("--probe", type=int, default=0, help="run N micro-steps, report memory/speed, exit")
    ap.add_argument("--thermal-pause-at", type=int, default=75)
    ap.add_argument("--thermal-resume-at", type=int, default=65)
    ap.add_argument("--init-adapter", default="", help="continue from this PEFT adapter (round 2: step 612)")
    ap.add_argument("--probe-trunc", type=int, default=0, help="probe only: keep the last N tokens of each example")
    ap.add_argument("--hb", default=os.path.expanduser("~/smartcity_runs/reasoner_v1/HEARTBEAT"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *x: STOP.__setitem__("flag", "sigterm"))
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, set_peft_model_state_dict
    from safetensors.torch import load_file
    import bitsandbytes as bnb

    tok = AutoTokenizer.from_pretrained(M)
    data = prep(tok, a.data, 4096, os.path.join(a.out, "train_tok.pt"))
    data = [d for d in data if len(d["ids"]) <= a.max_len]
    if a.probe and a.probe_trunc:
        data = [{"id": d["id"], "ids": d["ids"][-a.probe_trunc:], "labels": d["labels"][-a.probe_trunc:]} for d in data]
    torch.manual_seed(1234)
    MQ = os.path.expanduser("~/models/qwen3.5-4b-nf4")      # pre-quantized NF4 base (prequant.py): low host-RAM load
    if os.path.isdir(MQ):
        model = AutoModelForCausalLM.from_pretrained(MQ, dtype=torch.bfloat16, device_map={"": 0}, low_cpu_mem_usage=True)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            M, dtype=torch.bfloat16, device_map={"": 0},
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                   bnb_4bit_compute_dtype=torch.bfloat16))
    # not prepare_model_for_kbit_training: it casts the 248k x 2560 tied embedding to fp32 (+2.5 GB, OOM on 6 GB)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=a.alpha, lora_dropout=0.0, target_modules=TARGETS, bias="none",
                                             task_type="CAUSAL_LM"))
    log(a.out, "model loaded: VRAM %.2f GiB" % (torch.cuda.memory_allocated() / 2 ** 30))
    if a.init_adapter and not os.path.exists(os.path.join(a.out, "ckpt_latest", "state.pt")):
        set_peft_model_state_dict(model, load_file(os.path.join(a.init_adapter, "adapter_model.safetensors")))
        log(a.out, "initialised from adapter %s" % a.init_adapter)
    ntrain = sum(p.numel() for p in model.parameters() if p.requires_grad)
    opt = bnb.optim.AdamW8bit([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0, betas=(0.9, 0.999))
    steps_per_epoch = math.ceil(len(data) / a.accum)
    total = int(steps_per_epoch * a.epochs)
    warm = max(1, int(0.03 * total))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, s / total)))))
    # order: per epoch shuffle, fixed seeds -> resumable cursor
    order = []
    for ep in range(math.ceil(a.epochs)):
        o = list(range(len(data)))
        random.Random(100 + ep).shuffle(o)
        order += o
    order = order[:total * a.accum]
    step, cursor = 0, 0
    ck = os.path.join(a.out, "ckpt_latest")
    if os.path.exists(os.path.join(ck, "state.pt")) and not a.probe:
        st = torch.load(os.path.join(ck, "state.pt"), weights_only=False)
        set_peft_model_state_dict(model, load_file(os.path.join(ck, "adapter_model.safetensors")))
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        step, cursor = st["step"], st["cursor"]
        torch.set_rng_state(st["rng"])
        log(a.out, "resumed at step %d/%d (cursor %d)" % (step, total, cursor))
    else:
        log(a.out, "start: %d examples, %d steps (%d/epoch), trainable %.1fM, r=%d alpha=%d lr=%g" % (len(data), total, steps_per_epoch, ntrain / 1e6, a.r, a.alpha, a.lr))

    def save(tag="latest"):
        d = os.path.join(a.out, "ckpt_" + tag)
        tmp = d + ".part"
        os.makedirs(tmp, exist_ok=True)
        model.save_pretrained(tmp)
        if tag == "latest":
            torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "step": step, "cursor": cursor,
                        "rng": torch.get_rng_state()}, os.path.join(tmp, "state.pt"))
        if os.path.exists(d):
            os.system("rm -rf '%s'" % d)
        os.rename(tmp, d)
        json.dump({"step": step, "total": total, "cursor": cursor, "done": step >= total, "t": time.time()},
                  open(os.path.join(a.out, "status.json"), "w"))

    model.train()
    t0, tok_count, run_loss, run_n = time.time(), 0, 0.0, 0
    deadline = t0 + a.hours * 3600
    micro = 0
    while step < total:
        # guards
        if a.hb and os.path.exists(a.hb) and time.time() - os.path.getmtime(a.hb) > stale_limit():
            STOP["flag"] = "heartbeat stale"
        if os.path.exists(PAUSE_FILE):
            STOP["flag"] = "owner PAUSE_GPU"
        if os.path.exists(os.path.join(a.out, "STOP")):
            STOP["flag"] = "STOP file"
        if time.time() > deadline:
            STOP["flag"] = "hours limit"
        if STOP["flag"]:
            if not a.probe:
                save()
            log(a.out, "EXIT (%s) at step %d" % (STOP["flag"], step))
            return 3
        if micro % 8 == 0 and gpu_temp() >= a.thermal_pause_at:
            tp = time.time()
            while gpu_temp() > a.thermal_resume_at:
                time.sleep(10)
            log(a.out, "THERMAL pause %.0f s" % (time.time() - tp))
        if cursor + a.accum > len(order):
            break
        lsum, nsum, oom = 0.0, 0, False
        for k in range(a.accum):
            ex = data[order[cursor]]
            cursor += 1
            try:
                l, n = loss_fn(model, ex["ids"], ex["labels"])
                (l / max(1, n) / a.accum).backward()
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if "out of memory" not in str(e) and not isinstance(e, torch.OutOfMemoryError):
                    raise
                oom = True
                l = None
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                log(a.out, "OOM on %s (%d tokens): accumulation step skipped" % (ex["id"], len(ex["ids"])))
                cursor += a.accum - k - 1
                break
            lsum += l.item()
            nsum += n
            tok_count += len(ex["ids"])
            micro += 1
            if a.probe and micro >= a.probe:
                dt_ = time.time() - t0
                log(a.out, "PROBE %d micro-steps %.1f s/ex, peak VRAM %.2f GiB, loss %.3f" % (micro, dt_ / micro,
                    torch.cuda.max_memory_allocated() / 2 ** 30, lsum / max(1, nsum)))
                return 0
        if oom:
            continue
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        run_loss += lsum / max(1, nsum)
        run_n += 1
        if step % 5 == 0:
            el = time.time() - t0
            eta = (el / run_n) * (total - step)     # time per step over the last 5 steps x remaining
            log(a.out, "step %d/%d loss %.4f lr %.2e %.0f tok/s ETA %.1f h" % (step, total, run_loss / run_n, sched.get_last_lr()[0],
                                                                            tok_count / el, eta / 3600))
            with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                f.write(json.dumps({"step": step, "loss": run_loss / run_n, "lr": sched.get_last_lr()[0], "t": time.time()}) + "\n")
            run_loss, run_n = 0.0, 0
            t0, tok_count = time.time(), 0
            el = 0
        if step % a.save_every == 0 or step == total:
            save()
            if step % a.keep_every == 0 or step == total:
                save("step%04d" % step)
            log(a.out, "checkpoint step %d" % step)
    if step < total:            # data exhausted early because of OOM-skipped steps
        log(a.out, "data exhausted at step %d of %d (OOM skips)" % (step, total))
        step = total
        save()
        save("step%04d" % step)
    log(a.out, "TRAINING DONE step %d" % step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
