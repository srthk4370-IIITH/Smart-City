# %% [markdown]
# # rsn_v3 on Kaggle: LoRA r32/a64 from the base Qwen3.5-4B (incident reports + chat with adaptive thinking)
# Inputs: dataset **rsn-v3-bundle** (bundle A: ~12k verified incident rows, scripts, tools) and, from session 2 on, dataset
# **rsn-v3-chat** (bundle B: verified distilled chat rows, made on the laptop). Without bundle B the run trains the incident
# part of epoch 1 and waits; when B is attached the remaining incident rows and the chat rows are mixed into the rest of epoch 1.
# Curriculum: epoch 1 = all rows; epoch 2 = weak/hard rows only, and only when RUN_E2 = True (only if the epoch-1 gate fails).
# Overtraining control: generation dev score every 200 steps, best-3 checkpoints, early stop (patience 3).
# Session 1 probes the fastest setup that fits (2 GPUs vs 1, flash-linear-attention on/off, 16-bit LoRA vs 4-bit QLoRA).
# Settings: Accelerator **GPU T4 x2**, Internet **On**. Run with **Save Version -> Save & Run All (Commit)**. Every session
# stops itself at 11.3 h; to continue, add this notebook's previous version output as an input and commit again.

# %%
import glob, json, math, os, shutil, subprocess, sys, time
T0 = time.time(); BUDGET_H = 11.3                     # everything saves and exits before Kaggle's 12 h session limit
RUN_E2 = False                                        # set True (and commit) only when the gate asks for epoch 2
CHAT_FRAC = 0.375; MAX_LEN = 6144
W = "/kaggle/working"; R3 = "/tmp/r3"; STATE = W + "/r3_state"; BASE = "/tmp/base"


def sh(c, check=True):
    print("$", c, flush=True)
    r = subprocess.run(c, shell=True)
    if r.returncode and check:
        raise SystemExit("FAILED (%d): %s" % (r.returncode, c))
    return r.returncode


def hours_left():
    return BUDGET_H - (time.time() - T0) / 3600


sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv")
NGPU = int(subprocess.run("nvidia-smi -L | wc -l", shell=True, capture_output=True, text=True).stdout.strip() or 1)

# %% pinned versions = the laptop venv ~/venvs/rsn (Python 3.12, torch 2.6.0+cu124) as in round 2, + flash-linear-attention 0.6.0
sh("pip uninstall -y -q torchvision torchaudio")  # keep Kaggle torch; torchvision breaks transformers import
sh("pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2 safetensors==0.8.0 "
   "tokenizers==0.23.3 sentencepiece==0.2.2 huggingface_hub==2.3.0")
sh("pip install -q --no-deps flash-linear-attention==0.6.0 fla-core==0.6.0", check=False)   # probed below; --no-fla switches it off
# session 1 log: "causal_conv1d_fn is falling back to its reference PyTorch implementation". Install the CUDA kernel (prebuilt
# wheel or a <= 15 min build); keep it only if it matches the reference on random inputs, else uninstall (training then as session 1)
# session 2 log: the build took 12 min, so the wheel goes to the output (wheels/) and later sessions install it from the attached
# previous output in seconds
whl = sorted(glob.glob("/kaggle/input/**/wheels/causal_conv1d-1.5.2*.whl", recursive=True))
os.makedirs("/kaggle/working/wheels", exist_ok=True)
if whl:
    shutil.copy(whl[-1], "/kaggle/working/wheels/")
elif sh("MAX_JOBS=4 timeout 900 pip wheel -q --no-deps --no-build-isolation -w /kaggle/working/wheels causal-conv1d==1.5.2", check=False) == 0:
    whl = sorted(glob.glob("/kaggle/working/wheels/causal_conv1d-1.5.2*.whl"))
print("causal_conv1d wheel:", whl[-1] if whl else "none (build failed)")
if whl and sh("pip install -q --no-deps " + whl[-1], check=False) == 0:
    chk = ("import torch,torch.nn.functional as F;from causal_conv1d import causal_conv1d_fn as f;torch.manual_seed(0);"
           "x=torch.randn(2,512,300,device='cuda',dtype=torch.float16);w=torch.randn(512,4,device='cuda',dtype=torch.float16);"
           "r=F.conv1d(x.float(),w.float().unsqueeze(1),padding=3,groups=512)[...,:300];r=r*torch.sigmoid(r);"
           "d=(f(x,w,None,activation='silu').float()-r).abs().max().item();print('causal_conv1d max diff',d);assert d<0.05")
    if sh("python -c \"%s\"" % chk, check=False) != 0:
        sh("pip uninstall -y -q causal-conv1d", check=False)
