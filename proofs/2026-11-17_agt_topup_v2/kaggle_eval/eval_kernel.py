# eval_kernel.py: Kaggle side of the top-up v2 snapshot evaluation (private script kernel, GPU T4 x2, Internet on, ONE private dataset attached:
# agt3-topup2-run holding sets/, adapters/<tag>/, eval_worker.py, rows.py, eval_cfg.json). Base = HF mirror unsloth/Llama-3.2-3B-Instruct (as training).
# One worker per GPU; models are dealt out in the order of eval_cfg["tags"] (priority first); no new model is started after the eval deadline.
import glob, json, os, subprocess, sys, time  # noqa: E401

T0 = time.time()
W = "/kaggle/working"
OUT = W + "/eval_out"
os.makedirs(OUT, exist_ok=True)


def log(m):
    print("[+%.1fmin] %s" % ((time.time() - T0) / 60, m), flush=True)


def find(n):
    g = sorted(glob.glob("/kaggle/input/**/" + n, recursive=True))
    return g[0] if g else None


cf = find("eval_cfg.json")
assert cf, "run dataset not attached"
PACK = os.path.dirname(cf)
CFG = json.load(open(cf))
assert CFG["nonce"] == "@@NONCE@@", "stale run dataset %s" % CFG["nonce"]
subprocess.run("pip uninstall -y -q torchvision torchaudio torchao; pip install -q transformers==5.20.2 peft==0.21.2 accelerate==1.15.0 "
               "safetensors==0.8.0 tokenizers==0.23.3 huggingface_hub==2.3.0", shell=True)
BASE = "/tmp/base"
subprocess.run("python -c \"from huggingface_hub import snapshot_download as s; s('%s', local_dir='%s', allow_patterns=['*.safetensors','*.json'])\""
               % (CFG["base_hf"], BASE), shell=True, check=True)
ngpu = int(subprocess.run("nvidia-smi -L | wc -l", shell=True, capture_output=True, text=True).stdout.strip() or 1)
log("setup done, %d GPU(s)" % ngpu)
deadline = time.time() + CFG["eval_budget_min"] * 60
tags = CFG["tags"]
parts = [tags[i::ngpu] for i in range(ngpu)]
procs = []
for g, p in enumerate(parts):
    if not p:
        continue
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(g), TOKENIZERS_PARALLELISM="false")
    cmd = [sys.executable, PACK + "/eval_worker.py", "--pack", PACK, "--base", BASE, "--out", OUT, "--tags", ",".join(p),
           "--deadline", str(deadline)]
    procs.append(subprocess.Popen(cmd, env=env, stdout=open(W + "/worker%d.log" % g, "w"), stderr=subprocess.STDOUT))
for p in procs:
    p.wait()
done = sorted(os.path.relpath(f, OUT) for f in glob.glob(OUT + "/*/*.done"))
json.dump({"ok": True, "rc": [p.returncode for p in procs], "done": done, "minutes": round((time.time() - T0) / 60, 1),
           "nonce": CFG["nonce"]}, open(W + "/EVAL_RESULT.json", "w"), indent=1)
log("finished: %s" % done)
