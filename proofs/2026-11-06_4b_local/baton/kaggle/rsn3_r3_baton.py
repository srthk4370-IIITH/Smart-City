# rsn3_r3_baton.py: Kaggle side of the laptop <-> Kaggle baton for the ONE Qwen3.5-4B QLoRA r3 run (BATON.md).
# Pushed by to_kaggle.sh as a private script kernel (GPU T4 x2, Internet on) with two private datasets attached:
#   rsn3-r3-data  : r3_data.tar (r3 rows + gen-eval tool tree, repo layout) + R3_DATA_OK (md5 of every file)
#   rsn3-r3-baton : lineage.tar (ckpt_latest + best-K + schedule.json + best.json + logs, MD5SUMS inside) + LINEAGE.json +
#                   baton_cfg.json (seq, budget, recipe, md5s) + train_rsn3.py + baton_util.py [+ causal_conv1d wheel]
# Resumes the lineage exactly where the laptop stopped (same trainer file, data, max_len, accum = 16 rows per optimizer step on
# 1 or 2 GPUs), trains until the session budget, then writes /kaggle/working/lineage.tar (+ .md5, LINEAGE.json,
# KAGGLE_RESULT.json). The laptop pulls it with from_kaggle.sh. Nothing here ever reads a token or contacts the board.
import glob, hashlib, json, os, shutil, subprocess, sys, tarfile, time  # noqa: E401

T0 = time.time()
EXPECT_SEQ = int("@@SEQ@@")            # filled in by to_kaggle.sh: the baton dataset version this kernel must see
EXPECT_NONCE = "@@NONCE@@"             # ... and that upload's nonce (a re-upload of the same seq after a failed push differs)
W = "/kaggle/working"; OUT = W + "/run"; R3 = "/tmp/r3"; BASE = "/tmp/base"; PACK_H = 0.35
LOG = W + "/baton_kaggle.log"
RESULT = {"seq": EXPECT_SEQ, "ok": False}


def log(m):
    line = "[%s +%.2fh] %s" % (time.strftime("%H:%M:%S"), (time.time() - T0) / 3600, m)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sh(c, check=True, env=None):
    log("$ " + c)
    r = subprocess.run(c, shell=True, env=env)
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
    """stop without training further: the attached lineage is NOT repacked, so the laptop keeps its own copy"""
    log("ABORT: " + abort)
    shutil.rmtree(OUT, ignore_errors=True)    # only called before training starts: nothing new to keep
    write_result(abort=abort)
    sys.exit(0)        # status COMPLETE: from_kaggle.sh reads KAGGLE_RESULT.json


os.makedirs(W, exist_ok=True)
log("baton kernel seq %d" % EXPECT_SEQ)
sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv", check=False)

# ---- 1. inputs: the baton of THIS handover (a stale dataset version would fork the lineage)
cf = glob.glob("/kaggle/input/**/baton_cfg.json", recursive=True)
if not cf:
    finish("baton dataset not attached")
BD = os.path.dirname(cf[0])
CFG = json.load(open(cf[0]))
if CFG["seq"] != EXPECT_SEQ or CFG.get("nonce") != EXPECT_NONCE:
    finish("stale baton: dataset seq %s/%s, kernel expects %d/%s (dataset version not processed yet)" % (CFG["seq"], CFG.get("nonce"), EXPECT_SEQ, EXPECT_NONCE))
BUDGET_H = float(CFG["budget_h"])
RESULT.update(step_from=CFG["step"], budget_h=BUDGET_H)

# ---- 2. data: r3 rows + tool tree, md5-checked file by file
mk = glob.glob("/kaggle/input/**/R3_DATA_OK", recursive=True)
if not mk:
    finish("data dataset not attached")
DD = os.path.dirname(mk[0])
if not os.path.exists(R3 + "/R3_DATA_OK"):
    if os.path.exists(DD + "/r3_data.tar"):
        with tarfile.open(DD + "/r3_data.tar") as t:
            t.extractall(R3)
    else:                                   # Kaggle extracted the archive itself
        src = glob.glob("/kaggle/input/**/tree/R3_DATA_OK", recursive=True)
        if not src:
            finish("r3_data.tar missing in the data dataset")
        shutil.copytree(os.path.dirname(src[0]), R3)
data_id = hashlib.md5(open(R3 + "/R3_DATA_OK", "rb").read()).hexdigest()
if data_id != CFG["data_id"]:
    finish("data dataset %s != expected %s (re-run to_kaggle.sh: it re-versions the data)" % (data_id, CFG["data_id"]))
if sh("cd %s && md5sum -c --quiet R3_DATA_OK" % R3, check=False):
    finish("r3 data md5 check failed")
