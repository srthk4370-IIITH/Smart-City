"""rsn v3 fine-tune (2026-11-13, proofs/2026-11-13_v3_train/rsn_ft/README.md): short fine-tune of the EDITED r3-2800 model on the
v4-format data (proofs/2026-11-13_v3_data/rsn) + r3-format replay. Adapted from topup_train.py (r4, never run); differences:
  --base may point to the edited base dir (merged weights); --init-adapter is OPTIONAL (absent = fresh LoRA --lora-r/--lora-alpha
  on --base); tools are picked by each row's "tools" key (incident_v4 / chat_r5 / incident / chat); the "r4" gen slices are the
  v4 dev slices (--gen-v4-inc / --gen-v4-chat; chat scored with the chat_r5 header).
Original r4 notes follow.
rsn_v3 r4 top-up: continue the gated 4B r3 adapter (step 2800) on r4 rows + r3 replay, keeping every 6 GB fit / speed lever of
train_rsn3.py (it is imported, not changed: the r3 trainer and its jobs stay byte-identical). TOPUP.md has the design.

What differs from train_rsn3.py main():
- --init-adapter: the LoRA weights are loaded from the start adapter (r / alpha / targets read from its adapter_config.json and
  required to match); the optimizer, scheduler and step start fresh. INIT_CHECK: every LoRA tensor is compared with the file
  right after loading; any difference aborts (exit 10). A resume (ckpt_latest/state.pt) never reads --init-adapter again.
- schedule: every optimizer step = accum x mix rows of --new + the rest from --replay (default 8 + 8, i.e. 1:1); one pass over
  --new (x --epochs); the replay list is reshuffled and cycled when it is shorter. schedule.json = the data cursor (resumable).
- LR --lr (3e-5) with warmup --warmup (3 %) and cosine to --floor (0.1) x LR over the whole plan.
- generation eval (every --gen-every steps AND at step 0 = the start adapter): slice "r4" (r4 dev incidents with the row's own
  think mode, think-aware parse + severity + label + think decision; r4 dev chat records via verify_chat) and slice "r3" (the
  r3 run's gen slices, train_rsn3.gen_score unchanged). Combined score = w x r4 + (1 - w) x r3. A checkpoint is kept (best-K)
  only if combined > start combined AND r3 >= start r3 - --r3-tol (a cross-domain gain cannot hide an r3 regression).
  Patience counts evaluations without a new best combined score among eligible ones.
Exit codes: 0 plan done, 3 hours / STOP / --max-steps, 6 early stop, 7 OOM STOP (--oom-stop), 9 data check, 10 init check.
  python topup_train.py --base B --model-dir NF4 --init-adapter CKPT --tools tools_r3.json --new train_new.jsonl --replay replay.jsonl
         --out DIR --gen-r4-inc dev_inc.jsonl --gen-r4-chat dev_chat.jsonl --gen-inc gen_inc_r2.jsonl --gen-chat gen_chat_r3.jsonl
         --micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix --oom-stop"""
import argparse
import json
import math
import os
import random
import sys
import time

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
KG = os.environ.get("RSN3_KG", os.path.abspath(os.path.join(HERE, "..", "..", "2026-10-29_rsn_v3", "kaggle")))
sys.path.insert(0, KG)
import train_rsn3 as T  # noqa: E402


def split_think(t):
    """(think, rest) of a generation: text before '</think>' (leading '<think>' dropped) when the close tag comes before the
    report JSON; otherwise ('', t)."""
    t = t or ""
    i = t.find("</think>")
    j = t.find("{")
    if i < 0 or (0 <= j < i and not t.lstrip().startswith("<think>")):
        return "", t
    th = t[:i].strip()
    if th.startswith("<think>"):
        th = th[len("<think>"):].strip()
    return th, t[i + len("</think>"):]


def gold_of(row):
    """(report dict, gold think text) of an r4 incident row: reasoning_content or an inline <think> block"""
    m = row["messages"][-1]
    th, rest = split_think(m.get("content") or "")
    th = (m.get("reasoning_content") or th or "").strip()
    return json.loads(rest.strip()), th


