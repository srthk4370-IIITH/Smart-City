# agt3_kernel.py: Kaggle side of the agt_v3 training (V3_DESIGN.md §5.1). Pushed by push.sh as a PRIVATE script kernel
# (GPU T4 x2, Internet on) with private datasets attached:
#   agt3-data : agt3_data.tar (synthetic agt_v3 train + gen-dev rows, calib_stats.json (aggregates only), base TENSOR_SHA.json +
#               tokenizer files of the laptop's Llama-3.2-3B-Instruct) + DATA_OK (md5 of every file)
#   agt3-run  : agt3_cfg.json (seq, nonce, budget, recipe, md5s) + train_agt3.py + rows.py [+ lineage.tar(.md5)]
#   agt3-base : (only if BASE_SRC=dataset) the laptop base weights; otherwise the base comes from HF and must match the laptop's
#               tensors (TENSOR_SHA.json) bit for bit
# Resumes the lineage, trains until the session budget, packs /kaggle/working/lineage.tar (ckpt_latest + new snap_* + logs).
# Never reads a token, never contacts the board. Env overrides (offline dry run only): AGT3_INPUT AGT3_WORK AGT3_TMP AGT3_SKIP_PIP
# AGT3_BASE_DIR AGT3_TRAIN_FLAGS AGT3_LAUNCH.
import glob, hashlib, json, os, shutil, subprocess, sys, tarfile, time  # noqa: E401

T0 = time.time()
EXPECT_SEQ = int("@@SEQ@@")
EXPECT_NONCE = "@@NONCE@@"
INP = os.environ.get("AGT3_INPUT", "/kaggle/input")
W = os.environ.get("AGT3_WORK", "/kaggle/working")
TMP = os.environ.get("AGT3_TMP", "/tmp")
OUT = W + "/run"; DX = TMP + "/agt3x"; DATA = DX + "/data"; BASE = TMP + "/base"; PACK_H = 0.25
LOG = W + "/agt3_kaggle.log"
RESULT = {"seq": EXPECT_SEQ, "ok": False}
os.makedirs(W, exist_ok=True)


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
    """stop before training: nothing repacked, the laptop keeps its lineage"""
    log("ABORT: " + abort)
    shutil.rmtree(OUT, ignore_errors=True)
    write_result(abort=abort)
    sys.exit(0)


def find(name):
    g = sorted(glob.glob(INP + "/**/" + name, recursive=True))
    return g[0] if g else None


log("agt3 kernel seq %d" % EXPECT_SEQ)
sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv", check=False)

# ---- 1. this handover's run dataset (a stale version would fork the lineage)
cf = find("agt3_cfg.json")
if not cf:
    finish("run dataset not attached")
RD = os.path.dirname(cf)
CFG = json.load(open(cf))
if CFG["seq"] != EXPECT_SEQ or CFG.get("nonce") != EXPECT_NONCE:
    finish("stale run dataset: seq %s/%s, kernel expects %d/%s" % (CFG["seq"], CFG.get("nonce"), EXPECT_SEQ, EXPECT_NONCE))
BUDGET_H = float(CFG["budget_h"])
RESULT.update(step_from=CFG["step"], budget_h=BUDGET_H)

# ---- 2. data (md5 file by file; data id = md5 of DATA_OK)
mk = find("DATA_OK")
if not mk:
    finish("data dataset not attached")
DD = os.path.dirname(mk)
if not os.path.exists(DATA + "/DATA_OK"):
    os.makedirs(DX, exist_ok=True)
    if os.path.exists(DD + "/agt3_data.tar"):
        with tarfile.open(DD + "/agt3_data.tar") as t:             # archive members: data/...
            t.extractall(DX, filter="data")
    else:                                           # Kaggle unpacked the archive itself
        src = find("data/DATA_OK")
        if not src:
            finish("agt3_data.tar missing in the data dataset")
        shutil.copytree(os.path.dirname(src), DATA)
if md5(DATA + "/DATA_OK") != CFG["data_id"]:
    finish("data dataset %s != expected %s" % (md5(DATA + "/DATA_OK"), CFG["data_id"]))
if sh("cd %s && md5sum -c --quiet DATA_OK" % DATA, check=False):
    finish("data md5 check failed")
CODE = W + "/code"
os.makedirs(CODE, exist_ok=True)
for f in ("train_agt3.py", "rows.py"):
    shutil.copy(RD + "/" + f, CODE + "/" + f)
if md5(CODE + "/train_agt3.py") != CFG["trainer_md5"] or md5(CODE + "/rows.py") != CFG["rows_md5"]:
    finish("trainer/rows md5 differs from the laptop's")