P = R3 + "/proofs"; F = P + "/2026-11-06_4b_local/data/final"; KGD = P + "/2026-10-29_rsn_v3/kaggle"
TRAINER = KGD + "/train_rsn3.py"; UTIL = W + "/baton_util.py"
shutil.copy(BD + "/train_rsn3.py", TRAINER)
shutil.copy(BD + "/baton_util.py", UTIL)
if md5(TRAINER) != CFG["trainer_md5"]:
    finish("trainer md5 differs from the laptop's")

# ---- 3. lineage -> OUT: tar md5, every file md5, scaler sidecar, step == baton step (baton_util.py kunpack)
r = subprocess.run("python %s kunpack %s %s %d %s" % (UTIL, BD, OUT, EXPECT_SEQ, EXPECT_NONCE), shell=True, capture_output=True, text=True)
log(r.stdout.strip() + r.stderr.strip()[-500:])
if r.returncode:
    finish(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "kunpack failed: " + r.stderr.strip()[-300:])

# ---- 4. packages (pinned = the laptop venv ~/venvs/rsn, as the 2026-10-29 Kaggle runs) + causal_conv1d CUDA kernel
sh("pip uninstall -y -q torchvision torchaudio", check=False)
sh("pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2 safetensors==0.8.0 "
   "tokenizers==0.23.3 sentencepiece==0.2.2 huggingface_hub==2.3.0")
sh("pip install -q --no-deps flash-linear-attention==0.6.0 fla-core==0.6.0", check=False)
os.makedirs(W + "/wheels", exist_ok=True)
T_PKG = time.time()
if CFG.get("pin_torch"):
    # optional (baton.conf KAGGLE_PIN_TORCH=1): the laptop's torch 2.6.0+cu124 instead of the image's (seq 1: 2.11.0+cu130, whose
    # CUDA 13 does not match the image's nvcc, so causal_conv1d could not be built)
    sh("pip install -q torch==2.6.0 triton==3.2.0 --index-url https://download.pytorch.org/whl/cu124", check=False)
TV = subprocess.run("python -c \"import torch,sys;print('torch%s-py%d%d' % (torch.__version__.split('+')[0] + torch.version.cuda.replace('.', ''), *sys.version_info[:2]))\"",
                    shell=True, capture_output=True, text=True).stdout.strip()
sh("nvcc --version | tail -2; echo torch tag " + TV, check=False)
tagged = sorted(glob.glob(BD + "/%s__causal_conv1d-1.5.2*.whl" % TV))     # wheels are cached under a torch/python tag
whl = []
if tagged:
    whl = [W + "/wheels/" + os.path.basename(tagged[-1])]
    shutil.copy(tagged[-1], whl[0])
else:
    os.makedirs("/tmp/ccwhl", exist_ok=True)
    if sh("CAUSAL_CONV1D_FORCE_BUILD=TRUE TORCH_CUDA_ARCH_LIST=7.5 MAX_JOBS=4 timeout 1200 pip wheel --no-deps --no-build-isolation "
          "-w /tmp/ccwhl causal-conv1d==1.5.2 > %s/causal_conv1d_build.log 2>&1" % W, check=False) == 0:
        b = sorted(glob.glob("/tmp/ccwhl/causal_conv1d-1.5.2*.whl"))
        if b:
            whl = [W + "/wheels/%s__%s" % (TV, os.path.basename(b[-1]))]
            shutil.copy(b[-1], whl[0])
    else:
        log("causal_conv1d build failed: tail of %s/causal_conv1d_build.log: %s" % (W, open(W + "/causal_conv1d_build.log").read()[-600:].replace(chr(10), " | ")))
if whl:
    inst = "/tmp/" + os.path.basename(whl[-1]).split("__")[-1]       # pip needs the original wheel file name
    shutil.copy(whl[-1], inst)
    whl = [inst]
if whl and sh("pip install -q --no-deps " + whl[-1], check=False) == 0:
    chk = ("import torch,torch.nn.functional as F;from causal_conv1d import causal_conv1d_fn as f;torch.manual_seed(0);"
           "x=torch.randn(2,512,300,device='cuda',dtype=torch.float16);w=torch.randn(512,4,device='cuda',dtype=torch.float16);"
           "r=F.conv1d(x.float(),w.float().unsqueeze(1),padding=3,groups=512)[...,:300];r=r*torch.sigmoid(r);"
           "d=(f(x,w,None,activation='silu').float()-r).abs().max().item();print('causal_conv1d max diff',d);assert d<0.05")
    if sh("python -c \"%s\"" % chk, check=False) != 0:
        sh("pip uninstall -y -q causal-conv1d", check=False)