sh("python -c \"import torch,transformers,peft,bitsandbytes;print(torch.__version__,transformers.__version__,peft.__version__,"
   "bitsandbytes.__version__,torch.cuda.device_count(),torch.cuda.get_device_capability(0))\"")

# %% bundle A (required) and bundle B (optional) under /kaggle/input; copy A somewhere writable
mk = glob.glob("/kaggle/input/**/BUNDLE_OK_RSN3", recursive=True)
assert mk, "bundle A not attached: Add Input -> Your Datasets -> rsn-v3-bundle"
if not os.path.exists(R3):
    shutil.copytree(os.path.dirname(mk[0]), R3)
V3 = R3 + "/proofs/2026-10-29_rsn_v3"; KG = V3 + "/kaggle"; PIPE = V3 + "/pipeline"; D3 = V3 + "/data"; B3 = V3 + "/data3"
TOOLS = PIPE + "/tools_v4.json"
print(open(R3 + "/BUNDLE_OK_RSN3").read().split("\n")[0])
mb = glob.glob("/kaggle/input/**/BUNDLE_OK_RSN3_CHAT", recursive=True)
CHAT_SRC = os.path.join(os.path.dirname(mb[0]), "chat3_distilled.jsonl") if mb else ""
REPLAY_SRC = os.path.join(os.path.dirname(mb[0]), "replay_train.jsonl") if mb else ""
REPLAY_SRC = REPLAY_SRC if REPLAY_SRC and os.path.exists(REPLAY_SRC) else ""
print("bundle B (chat rows):", open(mb[0]).read().split("\n")[0] if mb else "not attached (incident part of epoch 1 only)")
os.makedirs(STATE, exist_ok=True)

# %% resume: state of a previous version's output, if attached (probe choice, mixes, token caches, checkpoints)
prev = sorted(glob.glob("/kaggle/input/**/r3_state/progress.json", recursive=True), key=os.path.getmtime)
if prev and not os.path.exists(STATE + "/progress.json"):
    ps = os.path.dirname(prev[-1])
    print("resuming from", ps)
    shutil.copytree(ps, STATE, dirs_exist_ok=True)
PROG = json.load(open(STATE + "/progress.json")) if os.path.exists(STATE + "/progress.json") else {"sessions": 0}
PROG["sessions"] += 1


def save_prog():
    json.dump(PROG, open(STATE + "/progress.json", "w"), indent=1)


save_prog()
print("session", PROG["sessions"], {k: v for k, v in PROG.items() if k != "sessions"})

# %% base model from the HF hub, checked against the laptop copy's SHA256SUMS (same weights as rounds 1-2)
if not os.path.exists(BASE + "/OK"):
    sh("python -c \"from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3.5-4B', local_dir='%s')\"" % BASE)
    sh("cd %s && sha256sum -c --ignore-missing %s/base/SHA256SUMS" % (BASE, R3))
    open(BASE + "/OK", "w").close()

# %% mixes: dev slice (always); chat selection once bundle B is attached (CHAT_FRAC of all rows)
MX = STATE + "/mix"
INC = B3 + "/incidents3_train.jsonl"
EXPECT_CHAT = int(subprocess.run("cd %s && python build_mix3.py --inc %s --out-dir /tmp --target-only" % (KG, INC), shell=True,
                                 capture_output=True, text=True).stdout.strip())
sh("cd %s && python build_mix3.py --inc %s --inc-dev %s/incidents_dev60.jsonl --chat-dev %s/chat3_dev.jsonl --out-dir %s" % (KG, INC, B3, D3, MX))
if CHAT_SRC and not os.path.exists(MX + "/chat_mix3.jsonl"):
    sh("cd %s && python build_mix3.py --inc %s --chat %s --out-dir %s --chat-frac %s%s" % (KG, INC, CHAT_SRC, MX, CHAT_FRAC,
                                                                                    (" --replay " + REPLAY_SRC) if REPLAY_SRC else ""))
    PROG["chat_bundle"] = open(mb[0]).read().split("\n")[0]
    save_prog()
