"""baton_util.py: CPU-only helpers for moving ONE train_rsn3.py lineage between the laptop and Kaggle (BATON.md).
Never touches a GPU (CUDA_VISIBLE_DEVICES is cleared before torch is imported).
  step STATE                         print the optimizer step stored in ckpt_latest/state.pt
  info CKPT                          json: step, dtype, world, host, scaler?, adapter tensors/params/dtypes
  scaler-extract STATE SIDE          save the GradScaler state of an fp16 (Kaggle) checkpoint to SIDE (no-op for bf16)
  scaler-inject STATE SIDE           put SIDE's scaler state into a bf16 (laptop) state.pt whose scaler is empty
  tokfp RUNDIR                       json fingerprint of the token caches (*_tok.pt) in RUNDIR
  tokfp-check RUNDIR FP.json         exit 1 when a cache present on both sides differs
  tokprep TRAINER BASE TOOLS OUT MAXLEN INC CHAT DEV   build the trainer's token caches in OUT (same code path as training)
  cursor RUNDIR [DATA.jsonl ...]     data cursor check: step vs schedule.json, group sizes, scheduled ids exist in the data
  recipe RUN_ENV_EXTRA MAXLEN        json recipe for Kaggle from the laptop's EXTRA flags (fit flags / --model-dir dropped)
  kunpack BATON_DIR OUT SEQ [NONCE]         Kaggle side: check baton_cfg seq, lineage.tar md5, every file md5, scaler sidecar, step
  kpack OUT WORKING SEQ STEP_FROM RC NGPU GPUS SESSION_H   Kaggle side: lineage.tar (+.md5, LINEAGE.json) from OUT
  skipped RUNDIR                     json: optimizer steps skipped by OOM (train.log), their rows (schedule.json), retries
  loadtest CKPT CONFIG_DIR [OUTDIR]  laptop checkpoint -> Kaggle code path -> laptop code path (keys, shapes, optimizer,
                                     scheduler, scaler, RNG, step), on CPU with a meta-device model skeleton
"""
import hashlib
import json
import os
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch  # noqa: E402

FIT_FLAGS = {"--head-cpu": 0, "--lean-host": 0, "--model-dir": 1, "--step-log": 0}   # laptop only (--step-log = benchmark log only)
# memory levers that also run on Kaggle (2026-11-07): exact (FIT.md); without them baton seq 1 (T4 x2 fp16, --shared-prefix)
# OOMed in 102 of 468 steps. With them a step's working set is the laptop's (fits 4.95 GiB) + the GPU lm_head (1.2 GiB) + the
# fp16->fp32 attention upcast (< 0.3 GiB), far below a T4's 15 GiB.
KAGGLE_LEVERS = {"--ckpt-offload": 0, "--mlp-chunk": 1, "--mlp-chunk-min": 1, "--offload-min": 1}
MAPPED = {"--gen-r3-tools": 1, "--dtype": 1, "--quant": 1}          # set by the Kaggle side itself
VALUE_FLAGS = {"--r", "--alpha", "--lr", "--e2-peak", "--accum", "--save-every", "--keep-every", "--eval-every", "--gen-every",
               "--gen-n", "--gen-train-n", "--patience", "--keep-best", "--lora-dropout", "--wd", "--micro-tokens", "--gen-r3",
               "--expect-chat", "--shared-prefix-min", "--shared-prefix-cont"}
BOOL_FLAGS = {"--run-e2", "--no-fla", "--shared-prefix", "--oom-stop"}     # --shared-prefix: same loss/rows, computed faster (speed/EQUIV.md); keep on both sides


def load_state(p):
    return torch.load(p, weights_only=False, map_location="cpu")


def save_atomic(obj, p):
    torch.save(obj, p + ".part")
    os.replace(p + ".part", p)


def cmd_step(a):
    print(load_state(a[0])["step"])


def adapter_info(ck):
    from safetensors import safe_open
    out = {"tensors": 0, "params": 0, "dtypes": {}}
    with safe_open(os.path.join(ck, "adapter_model.safetensors"), "pt") as f:
        for k in f.keys():
            t = f.get_slice(k)
            n = 1
            for s in t.get_shape():
                n *= s
            out["tensors"] += 1
            out["params"] += n
            d = str(t.get_dtype())
            out["dtypes"][d] = out["dtypes"].get(d, 0) + 1
    return out