sh("python -c \"import torch,transformers,peft,bitsandbytes;print(torch.__version__,transformers.__version__,peft.__version__,"
   "bitsandbytes.__version__,torch.cuda.device_count(),torch.cuda.get_device_capability(0))\"")
CC_OK = sh("python -c \"import causal_conv1d\"", check=False) == 0
RESULT.update(packages_s=round(time.time() - T_PKG), causal_conv1d=CC_OK, torch_tag=TV)
log("causal_conv1d kernel %s" % ("ACTIVE" if CC_OK else "MISSING (transformers falls back to the torch reference conv)"))

# Triton kernel cache (fla autotune/compile: seq 1 spent ~10 min on its first 4 steps): seeded from the previous session
os.makedirs("/tmp/triton_cache", exist_ok=True)
os.environ.update(TRITON_CACHE_DIR="/tmp/triton_cache", TRITON_CACHE_AUTOTUNING="1")
if os.path.exists(BD + "/triton_cache.tar"):
    with tarfile.open(BD + "/triton_cache.tar") as t:
        t.extractall("/tmp/triton_cache", filter="data")
    log("triton cache seeded (%d files)" % sum(len(f) for _, _, f in os.walk("/tmp/triton_cache")))

# ---- 5. base model (same weights as the laptop: its SHA256SUMS)
if not os.path.exists(BASE + "/OK"):
    sh("python -c \"from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3.5-4B', local_dir='%s')\"" % BASE)
    sh("cd %s && sha256sum -c --ignore-missing %s/base/SHA256SUMS" % (BASE, R3))
    open(BASE + "/OK", "w").close()

# ---- 6. data files + token caches: built by the trainer's own prep(); must equal the laptop's caches when it has some
INC, CHAT, DEV = F + "/incidents_train.jsonl", F + "/chat_train_r3.jsonl", F + "/dev_r3.jsonl"
TOOLS = F + "/tools_r3.json"
os.environ.update(TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", RSN3_SEG_TOKENIZE="1",
                  MALLOC_ARENA_MAX="2", TORCHINDUCTOR_COMPILE_THREADS="1",
                  RSN3_GEN_TOK_BUDGET="24000")   # gen-eval prefill budget: seq 1 ran its step-800 gen eval with it on T4 (15 GB); the
                                                  # laptop's 8400 is a 6 GB limit. Bigger risks a gen-eval OOM for ~1 % of a session
ML = int(json.load(open(OUT + "/maxlen.json"))["max_len"])
if ML != CFG["recipe"]["max_len"]:
    finish("max_len %d in the lineage != recipe %d" % (ML, CFG["recipe"]["max_len"]))
T_TOK = time.time()
tc = glob.glob("/kaggle/input/**/TOKCACHE_OK", recursive=True)
if tc and os.path.exists(OUT + "/tokfp.json"):
    for f in glob.glob(os.path.join(os.path.dirname(tc[0]), "*_seg_tok.pt")):
        os.symlink(f, os.path.join(OUT, os.path.basename(f)))        # read-only input; the trainer only reads (mmap/torch.load)
    if sh("python %s tokfp-check %s %s/tokfp.json" % (UTIL, OUT, OUT), check=False):
        log("cached token caches differ from the lineage's tokfp: rebuilding them")
        for f in glob.glob(OUT + "/*_tok.pt"):
            os.remove(f)
    else:
        log("token caches from the cache dataset (tokfp equal)")
sh("python %s tokprep %s %s %s %s %d %s %s %s" % (UTIL, TRAINER, BASE, TOOLS, OUT, ML, INC, CHAT, DEV))
RESULT.update(token_caches_s=round(time.time() - T_TOK))
if os.path.exists(OUT + "/tokfp.json"):
    if sh("python %s tokfp-check %s %s/tokfp.json" % (UTIL, OUT, OUT), check=False):
        finish("token caches differ from the laptop's (tokenizer/package drift): not training on a different encoding")
else:
    sh("python %s tokfp %s > %s/tokfp.json" % (UTIL, OUT, OUT))
if not CFG.get("fresh"):
    sh("python %s cursor %s %s %s" % (UTIL, OUT, INC, CHAT))

# ---- 7. train: the laptop's recipe; 16 rows per optimizer step whatever the GPU count (rows split by rank, one gradient all-reduce)
NGPU = int(subprocess.run("nvidia-smi -L | wc -l", shell=True, capture_output=True, text=True).stdout.strip() or 1)
G = R3 + "/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl"
ARGS = ("%s --base %s --tools %s --inc %s --chat %s --dev %s --out %s --max-len %d --accum %d --quant nf4 --dtype fp16 "
        "--gen-inc %s --gen-chat %s/gen_chat_r3.jsonl --gen-train-inc %s --gen-train-chat %s/gen_train_chat_r3.jsonl "
        "--gen-r3-tools %s/2026-11-06_4b_local/tools %s") % (
    TRAINER, BASE, TOOLS, INC, CHAT, DEV, OUT, ML, CFG["recipe"]["accum"], G, F, INC, F, P, " ".join(CFG["recipe"]["flags"]))


