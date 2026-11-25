# kernel_big.py: Kaggle side of the reasoner big top-up (proofs/2026-11-20_rsn_big). Pushed by launch_big.sh as a private script kernel
# (GPU, Internet on) with these private datasets attached (owner exception 2026-11-20: private, deleted after the run):
#   rsn-big-data : big_data.bin (tar of trainer, data/final_big files, p2 adapter, dev slices) + BIG_DATA_OK (md5 of every file) + big_cfg.json (seq, nonce, budget, recipe)
#   rsn3-r3-data : (existing) the r3 gen-eval tool tree (stores, tools_r3_impl, gen slices) = "R3_DATA_OK" tree
#   rsn-big-base : the edited base r3_edit_C1 (safetensors + json) + SHA256SUMS_base
#   rsn-big-run  : lineage.bin (+ .md5) of the previous session (absent in session 1) + causal_conv1d wheel
# Trains rsn_ft_train.py (continue the p2 LoRA, r32/a64, fp16 on T4, single GPU, the laptop's 6 GB fit levers) until the session budget, then packs
# /kaggle/working/lineage.bin (+ md5, KAGGLE_RESULT.json, best/ckpt_best_*). Resume = next session attaches the new rsn-big-run. Never reads a token.
import glob, hashlib, json, os, shutil, subprocess, sys, tarfile, time  # noqa: E401

T0 = time.time()
EXPECT_SEQ = int("@@SEQ@@")
EXPECT_NONCE = "@@NONCE@@"
W = "/kaggle/working"; OUT = W + "/run"; R3 = "/tmp/r3"; BIG = "/tmp/big"; PACK_H = 0.3
LOG = W + "/big_kaggle.log"
RESULT = {"seq": EXPECT_SEQ, "ok": False}


def log(m):
    line = "[%s +%.2fh] %s" % (time.strftime("%H:%M:%S"), (time.time() - T0) / 3600, m)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sh(c, check=True):
    log("$ " + c)
    r = subprocess.run(c, shell=True)
    if r.returncode and check:
        finish("command failed (%d): %s" % (r.returncode, c))
    return r.returncode


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def write_result(**kw):
    RESULT.update(kw, session_h=round((time.time() - T0) / 3600, 3), t=time.time())
    json.dump(RESULT, open(W + "/KAGGLE_RESULT.json", "w"), indent=1)


def finish(abort):
    log("ABORT: " + abort)
    write_result(abort=abort)
    sys.exit(0)


os.makedirs(W, exist_ok=True)
log("rsn big kernel seq %d" % EXPECT_SEQ)
sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv", check=False)

# ---- 1. config of THIS session (a stale dataset version would fork the lineage)
cf = glob.glob("/kaggle/input/**/big_cfg.json", recursive=True)
if not cf:
    finish("rsn-big-data not attached")
CFG = json.load(open(cf[0]))
if CFG["seq"] != EXPECT_SEQ or CFG.get("nonce") != EXPECT_NONCE:
    finish("stale rsn-big-data: seq %s/%s, kernel expects %d/%s" % (CFG["seq"], CFG.get("nonce"), EXPECT_SEQ, EXPECT_NONCE))
BUDGET_H = float(CFG["budget_h"])

# ---- 2. data tree + trainer (md5 of every file), r3 gen-eval tool tree
bt = glob.glob("/kaggle/input/**/big_data.bin", recursive=True)
if not bt:
    finish("rsn-big-data not attached (big_data.bin)")
if not os.path.exists(BIG + "/BIG_DATA_OK"):
    os.makedirs(BIG, exist_ok=True)
    with tarfile.open(bt[0]) as t:          # .bin: Kaggle auto-extracts .tar uploads (lesson 2026-11-13)
        t.extractall(BIG)
if sh("cd %s && md5sum -c --quiet BIG_DATA_OK" % BIG, check=False):
    finish("big data md5 check failed")
if hashlib.md5(open(BIG + "/BIG_DATA_OK", "rb").read()).hexdigest() != CFG["data_id"]:
    finish("data id differs from big_cfg.json")
mk = glob.glob("/kaggle/input/**/tree/R3_DATA_OK", recursive=True)       # Kaggle extracted r3_data.tar: .../r3_data/tree/{proofs,base,R3_DATA_OK}
mt = glob.glob("/kaggle/input/**/r3_data.tar", recursive=True)
if not mk and not mt:
    finish("rsn3-r3-data (tool tree) not attached")