# ---- 3. lineage (absent on the first session)
os.makedirs(OUT, exist_ok=True)
if not CFG.get("fresh"):
    lt = RD + "/lineage.bin"            # 2026-11-13: uploaded as .bin because Kaggle auto-extracts .tar in datasets
    if not os.path.isfile(lt):
        lt = RD + "/lineage.tar"
    if not os.path.isfile(lt):
        finish("lineage.bin/.tar missing in the run dataset (have: %s)" % sorted(os.listdir(RD))[:20])
    if md5(lt) != CFG["lineage_tar_md5"]:
        finish("lineage.tar md5 differs")
    with tarfile.open(lt) as t:
        t.extractall(OUT, filter="data")
    if sh("cd %s && md5sum -c --quiet MD5SUMS" % OUT, check=False):
        finish("lineage file md5 check failed")
    os.remove(OUT + "/MD5SUMS")
    st = json.load(open(OUT + "/status.json")) if os.path.exists(OUT + "/status.json") else {}
    if st.get("step") != CFG["step"]:
        finish("lineage step %s != handover step %s" % (st.get("step"), CFG["step"]))
before = set(os.listdir(OUT))

# ---- 4. packages: the laptop venv ~/venvs/rsn pins (proven on Kaggle T4 by the 4B baton, 2026-11-07)
T_PKG = time.time()
if not os.environ.get("AGT3_SKIP_PIP"):
    sh("pip uninstall -y -q torchvision torchaudio", check=False)
    sh("pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2 safetensors==0.8.0 "
       "tokenizers==0.23.3 huggingface_hub==2.3.0")
sh("python -c \"import torch,transformers,peft;print(torch.__version__,transformers.__version__,peft.__version__,"
   "torch.cuda.device_count())\"")
RESULT.update(packages_s=round(time.time() - T_PKG))

# ---- 5. base: laptop tensors bit for bit (HF mirror or the private base dataset), laptop tokenizer files
def tensor_sha(d):
    from safetensors import safe_open
    out = {}
    for f in sorted(glob.glob(d + "/*.safetensors")):
        with safe_open(f, "pt") as s:
            for k in s.keys():
                t = s.get_tensor(k)
                out[k] = [str(t.dtype), list(t.shape), hashlib.sha256(t.contiguous().view(-1).view(__import__("torch").uint8).numpy().tobytes()).hexdigest()]
    return out


T_BASE = time.time()
bdir = os.environ.get("AGT3_BASE_DIR")
if not bdir:
    bm = find("BASE_OK")                              # BASE_SRC=dataset
    if bm:
        bdir = os.path.dirname(bm)
    elif not os.path.exists(BASE + "/OK"):
        sh("python -c \"from huggingface_hub import snapshot_download as s; s('%s', local_dir='%s', allow_patterns=['*.safetensors','*.json'])\""
           % (CFG["base_hf"], BASE))
        bdir = BASE
    else:
        bdir = BASE
if not os.path.exists(BASE + "/OK") or bdir != BASE:
    want = json.load(open(DATA + "/base/TENSOR_SHA.json"))
    got = tensor_sha(bdir)
    if got != want:
        bad = [k for k in set(want) | set(got) if want.get(k) != got.get(k)][:5]
        finish("base mismatch: %d tensors differ from the laptop base (e.g. %s); set BASE_SRC=dataset" % (
            len([k for k in set(want) | set(got) if want.get(k) != got.get(k)]), bad))
    if bdir != BASE:
        os.makedirs(BASE, exist_ok=True)
        for f in glob.glob(bdir + "/*"):
            if not os.path.exists(BASE + "/" + os.path.basename(f)):
                os.symlink(f, BASE + "/" + os.path.basename(f))
    for f in glob.glob(DATA + "/base/*"):
        if not f.endswith("TENSOR_SHA.json"):
            if os.path.lexists(BASE + "/" + os.path.basename(f)):
                os.remove(BASE + "/" + os.path.basename(f))
            shutil.copy(f, BASE + "/")                 # laptop config + tokenizer files: same encoding as the laptop
    open(BASE + "/OK", "w").close()
RESULT.update(base_s=round(time.time() - T_BASE))

# ---- 6. train
NGPU = int(subprocess.run("nvidia-smi -L 2>/dev/null | wc -l", shell=True, capture_output=True, text=True).stdout.strip() or 0)
TR, DV = DATA + "/" + CFG["train_file"], DATA + "/" + CFG["dev_file"]
if md5(TR) != CFG["recipe"]["train_md5"]:
    finish("train file md5 != recipe")