def step_now():
    r = subprocess.run("python %s step %s/ckpt_latest/state.pt" % (UTIL, OUT), shell=True, capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


def hours_left():
    return BUDGET_H - (time.time() - T0) / 3600 - PACK_H


fl = CFG["recipe"]["flags"]
EXTRA = []
if NGPU > 1 and "--shared-prefix" in fl and CFG.get("sp_rank_balance", True):
    EXTRA.append("--sp-rank-balance")
if "--mlp-chunk" in fl and "--mlp-chunk-min" not in fl:
    EXTRA += ["--mlp-chunk-min", str(CFG.get("lever_min_tokens", 4096))]
if "--ckpt-offload" in fl and "--offload-min" not in fl:
    EXTRA += ["--offload-min", str(CFG.get("lever_min_tokens", 4096))]
EXTRA.append("--oom-stop")     # zero skipped steps: an OOM retries the rows one per forward; a row that still OOMs stops (rc 7)
ARGS += " " + " ".join(EXTRA)
RESULT.update(extra_flags=EXTRA, setup_s=round(time.time() - T0))
log("Kaggle-only flags: %s; setup took %.1f min" % (EXTRA, (time.time() - T0) / 60))

def trainer_rc(rc):
    """torchrun reports any child exit != 0 as 1 (seq 1: the normal "hours limit" exit 3 came back as rc 1): recover the
    trainer's own exit code from the last lines it logged"""
    if rc != 1:
        return rc
    tail = open(OUT + "/train.log").read().splitlines()[-3:] if os.path.exists(OUT + "/train.log") else []
    for key, code in (("EXIT (hours limit", 3), ("STOP after epoch 1", 5), ("EARLY STOP", 6), ("TRAINING DONE", 0), ("WAIT_CHAT", 4),
                      ("OOM STOP", 7)):
        if any(key in t for t in tail):
            log("torchrun rc 1 = trainer rc %d (%s)" % (code, key))
            return code
    return rc


rc, ngpu = None, NGPU
s0 = step_now()
if hours_left() > 0.5:
    run = ("torchrun --standalone --nproc_per_node %d " % ngpu) if ngpu > 1 else "CUDA_VISIBLE_DEVICES=0 python "
    rc = trainer_rc(sh(run + ARGS + " --hours %.2f" % hours_left(), check=False))
    if rc not in (0, 3, 4, 5, 6, 7) and ngpu > 1 and step_now() == s0 and hours_left() > 0.5:
        log("multi-GPU run failed before any progress: one GPU")
        ngpu = 1
        rc = trainer_rc(sh("CUDA_VISIBLE_DEVICES=0 python " + ARGS + " --hours %.2f" % hours_left(), check=False))
else:
    log("no time left to train after setup")
if rc == 7:
    log("OOM STOP: a row did not fit even one per forward; nothing skipped, the lineage resumes at that step (laptop levers)")

try:
    n = sum(os.path.getsize(os.path.join(a_, f)) for a_, _, fs in os.walk("/tmp/triton_cache") for f in fs)
    if 0 < n < 400e6:
        with tarfile.open(W + "/triton_cache.tar", "w") as t:
            t.add("/tmp/triton_cache", arcname=".")
except Exception as e:      # a cache is never worth failing the pack
    log("triton cache not saved: %s" % e)

# ---- 8. pack the lineage for the laptop (token caches stay here: the laptop has / rebuilds its own, checked by tokfp)
gpu = subprocess.run("nvidia-smi --query-gpu=name --format=csv,noheader", shell=True, capture_output=True, text=True).stdout.strip().replace(chr(10), "+")
r = subprocess.run("python %s kpack %s %s %d %d %s %d '%s' %.2f" % (UTIL, OUT, W, EXPECT_SEQ, s0, rc, ngpu, gpu, (time.time() - T0) / 3600),
                   shell=True, capture_output=True, text=True)
log(r.stdout.strip() + r.stderr.strip()[-500:])
if r.returncode:
    write_result(ok=False, rc=rc, abort="pack failed (raw run/ dir left in the output)")
    sys.exit(0)
s1 = json.loads(r.stdout.strip().splitlines()[-1])["step_to"]
write_result(ok=True, rc=rc, step_to=s1, ngpu=ngpu, gpus=gpu)
log("done: rc %s, step %d -> %d" % (rc, s0, s1))