def load_slice(path, n, seed, inc):
    if not path or not os.path.exists(path):
        return []
    rs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if inc:
        rs = [r for r in rs if str(r.get("tools", "")).startswith("incident") and not any(m["role"] == "tool" for m in r["messages"])]
    random.Random(seed).shuffle(rs)
    return rs[:n] if n else rs


def gen_score_r4_inc(model, tok, tools, rows, dev):
    """[n, parse, severity, label, think_ok]: prompt in the row's own think mode (r4: adaptive = thinking on); the report is
    parsed after the think block; think_ok = (generated think non-empty) == (gold think non-empty)"""
    sys.path.insert(0, KG)
    import chatloop as CL
    out = [0.0] * 5
    if not rows:
        return out
    be = CL.HFBackend(model, tok, temperature=0.0, max_new=900, tok_budget=int(os.environ.get("RSN3_GEN_TOK_BUDGET", "24000")),
                      max_batch=8, log=lambda m: None)
    th = [bool(r.get("think")) for r in rows]
    prompts = [tok.apply_chat_template(r["messages"][:2], tools=tools.get(r.get("tools"), tools["incident"]), tokenize=False,
                                       add_generation_prompt=True, enable_thinking=t) for r, t in zip(rows, th)]
    for r, (txt, _) in zip(rows, be.generate(prompts, th)):
        g, gth = gold_of(r)
        pth, rest = split_think(txt)
        p = T._parse_report(rest)
        out[0] += 1
        out[4] += float(bool(pth) == bool(gth))
        if isinstance(p, dict):
            out[1] += 1
            out[2] += float(p.get("severity") == g.get("severity"))
            out[3] += float(p.get("label") == g.get("label"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--init-adapter", default="", help="start LoRA (read only): adapter_config.json + adapter_model.safetensors; "
                    "empty = fresh LoRA on --base (the edited model already holds r3-2800)")
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=int, default=64)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--new", required=True, help="r4 train_new rows")
    ap.add_argument("--replay", required=True, help="replay rows (r3)")
    ap.add_argument("--dev", default="", help="rows for the dev loss (optional)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--warmup", type=float, default=0.03)
    ap.add_argument("--floor", type=float, default=0.1)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--mix", type=float, default=0.5, help="share of --new rows per step")
    ap.add_argument("--epochs", type=float, default=1.0, help="passes over --new")
    ap.add_argument("--max-len", type=int, default=7424)
    ap.add_argument("--max-drop", type=float, default=0.02, help="abort (exit 9) when more than this share of --new is dropped")
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--eval-every", type=int, default=100)
    ap.add_argument("--gen-every", type=int, default=100)
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--quant", default="nf4", choices=["nf4", "none"])
    ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16"])
    ap.add_argument("--no-fla", action="store_true")
    ap.add_argument("--lora-dropout", type=float, default=-1, help="default: the start adapter's")
    ap.add_argument("--wd", type=float, default=0.01)
    # fit / speed levers (train_rsn3.py, FIT.md, speed/EQUIV.md)
    ap.add_argument("--micro-tokens", type=int, default=0)
    ap.add_argument("--head-cpu", action="store_true")
    ap.add_argument("--ckpt-offload", action="store_true")
    ap.add_argument("--mlp-chunk", type=int, default=0)
    ap.add_argument("--mlp-chunk-min", type=int, default=0)
    ap.add_argument("--offload-min", type=int, default=0)
    ap.add_argument("--shared-prefix", action="store_true")
    ap.add_argument("--shared-prefix-min", type=int, default=256)
    ap.add_argument("--shared-prefix-cont", type=int, default=2048)
    ap.add_argument("--oom-stop", action="store_true")
    ap.add_argument("--lean-host", action="store_true")
    # generation eval
    ap.add_argument("--gen-r4-inc", "--gen-v4-inc", dest="gen_r4_inc", default="")
    ap.add_argument("--gen-r4-chat", "--gen-v4-chat", dest="gen_r4_chat", default="")
    ap.add_argument("--gen-r4-n", type=int, default=60)
    ap.add_argument("--gen-inc", default="", help="r3 incident gen slice")
    ap.add_argument("--gen-chat", default="", help="r3 chat gen slice")
    ap.add_argument("--gen-n", type=int, default=40)
    ap.add_argument("--gen-r3", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--gen-r3-tools", default="")
    ap.add_argument("--w-r4", type=float, default=0.5)
    ap.add_argument("--r3-tol", type=float, default=0.01)
    ap.add_argument("--r3-ref", type=float, default=-1, help="r3-slice score of r3-2800 itself (gen_eval r3 score of the unedited "
                    "model); when set, eligibility needs r3 >= r3-ref - r3-tol (owner gate: r3 slices >= r3-2800 - 0.01)")
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--keep-best", type=int, default=3)
    ap.add_argument("--step-log", action="store_true")
    a = ap.parse_args()
    assert T.WORLD == 1, "single GPU only"
    if a.no_fla:
        sys.modules["fla"] = None
    os.makedirs(a.out, exist_ok=True)
    log = lambda m: T.log(a.out, m)  # noqa: E731
    CPU = not torch.cuda.is_available()
    if CPU:
        dev, DT, a.quant = torch.device("cpu"), torch.float32, "none"
    else:
        dev = torch.device("cuda", 0)
        DT = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
        DT = {"fp16": torch.float16, "bf16": torch.bfloat16}.get(a.dtype, DT)
    SC = torch.amp.GradScaler("cuda", enabled=(DT == torch.float16))
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict, get_peft_model_state_dict
    from safetensors.torch import load_file

    if a.init_adapter:
        ac = json.load(open(os.path.join(a.init_adapter, "adapter_config.json")))
        assert not ac.get("use_rslora") and not ac.get("use_dora"), "plain LoRA expected"
        assert sorted(ac["target_modules"]) == sorted(T.TARGETS), "start adapter targets differ from train_rsn3.TARGETS"
    else:
        ac = {"r": a.lora_r, "lora_alpha": a.lora_alpha, "lora_dropout": 0.05, "target_modules": list(T.TARGETS)}
    if a.lora_dropout < 0:
        a.lora_dropout = float(ac.get("lora_dropout", 0.05))

    tok = AutoTokenizer.from_pretrained(a.base)
    tools = json.load(open(a.tools, encoding="utf-8"))
    tools["none"] = None
    T.LEAN_MMAP = a.lean_host
    new, _ = T.prep(tok, a.new, tools, a.max_len, a.out, "new")
    rep, _ = T.prep(tok, a.replay, tools, a.max_len, a.out, "replay")
    dvl = T.prep(tok, a.dev, tools, a.max_len, a.out, "dev")[0] if a.dev else []
    n_lines = sum(1 for l in open(a.new, encoding="utf-8") if l.strip())
    drop = 1 - len(new) / max(1, n_lines)
    log("data: new %d/%d rows kept (dropped %.2f %%: too long for max_len %d or unencodable), replay %d, dev %d" % (
        len(new), n_lines, 100 * drop, a.max_len, len(rep), len(dvl)))
    if drop > a.max_drop or not new or not rep:
        log("DATA CHECK FAILED: dropped %.2f %% of --new (limit %.2f %%) or an empty file" % (100 * drop, 100 * a.max_drop))
        return 9
    if a.lean_host:
        for d in new + rep + dvl:
            mk = d["labels"] != -100
            assert torch.equal(d["labels"][mk], d["ids"][mk])
            d["labels"] = mk
        T.host_trim()
    rows = {}
    for d in rep:
        rows["R:" + d["id"]] = d
    for d in new:
        rows["N:" + d["id"]] = d

    torch.manual_seed(1234)
    src = a.model_dir or a.base
    kw = dict(dtype=DT, device_map={"": "cpu" if CPU else 0}, low_cpu_mem_usage=True)
    if not a.model_dir and a.quant == "nf4":
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                                                       bnb_4bit_compute_dtype=DT)
    if not a.model_dir:
        kw["attn_implementation"] = os.environ.get("RSN3_ATTN", "sdpa")
    model = AutoModelForCausalLM.from_pretrained(src, **kw)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=ac["r"], lora_alpha=ac["lora_alpha"], lora_dropout=a.lora_dropout,
                                             target_modules=T.TARGETS, bias="none", task_type="CAUSAL_LM"))
    params = [p for p in model.parameters() if p.requires_grad]
    if not CPU:
        log("fit levers: %s" % T.apply_fit_levers(model, a, dev))
        if a.lean_host:
            T.host_trim()
        log("host RSS %d MB after model load" % T.host_rss_mb())

    ck = os.path.join(a.out, "ckpt_latest")
    st = None
    if os.path.exists(os.path.join(ck, "state.pt")):
        st = torch.load(os.path.join(ck, "state.pt"), weights_only=False, map_location="cpu")
    wsrc = ck if st is not None else a.init_adapter
    if not wsrc:                                   # fresh LoRA on the edited base: B = 0, so step 0 == the edited model
        sd = {k: v.detach().clone() for k, v in get_peft_model_state_dict(model).items()}
        wsrc = "(fresh LoRA r %d alpha %d on %s)" % (ac["r"], ac["lora_alpha"], a.base)
    else:
        sd = load_file(os.path.join(wsrc, "adapter_model.safetensors"), device="cpu" if CPU else "cuda:0")
    set_peft_model_state_dict(model, sd)
    # INIT_CHECK: the model's LoRA tensors == the file (exact), before any dtype change
    cur = get_peft_model_state_dict(model)
    miss = [k for k in sd if k not in cur]
    diff = max([float((cur[k].float() - sd[k].float()).abs().max()) for k in sd if k in cur] or [float("inf")])
    log("INIT_CHECK %s: %d tensors, %d missing, max_abs %.3g" % (wsrc, len(sd), len(miss), diff))
    if miss or diff != 0.0 or len(cur) != len(sd):
        log("INIT_CHECK FAILED (missing %s, model tensors %d)" % (miss[:3], len(cur)))
        return 10
    del sd, cur
    if DT == torch.float16:
        for p in params:
            p.data = p.data.float()
    import bitsandbytes as bnb
    opt = (torch.optim.AdamW if CPU else bnb.optim.AdamW8bit)(params, lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.999))

    # ---- schedule (deterministic, resumable)
    spath = os.path.join(a.out, "schedule.json")
    if os.path.exists(spath):
        S = json.load(open(spath))
    else:
        k_new = max(1, int(round(a.accum * a.mix)))
        k_rep = a.accum - k_new
        nk = ["N:" + d["id"] for d in new]
        rk = ["R:" + d["id"] for d in rep]
        seq_new = []
        for e in range(math.ceil(a.epochs)):
            k = list(nk)
            random.Random(404 + e).shuffle(k)
            seq_new += k
        seq_new = seq_new[:int(round(a.epochs * len(nk)))]
        ns = math.ceil(len(seq_new) / k_new)
        seq_rep, e = [], 0
        while len(seq_rep) < ns * k_rep:
            k = list(rk)
            random.Random(505 + e).shuffle(k)
            seq_rep += k
            e += 1
        groups = [seq_new[i * k_new:(i + 1) * k_new] + seq_rep[i * k_rep:(i + 1) * k_rep] for i in range(ns)]
        S = {"state": "topup", "groups": groups, "k_new": k_new, "k_rep": k_rep, "init_adapter": a.init_adapter,
             "new_md5": T.md5(a.new), "replay_md5": T.md5(a.replay), "lr": a.lr}
        json.dump(S, open(spath + ".part", "w"))
        os.replace(spath + ".part", spath)
    groups = S["groups"]
    NS = len(groups)

    def lr_lambda(s):
        w = max(1, int(a.warmup * NS))
        return min(1.0, (s + 1) / w) * (a.floor + (1 - a.floor) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / NS))))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    step = 0
    if st is not None:
        step = st["step"]
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        if st.get("scaler") and SC.is_enabled():
            SC.load_state_dict(st["scaler"])
        if st.get("rng") is not None:
            torch.set_rng_state(st["rng"])
        log("resumed at step %d/%d" % (step, NS))
    else:
        log("start top-up from %s: %d new + %d replay rows, %d steps x (%d new + %d replay), lr %g warmup %.0f%% cosine to %.2fx, "
            "r=%d alpha=%d dropout %g max_len %d" % (a.init_adapter, len(new), len(rep), NS, S["k_new"], S["k_rep"], a.lr,
                                                     100 * a.warmup, a.floor, ac["r"], ac["lora_alpha"], a.lora_dropout, a.max_len))
        json.dump({"new_rows": len(new), "replay_rows": len(rep), "steps": NS, "k_new": S["k_new"], "k_rep": S["k_rep"],
                   "tokens": sum(len(rows[k]["ids"]) for g in groups for k in g), "lr": a.lr},
                  open(os.path.join(a.out, "plan.json"), "w"), indent=1)

    def status(extra=None):
        d = {"step": step, "steps": NS, "done": step >= NS, "t": time.time()}
        d.update(extra or {})
        json.dump(d, open(os.path.join(a.out, "status.json"), "w"))

    def save(tag="latest", extra=None):
        d = os.path.join(a.out, "ckpt_" + tag)
        tmp = d + ".part"
        os.makedirs(tmp, exist_ok=True)
        model.save_pretrained(tmp, save_embedding_layers=False) if T.HEAD is not None else model.save_pretrained(tmp)
        if tag == "latest":
            torch.save({"opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": SC.state_dict() if SC.is_enabled() else {},
                        "step": step, "rng": torch.get_rng_state(), "dtype": str(DT), "world": 1}, os.path.join(tmp, "state.pt"))
        if os.path.exists(d):
            os.system("rm -rf '%s'" % d)
        os.rename(tmp, d)
        status(extra)

    def dev_eval():
        if not dvl:
            return
        model.eval()
        acc = [0.0, 0, 0.0, 0]
        with torch.no_grad():
            for d, l, n in T.dev_losses(model, dvl, a, dev):
                j = 0 if d["kind"] == "incident" else 2
                acc[j] += l
                acc[j + 1] += n
        model.train()
        r = {"step": step, "dev_incident": round(acc[0] / max(1, acc[1]), 4), "dev_chat": round(acc[2] / max(1, acc[3]), 4), "t": time.time()}
        log("DEV step %d incident %.4f chat %.4f" % (step, r["dev_incident"], r["dev_chat"]))
        with open(os.path.join(a.out, "dev.jsonl"), "a") as f:
            f.write(json.dumps(r) + "\n")

    G4 = (load_slice(a.gen_r4_inc, a.gen_r4_n, 21, True), load_slice(a.gen_r4_chat, a.gen_r4_n, 22, False))
    G3 = (load_slice(a.gen_inc, a.gen_n, 11, True), load_slice(a.gen_chat, a.gen_n, 12, False))
    has_gen = any(G4) or any(G3)
    bpath = os.path.join(a.out, "best.json")
    best = json.load(open(bpath)) if os.path.exists(bpath) else {"start": None, "top": [], "best": None, "since_best": 0, "evals": 0}

    def gen_eval():
        """returns True = early stop"""
        model.eval()
        model.config.use_cache = True
        if T.HEAD is not None:
            T.HEAD.unpark()
        rec = {"step": step, "t": time.time()}
        ir, cr = G4
        v = gen_score_r4_inc(model, tok, tools, ir, dev) if ir else [0.0] * 5
        c = T.gen_score(model, tok, dict(tools, chat=tools.get("chat_r5", tools["chat"])), [], cr, dev, a.gen_r3, a.gen_r3_tools)             if cr else torch.zeros(6)
        n = max(1.0, v[0])
        inc4 = (v[1] + v[2] + v[3] + v[4]) / (4 * n)
        ch4 = float(c[5]) / max(1.0, float(c[4]))
        parts = [x for x, k in ((inc4, v[0]), (ch4, float(c[4]))) if k > 0]
        rec["r4"] = {"n_inc": int(v[0]), "parse": round(v[1] / n, 3), "severity": round(v[2] / n, 3), "label": round(v[3] / n, 3),
                     "think_ok": round(v[4] / n, 3), "n_chat": int(c[4]), "chat_pass": round(ch4, 3),
                     "score": round(sum(parts) / max(1, len(parts)), 4)} if parts else None
        ir, cr = G3
        if ir or cr:
            w = T.gen_score(model, tok, tools, ir, cr, dev, a.gen_r3, a.gen_r3_tools)
            ni = max(1.0, float(w[0]))
            i3 = float(w[1] + w[2] + w[3]) / (3 * ni)
            c3 = float(w[5]) / max(1.0, float(w[4]))
            p3 = [x for x, k in ((i3, w[0]), (c3, w[4])) if k > 0]
            rec["r3"] = {"n_inc": int(w[0]), "parse": round(float(w[1]) / ni, 3), "severity": round(float(w[2]) / ni, 3),
                         "label": round(float(w[3]) / ni, 3), "n_chat": int(w[4]), "chat_pass": round(c3, 3),
                         "score": round(sum(p3) / max(1, len(p3)), 4)}
        model.config.use_cache = False
        if T.HEAD is not None:
            T.HEAD.park()
        model.train()
        s4 = (rec.get("r4") or {}).get("score")
        s3 = (rec.get("r3") or {}).get("score")
        if s4 is not None and s3 is not None:
            sc = a.w_r4 * s4 + (1 - a.w_r4) * s3
        else:
            sc = s4 if s4 is not None else s3
        rec["combined"] = None if sc is None else round(sc, 4)
        log("GEN step %d %s" % (step, json.dumps(rec)))
        with open(os.path.join(a.out, "gen_eval.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        if sc is None:
            return False
        if best["start"] is None:
            best["start"], best["start_r3"], best["start_r4"] = sc, s3, s4
            json.dump(best, open(bpath, "w"), indent=1)
            return False
        best["evals"] += 1
        ref3 = a.r3_ref if a.r3_ref >= 0 else best.get("start_r3")
        r3_ok = s3 is None or ref3 is None or s3 >= ref3 - a.r3_tol
        elig = sc > best["start"] and r3_ok
        rec_b = {"step": step, "combined": sc, "r3": s3, "r4": s4, "eligible": elig, "r3_ok": r3_ok}
        best.setdefault("history", []).append(rec_b)
        if elig and (best["best"] is None or sc > best["best"]):
            best["best"], best["since_best"] = sc, 0
        else:
            best["since_best"] += 1
        if elig:
            top = sorted(best["top"] + [[sc, step]], key=lambda x: (-x[0], -x[1]))
            keep, dropk = top[:a.keep_best], top[a.keep_best:]
            if [sc, step] in keep:
                save("best_%04d" % step)
            for _, s_ in dropk:
                os.system("rm -rf '%s'" % os.path.join(a.out, "ckpt_best_%04d" % s_))
            best["top"] = keep
        json.dump(best, open(bpath, "w"), indent=1)
        return best["since_best"] >= a.patience

    if step == 0 and best["start"] is None and has_gen:
        log("scoring the START adapter (step 0)")
        dev_eval()
        gen_eval()
    model.train()
    t0, tok_count, run_loss, run_n = time.time(), 0, 0.0, 0
    deadline = time.time() + a.hours * 3600
    while True:
        if best["since_best"] >= a.patience:
            log("EARLY STOP already reached (start %s, top %s)" % (best["start"], best["top"]))
            status({"stopped": "early_stop"})
            return 6
        if step >= NS:
            save()
            save("final")
            dev_eval()
            if has_gen and step % a.gen_every != 0:
                gen_eval()
            log("TRAINING DONE step %d (start %s, top %s)" % (step, best["start"], best["top"]))
            status({"stopped": "done", "done": True})
            return 0
        if time.time() > deadline or os.path.exists(os.path.join(a.out, "STOP")) or (a.max_steps and step >= a.max_steps):
            save()
            log("EXIT (hours limit / STOP / max-steps) at step %d" % step)
            return 3
        group = groups[step]
        mine = list(group)
        if a.step_log:
            ts, tc0 = time.time(), tok_count
        lsum = [0.0, 0, 0]
        retry = False
        tc_step = tok_count
        if a.shared_prefix:
            try:
                for (l, n), e in T.shared_prefix_step(model, [rows[k] for k in mine], a, dev, lambda t: SC.scale(t / a.accum).backward()):
                    lsum[0] += float(l) / max(1, n)
                    lsum[1] += n
                    tok_count += len(e["ids"])
                mine = []
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not T._is_oom(e):
                    raise
                retry = True
        if a.micro_tokens and not retry and mine:
            try:
                for mb in T.micro_batches([rows[k] for k in mine], a.micro_tokens):
                    res = T.loss_fn_batch(model, [e["ids"] for e in mb], [e["labels"] for e in mb], dev)
                    SC.scale(sum(l / max(1, n) for l, n in res) / a.accum).backward()
                    for (l, n), e in zip(res, mb):
                        lsum[0] += float(l) / max(1, n)
                        lsum[1] += n
                        tok_count += len(e["ids"])
                mine = []
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not T._is_oom(e):
                    raise
                retry = True
        if retry:                              # never drop rows: the step's rows again, one per forward (as train_rsn3 --oom-stop)
            opt.zero_grad(set_to_none=True)
            if not CPU:
                torch.cuda.empty_cache()
            lsum, tok_count, mine = [0.0, 0, 0], tc_step, list(group)
            log("OOM in a batch at step %d: retrying its %d rows one per forward" % (step, len(mine)))
        for k in mine:
            ex = rows[k]
            try:
                l, n = T.loss_fn(model, ex["ids"], ex["labels"], dev)
                SC.scale(l / max(1, n) / a.accum).backward()
                lsum[0] += float(l) / max(1, n)
                lsum[1] += n
                tok_count += len(ex["ids"])
            except (torch.OutOfMemoryError, RuntimeError) as e:
                if not T._is_oom(e):
                    raise
                lsum[2] += 1
                opt.zero_grad(set_to_none=True)
                if not CPU:
                    torch.cuda.empty_cache()
                log("OOM on %s (%d tokens) at step %d on the per-row path" % (k, len(ex["ids"]), step))
                break
        if lsum[2] and a.oom_stop:
            opt.zero_grad(set_to_none=True)
            save()
            log("OOM STOP at step %d: a row does not fit even one per forward; nothing skipped, ckpt_latest saved; exit 7" % step)
            return 7
        if lsum[2]:
            opt.zero_grad(set_to_none=True)
            step += 1
            continue
        SC.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        SC.step(opt)
        SC.update()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        run_loss += lsum[0] / len(group)
        run_n += 1
        if a.step_log:
            with open(os.path.join(a.out, "steps.jsonl"), "a") as f:
                f.write(json.dumps({"step": step, "loss": lsum[0] / len(group), "row_tokens": tok_count - tc0,
                                    "s": round(time.time() - ts, 2), "t": time.time()}) + "\n")
        if step % 5 == 0:
            el = time.time() - t0
            eta = el / run_n * (NS - step)
            log("step %d/%d loss %.4f lr %.2e %.0f tok/s ETA %.1f h" % (step, NS, run_loss / run_n, sched.get_last_lr()[0],
                                                                       tok_count / el, eta / 3600))
            with open(os.path.join(a.out, "losses.jsonl"), "a") as f:
                f.write(json.dumps({"step": step, "loss": run_loss / run_n, "lr": sched.get_last_lr()[0], "tok_s": tok_count / el,
                                    "t": time.time()}) + "\n")
            run_loss, run_n, t0, tok_count = 0.0, 0, time.time(), 0
        if step % a.save_every == 0:
            save()
            log("checkpoint step %d" % step)
        if a.eval_every and step % a.eval_every == 0 and step < NS:
            dev_eval()
        if has_gen and step % a.gen_every == 0 and step <= NS:
            if gen_eval():
                save(extra={"stopped": "early_stop", "best": best})
                log("EARLY STOP at step %d: combined score not better for %d evals (start %s, top %s)" % (
                    step, a.patience, best["start"], best["top"]))
                return 6


if __name__ == "__main__":
    sys.exit(main())