R = CFG["recipe"]
ARGS = ("%s/train_agt3.py --base %s --train %s --dev %s --out %s --rank %d --alpha %d --dropout %s --lr %s --warmup %s "
        "--min-lr-ratio %s --rows-per-step %d --micro %d --max-len %d --epochs %s --seed %d --quant %s --save-every %d "
        "--snap-every %d --gen-n %d --max-new %d --patience %d --oom-stop %s") % (
    CODE, BASE, TR, DV, OUT, R["rank"], R["alpha"], R["dropout"], R["lr"], R["warmup"], R["min_lr_ratio"], R["rows_per_step"],
    R["micro"], R["max_len"], R["epochs"], R["seed"], R["quant"], CFG["save_every"], CFG["snap_every"], CFG["gen_n"],
    CFG["max_new"], CFG["patience"], os.environ.get("AGT3_TRAIN_FLAGS", "--dtype fp16 --optim adamw8bit"))
os.environ.update(TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")


def step_now():
    try:
        return int(json.load(open(OUT + "/status.json"))["step"])
    except Exception:  # noqa: BLE001
        return CFG["step"]


def hours_left():
    return BUDGET_H - (time.time() - T0) / 3600 - PACK_H


def trainer_rc(rc):
    """torchrun reports any child exit != 0 as 1: recover the trainer's code from its last log line"""
    if rc != 1:
        return rc
    tail = open(OUT + "/train.log").read().splitlines()[-3:] if os.path.exists(OUT + "/train.log") else []
    for key, code in (("EXIT (hours limit", 3), ("EARLY STOP", 6), ("TRAINING DONE", 0), ("OOM STOP", 7), ("STOP:", 2)):
        if any(key in t for t in tail):
            return code
    return rc


RESULT.update(setup_s=round(time.time() - T0), ngpu=NGPU)
log("setup %.1f min; %d GPU(s)" % ((time.time() - T0) / 60, NGPU))
rc, s0 = None, step_now()
launch = os.environ.get("AGT3_LAUNCH")
if hours_left() > 0.5:
    run = launch or (("torchrun --standalone --nproc_per_node %d " % NGPU) if NGPU > 1 else "python ")
    rc = trainer_rc(sh(run + ARGS + " --hours %.3f" % hours_left(), check=False))
    if rc not in (0, 2, 3, 6, 7) and NGPU > 1 and step_now() == s0 and hours_left() > 0.5 and not launch:
        log("multi-GPU run failed before any progress: one GPU")
        rc = trainer_rc(sh("CUDA_VISIBLE_DEVICES=0 python " + ARGS + " --hours %.3f" % hours_left(),
                           check=False))
else:
    log("no time left to train after setup")
if rc == 2:
    log("trainer refused its inputs (see train.log STOP line)")

# ---- 7. pack: ckpt_latest + the snapshots made this session + json/logs; MD5SUMS inside, .md5 next to it
s1 = step_now()
keep = ["ckpt_latest"] + sorted(d for d in os.listdir(OUT) if d.startswith("snap_") and d not in before)
keep += [f for f in ("schedule.json", "recipe.json", "tokfp.json", "status.json", "best.json", "train.log", "losses.jsonl",
                     "gen_dev.jsonl", "HISTORY.jsonl") if os.path.exists(OUT + "/" + f)]
if not os.path.exists(OUT + "/ckpt_latest/state.pt"):
    write_result(ok=False, rc=rc, abort="no checkpoint written (trainer rc %s)" % rc)
    sys.exit(0)
with open(OUT + "/HISTORY.jsonl", "a") as f:
    f.write(json.dumps({"side": "kaggle", "seq": EXPECT_SEQ, "step_from": s0, "step_to": s1, "rc": rc, "ngpu": NGPU,
                        "h": round((time.time() - T0) / 3600, 3)}) + "\n")
if "HISTORY.jsonl" not in keep:
    keep.append("HISTORY.jsonl")
files = []
for k in keep:
    p = OUT + "/" + k
    files += [os.path.relpath(os.path.join(a_, f), OUT) for a_, _, fs in os.walk(p) for f in fs] if os.path.isdir(p) else [k]
with open(OUT + "/MD5SUMS", "w") as f:
    for rel in sorted(files):
        f.write("%s  %s\n" % (md5(OUT + "/" + rel), rel))
with tarfile.open(W + "/lineage.tar.part", "w") as t:
    for rel in sorted(files) + ["MD5SUMS"]:
        t.add(OUT + "/" + rel, arcname=rel)
os.replace(W + "/lineage.tar.part", W + "/lineage.tar")
open(W + "/lineage.tar.md5", "w").write("%s  lineage.tar\n" % md5(W + "/lineage.tar"))
shutil.copy(OUT + "/train.log", W + "/train.log") if os.path.exists(OUT + "/train.log") else None
shutil.rmtree(OUT, ignore_errors=True)               # only the tar is downloaded (keeps the output small)
write_result(ok=True, rc=rc, step_to=s1, snaps=[k for k in keep if k.startswith("snap_")])
log("done: rc %s, step %d -> %d" % (rc, s0, s1))
