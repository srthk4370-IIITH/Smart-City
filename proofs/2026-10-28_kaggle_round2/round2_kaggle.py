# %% [markdown]
# # Reasoner round 2 on Kaggle
# chat paraphrases + replay (base Qwen3.5-4B, GPU) -> verify -> mix2 -> QLoRA continue from step 612 -> adapter zip.
# Settings: Accelerator **GPU T4 x2**, Internet **On**, input = the private dataset holding `rsn_r2_bundle.zip`.
# Run with **Save Version -> Save & Run All (Commit)**. If it stops before training is done (12 h limit), add this
# notebook's previous version output as an input and commit again: it resumes from the last checkpoint (every 25 steps).

# %%
import glob, json, os, shutil, subprocess, sys, time
T0 = time.time(); BUDGET_H = 11.3                     # training saves and exits before Kaggle's 12 h session limit
W = "/kaggle/working"; R2 = "/tmp/r2"; STATE = W + "/r2_state"; BASE = "/tmp/base"


def sh(c):
    print("$", c, flush=True)
    r = subprocess.run(c, shell=True)
    if r.returncode:
        raise SystemExit("FAILED (%d): %s" % (r.returncode, c))


sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv")

# %% pinned versions = the laptop venv ~/venvs/rsn (Python 3.12, torch 2.6.0+cu124)
sh("pip uninstall -y -q torchvision torchaudio")  # keep Kaggle torch; torchvision breaks transformers import
sh("pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 bitsandbytes==0.50.2 safetensors==0.8.0 "
   "tokenizers==0.23.3 sentencepiece==0.2.2 huggingface_hub==2.3.0")
sh("python -c \"import torch,transformers,peft,bitsandbytes;print(torch.__version__,transformers.__version__,peft.__version__,"
   "bitsandbytes.__version__,torch.cuda.device_count(),torch.cuda.get_device_capability(0))\"")

# %% find the bundle (Kaggle auto-extracts the zip under /kaggle/input/...) and copy it somewhere writable
mk = glob.glob("/kaggle/input/**/BUNDLE_OK", recursive=True)
assert mk, "bundle not attached: Add Input -> Your Datasets -> the dataset holding rsn_r2_bundle.zip"
if not os.path.exists(R2):
    shutil.copytree(os.path.dirname(mk[0]), R2)
T = R2 + "/proofs/2026-10-25_reasoner_final"; P = T + "/pipeline"; D = T + "/data"
ADAPTER = R2 + "/adapter/ckpt_step0612"
os.makedirs(STATE + "/data", exist_ok=True)

# %% resume: state from a previous version's output, if attached (generated data + run2 checkpoints)
prev = sorted(glob.glob("/kaggle/input/**/r2_state/run2/status.json", recursive=True), key=os.path.getmtime)
if prev and not os.path.exists(STATE + "/run2/status.json"):
    ps = os.path.dirname(os.path.dirname(prev[-1]))
    print("resuming from", ps)
    shutil.copytree(ps, STATE, dirs_exist_ok=True)
for n in ["chat2_train.jsonl", "replay_train.jsonl"]:
    for c in [STATE + "/data/" + n] + glob.glob("/kaggle/input/**/r2_state/data/" + n, recursive=True):
        if os.path.exists(c) and not os.path.exists(D + "/" + n):
            shutil.copy(c, D + "/" + n)

# %% base model from the HF hub, checked against the laptop copy's SHA256SUMS (same weights as round 1)
if not os.path.exists(BASE + "/OK"):
    sh("python -c \"from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3.5-4B', local_dir='%s')\"" % BASE)
    sh("cd %s && sha256sum -c --ignore-missing %s/base/SHA256SUMS" % (BASE, R2))
    open(BASE + "/OK", "w").close()

# %% 1) generation on the GPU(s): 1,200 seeds x 5 paraphrases (cap 5,000) + 515 replay answers, base model in-process
G = R2 + "/kaggle/kaggle_gen.py"
if not os.path.exists(D + "/chat2_train.jsonl"):
    sh("python %s --base %s --pipeline %s --what chat --seeds 1200 --k 5 --cap 5000 --out %s/chat2_train.jsonl" % (G, BASE, P, D))
    shutil.copy(D + "/chat2_train.jsonl", STATE + "/data/")