if not os.path.exists(R3):
    if mk:
        shutil.copytree(os.path.dirname(mk[0]), R3, ignore=shutil.ignore_patterns("chat_train_r3.jsonl", "incidents_train.jsonl", "dev_r3.jsonl"))
    else:
        with tarfile.open(mt[0]) as t:
            t.extractall("/tmp/r3x")
        shutil.copytree("/tmp/r3x/tree", R3)
KGD = R3 + "/proofs/2026-10-29_rsn_v3/kaggle"; FTD = R3 + "/proofs/2026-11-13_v3_train/rsn_ft"
os.makedirs(KGD, exist_ok=True); os.makedirs(FTD, exist_ok=True)
shutil.copy(BIG + "/trainer/train_rsn3.py", KGD); shutil.copy(BIG + "/trainer/rsn_ft_train.py", FTD)
for k, v in (("train_rsn3.py", CFG["train_rsn3_md5"]), ("rsn_ft_train.py", CFG["rsn_ft_md5"])):
    if md5((KGD if k == "train_rsn3.py" else FTD) + "/" + k) != v:
        finish("trainer %s differs from the laptop's" % k)

# ---- 3. lineage of the previous session
RUN = glob.glob("/kaggle/input/**/lineage.bin", recursive=True)
if CFG["seq"] > 1:
    if not RUN or not os.path.exists(RUN[0] + ".md5") or open(RUN[0] + ".md5").read().split()[0] != md5(RUN[0]):
        finish("lineage.tar missing or md5 mismatch (seq %d needs the previous session's run dataset)" % EXPECT_SEQ)
    os.makedirs(OUT, exist_ok=True)
    with tarfile.open(RUN[0]) as t:
        t.extractall(OUT)
    if sh("cd %s && md5sum -c --quiet MD5SUMS" % OUT, check=False):
        finish("lineage file md5 check failed")
    os.remove(OUT + "/MD5SUMS")
    st0 = json.load(open(OUT + "/status.json")).get("step", 0)
    if st0 != CFG["step"]:
        finish("lineage step %s != expected %s" % (st0, CFG["step"]))
    if json.load(open(OUT + "/status.json")).get("done"):
        finish("the run is already done")
else:
    os.makedirs(OUT, exist_ok=True)
RESULT.update(step_from=CFG["step"], budget_h=BUDGET_H)

# ---- 4. packages (pinned = the laptop venv) + causal_conv1d
sh("pip uninstall -y -q torchvision torchaudio", check=False)
sh("pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2 safetensors==0.8.0 tokenizers==0.23.3 sentencepiece==0.2.2 huggingface_hub==2.3.0")
sh("pip install -q --no-deps flash-linear-attention==0.6.0 fla-core==0.6.0", check=False)
os.makedirs(W + "/wheels", exist_ok=True)
whl = sorted(glob.glob("/kaggle/input/**/causal_conv1d-1.5.2*.whl", recursive=True))
if whl:
    shutil.copy(whl[-1], W + "/wheels/")
elif sh("MAX_JOBS=4 timeout 900 pip wheel -q --no-deps --no-build-isolation -w %s/wheels causal-conv1d==1.5.2" % W, check=False) == 0:
    whl = sorted(glob.glob(W + "/wheels/causal_conv1d-1.5.2*.whl"))
if whl and sh("pip install -q --no-deps " + whl[-1], check=False) == 0:
    chk = ("import torch,torch.nn.functional as F;from causal_conv1d import causal_conv1d_fn as f;torch.manual_seed(0);"
           "x=torch.randn(2,512,300,device='cuda',dtype=torch.float16);w=torch.randn(512,4,device='cuda',dtype=torch.float16);"
           "r=F.conv1d(x.float(),w.float().unsqueeze(1),padding=3,groups=512)[...,:300];r=r*torch.sigmoid(r);"
           "d=(f(x,w,None,activation='silu').float()-r).abs().max().item();print('causal_conv1d max diff',d);assert d<0.05")
    if sh("python -c \"%s\"" % chk, check=False) != 0:
        sh("pip uninstall -y -q causal-conv1d", check=False)