def cmd_info(a):
    ck = a[0]
    r = {"ckpt": os.path.basename(os.path.normpath(ck)), "adapter": adapter_info(ck)}
    sp = os.path.join(ck, "state.pt")
    if os.path.exists(sp):
        st = load_state(sp)
        r.update(step=st["step"], dtype=st.get("dtype"), world=st.get("world"), host=st.get("host"), scaler=bool(st.get("scaler")),
                 opt_states=len(st["opt"]["state"]), sched_last_epoch=st["sched"].get("last_epoch"))
    print(json.dumps(r))


def cmd_scaler_extract(a):
    st = load_state(a[0])
    if st.get("scaler"):
        save_atomic({"scaler": st["scaler"], "step": st["step"], "host": st.get("host")}, a[1])
        print("scaler saved (scale %s, step %d)" % (st["scaler"].get("scale"), st["step"]))
    else:
        print("no scaler state (bf16 checkpoint): sidecar unchanged")


def cmd_scaler_inject(a):
    st = load_state(a[0])
    if st.get("scaler"):
        print("state.pt already has a scaler state: unchanged")
        return
    if not os.path.exists(a[1]):
        print("no scaler sidecar: the fp16 run starts a fresh GradScaler (a few skipped steps while it calibrates)")
        return
    sd = torch.load(a[1], weights_only=False, map_location="cpu")
    st["scaler"] = sd["scaler"]
    save_atomic(st, a[0])
    print("scaler state from step %s injected (scale %s)" % (sd.get("step"), sd["scaler"].get("scale")))


def tokfp(run):
    r = {}
    for f in sorted(os.listdir(run)):
        if not f.endswith("_tok.pt"):
            continue
        data = torch.load(os.path.join(run, f), weights_only=False, map_location="cpu")
        h = hashlib.md5()
        for d in data:
            h.update(d["id"].encode())
            h.update(d["ids"].to(torch.int32).numpy().tobytes())
            lab = d["labels"]
            lab = torch.where(lab, d["ids"], -100) if lab.dtype == torch.bool else lab
            h.update(lab.to(torch.int32).numpy().tobytes())
        r[f] = {"rows": len(data), "md5": h.hexdigest()}
    return r


def cmd_tokfp(a):
    print(json.dumps(tokfp(a[0]), indent=1))


def cmd_tokfp_check(a):
    mine, ref = tokfp(a[0]), json.load(open(a[1]))
    both = sorted(set(mine) & set(ref))
    bad = [k for k in both if mine[k] != ref[k]]
    print(json.dumps({"compared": both, "only_here": sorted(set(mine) - set(ref)), "only_ref": sorted(set(ref) - set(mine)), "differ": bad}))
    sys.exit(1 if bad else 0)


def cmd_tokprep(a):
    trainer, base, tools_p, out, maxlen = a[:5]
    sys.path.insert(0, os.path.dirname(os.path.abspath(trainer)))
    import train_rsn3 as T
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(base)
    tools = json.load(open(tools_p, encoding="utf-8"))
    tools["none"] = None
    os.makedirs(out, exist_ok=True)
    for name, p in zip(("inc", "chat", "dev"), a[5:8]):
        if p:
            d, c = T.prep(tok, p, tools, int(maxlen), out, name)
            print(name, len(d), os.path.basename(c))


def cmd_cursor(a):
    run = a[0]
    st = load_state(os.path.join(run, "ckpt_latest", "state.pt"))
    S = json.load(open(os.path.join(run, "schedule.json")))
    step, G = st["step"], S["groups"] + S.get("e2", [])
    sizes = sorted(set(len(g) for g in S["groups"][:-1]))
    r = {"step": step, "schedule": S["state"], "e1_groups": len(S["groups"]), "e2_groups": len(S.get("e2", [])), "group_sizes": sizes,
         "next_group": G[step][:3] if step < len(G) else None}
    ok = step <= len(G) and len(sizes) <= 1
    if len(a) > 1:
        ids = set()
        for p in a[1:]:
            for line in open(p, encoding="utf-8"):
                ids.add(json.loads(line)["id"])
        miss = [k for g in G[step:] for k in g if k not in ids]
        r["missing_ids"] = len(miss)
        ok = ok and not miss
    bp = os.path.join(run, "best.json")
    if os.path.exists(bp):
        top = json.load(open(bp))["top"]
        r["best_top"] = top
        r["best_dirs_missing"] = [s for _, s in top if not os.path.exists(os.path.join(run, "ckpt_best_%04d" % s, "adapter_model.safetensors"))]
    r["ok"] = ok
    print(json.dumps(r))
    sys.exit(0 if ok else 1)