if not os.path.exists(D + "/replay_train.jsonl"):
    sh("python %s --base %s --pipeline %s --what replay" % (G, BASE, P))
    shutil.copy(D + "/replay_train.jsonl", STATE + "/data/")
sh("cd %s && python verify.py %s/chat2_train.jsonl %s/replay_train.jsonl | tee %s/verify.txt" % (P, D, D, STATE))

# %% 2) mix2: incidents 50 % (incl. 450 borderline), chat2 35 %, replay 15 %; "chatter" family excluded
sh("cd %s && python build_mix2.py | tee %s/mix2.txt" % (P, STATE))

# %% 3) QLoRA continue from step 612: LR 5e-5, 1 pass, ckpt every 25 (fp16 + GradScaler on T4/P100, bf16 on Ampere+)
TR = R2 + "/kaggle/train_rsn_kaggle.py"
sh("python %s/kaggle/patch_train.py %s/train/train_rsn.py %s %s %s" % (R2, T, TR, T, BASE))
ARGS = ("--data %s/train_mix2.jsonl --init-adapter %s --lr 5e-5 --epochs 1 --max-len 3200 --hb '' "
        "--thermal-pause-at 95 --thermal-resume-at 90" % (D, ADAPTER))
OUT = STATE + "/run2"
os.makedirs(OUT, exist_ok=True)
os.environ.update(TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True", CUDA_VISIBLE_DEVICES="0")
if not os.path.exists(OUT + "/ckpt_latest/state.pt"):      # pre-flight: the 612 adapter's loss must be finite and small
    sh("python %s --out %s %s --probe 6" % (TR, OUT, ARGS))
    pl = [l for l in open(OUT + "/train.log") if "PROBE" in l][-1]
    print(pl)
    lv = float(pl.split("loss")[1].split()[0])
    assert lv == lv and lv < 1.5, "probe loss %s: fp16 numerics look wrong; stop and report" % lv
hours = BUDGET_H - (time.time() - T0) / 3600
print("training budget this session: %.2f h" % hours)
subprocess.run("python %s --out %s %s --hours %.2f" % (TR, OUT, ARGS, max(0.2, hours)), shell=True)
st = json.load(open(OUT + "/status.json"))
print(st)

# %% 4) package: the final step's adapter when done, else the latest checkpoint marked PARTIAL
ck = sorted(glob.glob(OUT + "/ckpt_step*"))
src = ck[-1] if st.get("done") and ck else OUT + "/ckpt_latest"
pk = W + "/rsn_r2_adapter"
shutil.rmtree(pk, ignore_errors=True)
os.makedirs(pk)
for f in ["adapter_model.safetensors", "adapter_config.json"]:
    shutil.copy(os.path.join(src, f), pk)
for f in ["status.json", "train.log", "losses.jsonl"]:
    if os.path.exists(OUT + "/" + f):
        shutil.copy(OUT + "/" + f, pk)
for f in ["mix2.txt", "verify.txt"]:
    shutil.copy(STATE + "/" + f, pk)
gpu = subprocess.run("nvidia-smi --query-gpu=name --format=csv,noheader", shell=True, capture_output=True, text=True).stdout.strip()
json.dump({"source_ckpt": os.path.basename(src), "done": bool(st.get("done")), "step": st["step"], "total": st["total"],
           "gpu": gpu, "wall_h": round((time.time() - T0) / 3600, 2)}, open(pk + "/KAGGLE_MANIFEST.json", "w"), indent=1)
name = "rsn_r2_adapter" if st.get("done") else "rsn_r2_adapter_PARTIAL"
shutil.make_archive(W + "/" + name, "zip", pk)
shutil.rmtree(pk)
print("DONE" if st.get("done") else "PARTIAL: add this version's output as input and commit again to resume", os.listdir(W))