sh("python -c \"import torch,transformers,peft,bitsandbytes;print(torch.__version__,transformers.__version__,peft.__version__,bitsandbytes.__version__,torch.cuda.device_count())\"")

# ---- 5. base (the laptop's edited base, tensor sha256 checked once per session)
bs = glob.glob("/kaggle/input/**/SHA256SUMS_base", recursive=True)
if not bs:
    finish("rsn-big-base not attached")
BASE = os.path.dirname(bs[0])
if sh("cd %s && sha256sum -c --quiet SHA256SUMS_base" % BASE, check=False):
    finish("base sha256 mismatch")

# ---- 6. train (single GPU: rsn_ft_train.py asserts WORLD == 1)
os.environ.update(TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", RSN3_SEG_TOKENIZE="1", MALLOC_ARENA_MAX="2",
                  TORCHINDUCTOR_COMPILE_THREADS="1", RSN3_GEN_TOK_BUDGET="24000", RSN3_KG=KGD, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
D = BIG + "/data"; F = R3 + "/proofs/2026-11-06_4b_local/data/final"
ARGS = ("%s/rsn_ft_train.py --base %s --init-adapter %s/p2 --tools %s/tools_v4.json --new %s/train_new.jsonl --replay %s/replay.jsonl --out %s --max-len 7424 "
        "--quant nf4 --dtype fp16 --gen-v4-inc %s/dev_hole_inc.jsonl --gen-v4-chat %s/dev_gen_chat.jsonl --gen-inc %s/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl "
        "--gen-chat %s/gen_chat_r3.jsonl --gen-r3-tools %s/proofs/2026-11-06_4b_local/tools %s") % (
    FTD, BASE, BIG, D, D, D, OUT, D, D, R3, F, R3, (CFG["flags"] if isinstance(CFG["flags"], str) else " ".join(CFG["flags"])))
h = BUDGET_H - (time.time() - T0) / 3600 - PACK_H
rc = None
if h > 0.5:
    rc = sh("CUDA_VISIBLE_DEVICES=0 python " + ARGS + " --hours %.2f" % h, check=False)
else:
    log("no time left to train after setup")
tail = open(OUT + "/train.log").read().splitlines()[-3:] if os.path.exists(OUT + "/train.log") else []
log("trainer rc %s; train.log tail: %s" % (rc, " | ".join(t[:160] for t in tail)))

# ---- 7. pack the lineage (token caches stay here) + the best adapters as plain files
keep = [p for p in ("ckpt_latest", "best.json", "status.json", "schedule.json", "plan.json", "losses.jsonl", "gen_eval.jsonl", "train.log") if os.path.exists(OUT + "/" + p)]
keep += [os.path.basename(p) for p in glob.glob(OUT + "/ckpt_best_*")]
files = []
for k in keep:
    p = OUT + "/" + k
    files += [os.path.relpath(os.path.join(a, f), OUT) for a, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else [k]
with open(OUT + "/MD5SUMS", "w") as f:
    for r in sorted(files):
        f.write("%s  %s\n" % (md5(OUT + "/" + r), r))
with tarfile.open(W + "/lineage.bin", "w") as t:
    for r in sorted(files) + ["MD5SUMS"]:
        t.add(OUT + "/" + r, arcname=r)
open(W + "/lineage.bin.md5", "w").write("%s  lineage.bin\n" % md5(W + "/lineage.bin"))
os.makedirs(W + "/best", exist_ok=True)
for b in glob.glob(OUT + "/ckpt_best_*"):
    shutil.copytree(b, W + "/best/" + os.path.basename(b), dirs_exist_ok=True)
for p in ("best.json", "gen_eval.jsonl", "train.log", "losses.jsonl", "status.json"):
    if os.path.exists(OUT + "/" + p):
        shutil.copy(OUT + "/" + p, W + "/best/")
st = json.load(open(OUT + "/status.json")) if os.path.exists(OUT + "/status.json") else {}
write_result(ok=True, rc=rc, step_to=st.get("step"), done=bool(st.get("done")), stopped=st.get("stopped"))
log("done: rc %s step %s" % (rc, st.get("step")))
shutil.rmtree(OUT, ignore_errors=True)       # token caches / raw run dir are not kept in the output (lineage.tar has what matters)