def cmd_recipe(a):
    toks, maxlen = a[0].split(), int(a[1])
    keep, dropped, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if t in FIT_FLAGS or t in MAPPED:
            n = FIT_FLAGS.get(t, MAPPED.get(t))
            dropped += toks[i:i + 1 + n]
            i += 1 + n
        elif t in KAGGLE_LEVERS:
            n = KAGGLE_LEVERS[t]
            keep += toks[i:i + 1 + n]
            i += 1 + n
        elif t in VALUE_FLAGS:
            keep += toks[i:i + 2]
            i += 2
        elif t in BOOL_FLAGS:
            keep.append(t)
            i += 1
        else:
            sys.exit("recipe: unknown trainer flag %r in the laptop flags: add it to baton_util.py before moving the run" % t)
    print(json.dumps({"max_len": maxlen, "accum": 16, "flags": keep, "dropped_laptop_only": dropped}))


def cmd_skipped(a):
    """steps whose optimizer update was skipped (OOM) in RUNDIR/train.log, their schedule rows, and shared-prefix retries"""
    import re
    run = a[0]
    S = json.load(open(os.path.join(run, "schedule.json")))
    G = S["groups"] + S.get("e2", [])
    steps, retries, kinds = [], 0, {}
    for line in open(os.path.join(run, "train.log"), errors="replace"):
        m = re.search(r"(OOM[^:]*?) at step (\d+)[^:]*: optimizer step skipped", line) or re.search(r"(OOM on \S+ \(\d+ tokens\)): optimizer step skipped", line)
        if m:
            k = re.sub(r"OOM on \S+", "OOM on a row", m.group(1))
            kinds[k] = kinds.get(k, 0) + 1
            if len(m.groups()) > 1:
                steps.append(int(m.group(2)))
        elif "retrying this rank's" in line:
            retries += 1
    steps = sorted(set(steps))
    print(json.dumps({"skipped_steps": steps, "n_steps": len(steps), "rows": [k for s in steps if s < len(G) for k in G[s]],
                      "n_rows": sum(len(G[s]) for s in steps if s < len(G)), "kinds": kinds, "shared_prefix_retries_rank0": retries}))


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def _md5_check(d):
    for line in open(os.path.join(d, "MD5SUMS")):
        m, f = line.rstrip(chr(10)).split("  ", 1)
        if _md5(os.path.join(d, f)) != m:
            return f
    return None


def cmd_kunpack(a):
    """exit 0 = OUT holds the lineage at the baton's step; exit 2 + message on stdout = abort (nothing trained)"""
    import shutil
    import tarfile
    bd, out, seq = a[0], a[1], int(a[2])
    cfg = json.load(open(os.path.join(bd, "baton_cfg.json")))
    def bad(m):
        print(m)
        sys.exit(2)
    if len(a) > 3 and cfg.get("nonce") != a[3]:
        bad("stale baton: dataset nonce %s, kernel expects %s (an older upload of seq %d is still served)" % (cfg.get("nonce"), a[3], seq))
    if cfg["seq"] != seq:
        bad("stale baton: dataset seq %s, kernel expects %d (dataset version not processed yet)" % (cfg["seq"], seq))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    if cfg.get("fresh"):
        json.dump({"max_len": cfg["recipe"]["max_len"], "probe": "baton fresh start on Kaggle"}, open(os.path.join(out, "maxlen.json"), "w"))
        print("fresh start")
        return
    tp = os.path.join(bd, "lineage.tar")
    if os.path.exists(tp):
        if _md5(tp) != cfg["lineage_tar_md5"]:
            bad("lineage.tar md5 mismatch")
        with tarfile.open(tp) as t:
            t.extractall(out, filter="data")
    else:                                   # Kaggle extracted the archive itself
        src = [root for root, dirs, fs in os.walk(bd) if "MD5SUMS" in fs and "ckpt_latest" in dirs]
        if not src:
            bad("lineage.tar missing in the baton dataset")
        shutil.copytree(src[0], out, dirs_exist_ok=True)
    f = _md5_check(out)
    if f:
        bad("lineage file md5 mismatch: %s" % f)
    os.remove(os.path.join(out, "MD5SUMS"))
    cmd_scaler_inject([os.path.join(out, "ckpt_latest", "state.pt"), os.path.join(out, "baton_scaler_kaggle.pt")])
    st = load_state(os.path.join(out, "ckpt_latest", "state.pt"))["step"]
    if st != cfg["step"]:
        bad("lineage step %d != baton step %d" % (st, cfg["step"]))
    print("lineage at step %d unpacked" % st)