elif CHAT_SRC and PROG.get("chat_bundle") != open(mb[0]).read().split("\n")[0]:
    print("WARNING: a different bundle B is attached than the one already mixed in; the first one is kept")
CHAT = MX + "/chat_mix3.jsonl" if os.path.exists(MX + "/chat_mix3.jsonl") else ""

# %% session-1 probe: the fastest setup that fits (each candidate: 1 optimizer step of 16 rows incl. the 2 longest rows)
OUT = STATE + "/run3"
os.makedirs(OUT, exist_ok=True)
os.environ.update(TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
TR = ("%s/train_rsn3.py --base %s --tools %s --inc %s --dev %s/dev_mix3.jsonl --out %s --max-len %d --expect-chat %d%s"
      " --gen-inc %s/incidents_dev60.jsonl --gen-chat %s/chat3_dev.jsonl --gen-train-inc %s --gen-train-chat %s/chat3_train.jsonl") % (
    KG, BASE, TOOLS, INC, MX, OUT, MAX_LEN, EXPECT_CHAT, (" --chat " + CHAT) if CHAT else "", B3, D3, INC, D3)


def probe(cmd):
    n0 = sum(1 for _ in open(OUT + "/train.log")) if os.path.exists(OUT + "/train.log") else 0
    rc = sh(cmd, check=False)
    ls = open(OUT + "/train.log").read().split("\n")[n0:] if os.path.exists(OUT + "/train.log") else []
    res = [json.loads(l.split("PROBE_RESULT ", 1)[1]) for l in ls if "PROBE_RESULT " in l]
    r = res[-1] if (rc == 0 and res) else {"failed_rc": rc}
    r["fits"] = rc == 0 and bool(res) and r.get("oom_steps", 1) == 0 and r.get("loss", 99) == r.get("loss", 0) and r.get("loss", 99) < 3.0
    print("PROBE", cmd.split("train_rsn3.py")[0][-40:], r)
    return r


if "config" not in PROG and not os.path.exists(OUT + "/ckpt_latest/state.pt"):
    cands = []
    for quant in ("none", "nf4"):
        for fla in (True, False):
            flags = " --quant %s%s" % (quant, "" if fla else " --no-fla")
            r = probe("CUDA_VISIBLE_DEVICES=0 timeout 2400 python %s --probe-steps 1%s" % (TR, flags))
            r["flags"] = flags
            cands.append(r)
    ok = [c for c in cands if c["fits"]]
    assert ok, "no setup fits / numerics wrong: %s -- stop and report" % cands
    best = max(ok, key=lambda c: c["tok_s"])
    ng = 1
    if NGPU > 1:
        r2 = probe("timeout 2400 torchrun --standalone --nproc_per_node %d %s --probe-steps 2%s" % (NGPU, TR, best["flags"]))
        if r2["fits"] and r2["tok_s"] > 1.2 * best["tok_s"]:
            ng, best = NGPU, dict(r2, flags=best["flags"])
    PROG["config"] = {"flags": best["flags"], "ngpu": ng, "tok_s": best["tok_s"], "candidates": cands}
    save_prog()
CFG = PROG.get("config", {"flags": " --quant nf4", "ngpu": NGPU, "tok_s": 0})
if CFG.get("tok_s"):
    plan = json.load(open(OUT + "/plan.json")) if os.path.exists(OUT + "/plan.json") else {}
    e1 = plan.get("tokens_e1", 0) / CFG["tok_s"] / 3600; e2 = plan.get("tokens_e2", 0) / CFG["tok_s"] / 3600
    print("PROJECTION: setup%s on %d GPU(s), %.0f tok/s -> epoch 1 %.1f h, epoch 2 %.1f h (~%.1f + %.1f sessions of 10.5 h)" % (
        CFG["flags"], CFG["ngpu"], CFG["tok_s"], e1, e2, e1 / 10.5, e2 / 10.5))

# %% train (data-parallel when the probe chose it); exit codes: 0 done, 3 time, 4 waiting for bundle B, 5 epoch 1 done
RC_TXT = {0: "plan done", 3: "session time used up: commit again to resume", 4: "incident part of epoch 1 done: attach bundle B and commit again",
          5: "EPOCH 1 DONE: download rsn_v3_adapter_epoch1.zip (+ _best) and run the gate; set RUN_E2 = True only if the gate fails",
          6: "EARLY STOP: the dev generation score stopped improving; download rsn_v3_adapter_best.zip and run the gate"}
rc = None
if hours_left() > 0.7:
    h = hours_left() - 0.4
    run = ("torchrun --standalone --nproc_per_node %d " % CFG["ngpu"]) if CFG["ngpu"] > 1 else "CUDA_VISIBLE_DEVICES=0 python "
    cmd = run + TR + CFG["flags"] + (" --run-e2" if RUN_E2 else "")
    print("training budget this session: %.2f h" % h)
    rc = sh(cmd + " --hours %.2f" % h, check=False)
    if rc not in (0, 3, 4, 5, 6) and CFG["ngpu"] > 1 and not os.path.exists(OUT + "/ckpt_latest/state.pt"):
        print("multi-GPU run failed before its first checkpoint: one GPU from now on")
        CFG["ngpu"] = 1; PROG["config"] = CFG; save_prog()
        rc = sh("CUDA_VISIBLE_DEVICES=0 python " + TR + CFG["flags"] + (" --run-e2" if RUN_E2 else "") + " --hours %.2f" % (hours_left() - 0.4), check=False)
st = json.load(open(OUT + "/status.json")) if os.path.exists(OUT + "/status.json") else {}
PROG["last_rc"] = rc; PROG["status"] = st; save_prog()
print("train rc", rc, RC_TXT.get(rc, "ERROR: send train.log"), st)

# %% package: epoch-1 adapter (normal end), final (after epoch 2), else the latest checkpoint marked PARTIAL; logs in each zip
gpu = subprocess.run("nvidia-smi --query-gpu=name --format=csv,noheader", shell=True, capture_output=True, text=True).stdout.strip()


def pack(src, name):
    pk = W + "/" + name
    shutil.rmtree(pk, ignore_errors=True)
    os.makedirs(pk)
    for f in ["adapter_model.safetensors", "adapter_config.json"]:
        shutil.copy(os.path.join(src, f), pk)
    for f in [OUT + "/" + x for x in ["status.json", "train.log", "losses.jsonl", "dev.jsonl", "gen_eval.jsonl", "best.json", "plan.json",
                                   "schedule.json"]] + [
            MX + "/mix3.txt", STATE + "/progress.json"]:
        if os.path.exists(f):
            shutil.copy(f, pk)
    json.dump({"adapter": name, "source_ckpt": os.path.basename(src), "epoch1_done": bool(st.get("epoch1_done")), "done": bool(st.get("done")),
               "step": st.get("step"), "e1_steps": st.get("e1_steps"), "e2_steps": st.get("e2_steps"), "gpu": gpu, "config": CFG,
               "session_h": round((time.time() - T0) / 3600, 2), "r": 32, "alpha": 64, "max_len": MAX_LEN},
              open(pk + "/KAGGLE_MANIFEST.json", "w"), indent=1)
    shutil.make_archive(pk, "zip", pk)
    shutil.rmtree(pk)


made = []
if os.path.exists(OUT + "/ckpt_epoch1/adapter_model.safetensors"):
    pack(OUT + "/ckpt_epoch1", "rsn_v3_adapter_epoch1"); made.append("rsn_v3_adapter_epoch1.zip")
if os.path.exists(OUT + "/ckpt_final/adapter_model.safetensors"):
    pack(OUT + "/ckpt_final", "rsn_v3_adapter_final"); made.append("rsn_v3_adapter_final.zip")
bj = json.load(open(OUT + "/best.json")) if os.path.exists(OUT + "/best.json") else {}
if bj.get("top") and os.path.exists(OUT + "/ckpt_best_%04d/adapter_model.safetensors" % bj["top"][0][1]):
    pack(OUT + "/ckpt_best_%04d" % bj["top"][0][1], "rsn_v3_adapter_best"); made.append("rsn_v3_adapter_best.zip (step %d, dev score %.4f)" % (bj["top"][0][1], bj["top"][0][0]))
if not made and os.path.exists(OUT + "/ckpt_latest/adapter_model.safetensors"):
    pack(OUT + "/ckpt_latest", "rsn_v3_adapter_PARTIAL"); made.append("rsn_v3_adapter_PARTIAL.zip")
print(RC_TXT.get(rc, "see log"), "| outputs:", made, sorted(os.listdir(W)))