def cmd_kpack(a):
    import shutil
    import tarfile
    import time
    out, w, seq, s0, rc, ngpu, gpus, sh_ = a[0], a[1], int(a[2]), int(a[3]), a[4], int(a[5]), a[6], float(a[7])
    sp = os.path.join(out, "ckpt_latest", "state.pt")
    s1 = load_state(sp)["step"] if os.path.exists(sp) else 0
    if os.path.exists(sp):
        cmd_scaler_extract([sp, os.path.join(out, "baton_scaler_kaggle.pt")])
    stp = os.path.join(out, "status.json")
    st = json.load(open(stp)) if os.path.exists(stp) else {}
    rc = int(rc) if rc not in ("", "None") else None
    with open(os.path.join(out, "BATON_HISTORY.jsonl"), "a") as f:
        f.write(json.dumps({"side": "kaggle", "seq": seq, "step_from": s0, "step_to": s1, "rc": rc, "gpus": gpus, "ngpu": ngpu,
                            "dtype": "fp16+GradScaler", "session_h": sh_, "t": time.time()}) + chr(10))
    for f in os.listdir(out):
        if f.endswith("_tok.pt") or f == "caches.json":
            os.remove(os.path.join(out, f))
    files = []
    for root, _, fs in os.walk(out):
        for f in fs:
            files.append(os.path.relpath(os.path.join(root, f), out))
    files = sorted(f for f in files if not f.endswith(".part") and ".part/" not in f and not f.startswith(("probe/", "STOP", "MD5SUMS")))
    with open(os.path.join(out, "MD5SUMS"), "w") as m:
        for f in files:
            m.write("%s  %s%s" % (_md5(os.path.join(out, f)), f, chr(10)))
    tp = os.path.join(w, "lineage.tar")
    with tarfile.open(tp + ".part", "w") as t:
        for f in files + ["MD5SUMS"]:
            t.add(os.path.join(out, f), arcname=f)
    os.replace(tp + ".part", tp)
    open(tp + ".md5", "w").write("%s  lineage.tar%s" % (_md5(tp), chr(10)))
    json.dump({"seq": seq, "holder": "kaggle", "step": s1, "step_from": s0, "rc": rc, "status": st, "files": len(files)},
              open(os.path.join(w, "LINEAGE.json"), "w"), indent=1)
    shutil.rmtree(out)                      # the tar holds everything; halves the output download
    print(json.dumps({"step_to": s1, "files": len(files), "tar_mb": round(os.path.getsize(tp) / 1e6, 1)}))


def peft_skeleton(cfg_dir, ck):
    """meta-device model + the same LoRA as the trainer (r/alpha/targets from adapter_config.json): no weights, no RAM"""
    from transformers import AutoConfig, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model
    ac = json.load(open(os.path.join(ck, "adapter_config.json")))
    cfg = AutoConfig.from_pretrained(cfg_dir)
    with torch.device("meta"):
        m = AutoModelForCausalLM.from_config(cfg)
    m = get_peft_model(m, LoraConfig(r=ac["r"], lora_alpha=ac["lora_alpha"], lora_dropout=ac.get("lora_dropout", 0.05),
                                     target_modules=sorted(ac["target_modules"]) if isinstance(ac["target_modules"], list) else ac["target_modules"],
                                     bias="none", task_type="CAUSAL_LM"))
    return m


def cmd_loadtest(a):
    """the resume block of train_rsn3.main() executed twice on CPU: as the Kaggle side (fp16 run: LoRA params fp32, GradScaler on)
    then as the laptop side (bf16 run: no scaler); every tensor must survive both hops bit-exactly"""
    import bitsandbytes as bnb
    from peft import get_peft_model_state_dict
    from safetensors.torch import load_file
    ck, cfg_dir = a[0], a[1]
    outd = a[2] if len(a) > 2 else None
    rep = {"ckpt": ck}
    m = peft_skeleton(cfg_dir, ck)
    exp = get_peft_model_state_dict(m)
    got = load_file(os.path.join(ck, "adapter_model.safetensors"))
    rep["adapter_keys"] = len(got)
    rep["keys_match"] = sorted(exp) == sorted(got)
    rep["shapes_match"] = rep["keys_match"] and all(tuple(exp[k].shape) == tuple(got[k].shape) for k in got)
    rep["adapter_dtypes"] = sorted(set(str(v.dtype) for v in got.values()))
    # trainer: params = [p for p in model.parameters() if p.requires_grad] (peft order); map them to the saved tensors
    names = [n for n, p in m.named_parameters() if p.requires_grad]
    def saved_key(n):
        return n.replace(".default.", ".")
    assert all(saved_key(n) in got for n in names), "trainable parameter without a saved tensor"
    st = load_state(os.path.join(ck, "state.pt"))
    rep["step"] = st["step"]
    rep["saved_dtype"] = st.get("dtype")

    def side(dt_name, state, scaler_on):
        params = [torch.nn.Parameter(got[saved_key(n)].clone().float()) for n in names]   # fp32 LoRA masters on both sides
        opt = bnb.optim.AdamW8bit(params, lr=1e-4, weight_decay=0.01, betas=(0.9, 0.999))
        sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 1.0)
        sc = torch.amp.GradScaler("cpu", enabled=scaler_on)
        opt.load_state_dict(state["opt"])
        sched.load_state_dict(state["sched"])
        if state.get("scaler") and sc.is_enabled():
            sc.load_state_dict(state["scaler"])
        if state.get("rng") is not None:
            torch.set_rng_state(state["rng"])
        rng = torch.get_rng_state()
        r = torch.rand(4)                                       # the first random draw after resume must be the same on both sides
        new = {"opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": sc.state_dict() if sc.is_enabled() else {},
               "step": state["step"], "rng": rng, "dtype": dt_name, "world": 2 if scaler_on else 1, "host": "loadtest"}
        return new, r, sched.last_epoch

    def same(x, y, path="opt"):
        if isinstance(x, torch.Tensor):
            return isinstance(y, torch.Tensor) and x.dtype == y.dtype and x.shape == y.shape and torch.equal(x, y)
        if isinstance(x, dict):
            return isinstance(y, dict) and set(x) == set(y) and all(same(x[k], y[k]) for k in x)
        if isinstance(x, (list, tuple)):
            return len(x) == len(y) and all(same(u, v) for u, v in zip(x, y))
        return x == y
    st_k, r1, le1 = side("torch.float16", st, True)            # laptop ckpt -> Kaggle code path
    st_k["scaler"] = st_k["scaler"] or {"scale": 4096.0, "growth_factor": 2.0, "backoff_factor": 0.5, "growth_interval": 2000, "_growth_tracker": 7}
    st_l, r2, le2 = side("torch.bfloat16", st_k, False)        # Kaggle ckpt -> laptop code path
    rep["opt_roundtrip_exact"] = same(st["opt"], st_k["opt"]) and same(st["opt"], st_l["opt"])
    rep["opt_param_states"] = len(st["opt"]["state"])
    def tensors(x):
        if isinstance(x, torch.Tensor):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from tensors(v)
    ts = list(tensors(st["opt"]["state"]))
    rep["opt_state_tensors"] = len(ts)
    rep["opt_state_dtypes"] = sorted(set(str(t.dtype) for t in ts))
    rep["sched_last_epoch"] = [st["sched"]["last_epoch"], le1, le2]
    rep["sched_ok"] = le1 == le2 == st["sched"]["last_epoch"] == st["step"]
    rep["rng_ok"] = torch.equal(r1, r2)
    rep["step_ok"] = st_k["step"] == st_l["step"] == st["step"]
    # scaler: a laptop (bf16) save drops it; the baton sidecar puts it back for the next Kaggle session
    sc_side = {"scaler": st_k["scaler"], "step": st_k["step"]}
    st_l2 = dict(st_l, scaler={})
    if not st_l2.get("scaler"):
        st_l2["scaler"] = sc_side["scaler"]
    sc = torch.amp.GradScaler("cpu", enabled=True)
    sc.load_state_dict(st_l2["scaler"])
    rep["scaler_carry_ok"] = sc.get_scale() == st_k["scaler"]["scale"]
    if outd:
        os.makedirs(outd, exist_ok=True)
        torch.save(st_k, os.path.join(outd, "state_as_kaggle.pt"))
    rep["ok"] = all(rep[k] for k in ("keys_match", "shapes_match", "opt_roundtrip_exact", "sched_ok", "rng_ok", "step_ok", "scaler_carry_ok"))
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    c, args = sys.argv[1], sys.argv[2:]
    {"step": cmd_step, "info": cmd_info, "scaler-extract": cmd_scaler_extract, "scaler-inject": cmd_scaler_inject, "tokfp": cmd_tokfp,
     "tokfp-check": cmd_tokfp_check, "tokprep": cmd_tokprep, "cursor": cmd_cursor, "recipe": cmd_recipe, "loadtest": cmd_loadtest,
     "kunpack": cmd_kunpack, "kpack": cmd_kpack, "skipped": cmd_skipped}[c](args)
