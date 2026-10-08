"""Kaggle job: AIMET calibration-only (w4a16) of the GPTQ fine-tuned Llama 3.2 3B on OUR agent prompts.

Produces /kaggle/working/out/model.encodings whose ACTIVATION encodings are calibrated for the
fine-tuned model (the device bundle currently reuses the base model's). Weight encodings in the
result are ignored later - the exact GPTQ scales are kept locally.

Inputs (private dataset srthk4370/qidk-ft-gptq-calib):
  hf__*                 GPTQ fine-tuned HF checkpoint (flattened)
  model_dynamic.onnx    the exact graph we compile locally (so tensor names match)
  gateup_map.json, rebuild_model_data.py   rebuild the 14 GB fp32 model.data from the HF weights
  calib_texts.jsonl     240 train-split prompt+answer texts
  requirements.txt      exact pip freeze of the local qai-hub-models venv
"""
import glob, json, os, shutil, subprocess, sys, threading, time

T0 = time.time()
def log(*a):
    print(f"[{(time.time() - T0) / 60:6.1f} min]", *a, flush=True)

def sh(cmd, env=None):
    log("$", cmd)
    subprocess.run(cmd, shell=True, check=True, env=env)

def mem_watch():
    while True:
        try:
            m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            log(f"MEM avail {m['MemAvailable'] / 2**20:.1f} GiB of {m['MemTotal'] / 2**20:.1f}")
        except Exception:
            pass
        time.sleep(60)
threading.Thread(target=mem_watch, daemon=True).start()

IN = os.path.dirname(glob.glob("/kaggle/input/**/model_dynamic.onnx", recursive=True)[0])
log("input:", IN, os.listdir(IN))
W = "/root/work"
OUT = "/kaggle/working/out"
os.makedirs(f"{W}/merged", exist_ok=True)
os.makedirs(f"{W}/ck", exist_ok=True)
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(f"{IN}/hf__*"):
    dst = f"{W}/merged/{os.path.basename(f)[4:]}"
    if not os.path.exists(dst):
        os.symlink(f, dst)

# 1. exact local toolchain in a Python 3.11 venv
sh("pip install -q uv")
sh("uv venv -q -p 3.11 /root/venv")
reqs = [l.strip() for l in open(f"{IN}/requirements.txt") if l.strip() and not l.startswith("#")]
open(f"{W}/req.txt", "w").write("\n".join(r for r in reqs if not r.lower().startswith(("nvidia-", "triton"))))
sh(f"uv pip install -q -p /root/venv/bin/python --index-strategy unsafe-best-match "
   f"--extra-index-url https://download.pytorch.org/whl/cpu -r {W}/req.txt")
PY = "/root/venv/bin/python"
sh(f"{PY} -c \"import importlib.metadata as m; print([(p, m.version(p)) for p in ('torch','transformers','aimet-onnx','qai_hub_models','onnx')])\"")

# 2. checkpoint dir: exact graph + rebuilt fp32 weights
shutil.copy(f"{IN}/model_dynamic.onnx", f"{W}/ck/model_dynamic.onnx")
if not os.path.exists(f"{W}/ck/model.data"):
    sh(f"{PY} {IN}/rebuild_model_data.py {W}/ck/model_dynamic.onnx {W}/merged {IN}/gateup_map.json {W}/ck/model.data")

# 3. calibration data hook (replaces wikitext with our prompts) + calibration-only recipe
os.makedirs(f"{W}/hooks", exist_ok=True)
open(f"{W}/hooks/calibhook.py", "w").write(f'''
import json
from datasets import Dataset
from qai_hub_models.datasets.wikitext.wikitext import WikiText
def _load_raw_dataset(self):
    return Dataset.from_dict({{"text": [json.loads(l)["text"] for l in open("{IN}/calib_texts.jsonl", encoding="utf-8")]}})
WikiText.load_raw_dataset = _load_raw_dataset
print("calibhook: WikiText replaced by agent prompts", flush=True)

# Memory: the FP torch model is only used to prepare calibration inputs (prefill / KV cache). Keep it in
# bf16 (6.4 GB instead of 12.8 GB) and cast its outputs back to fp32, so it fits next to the 14.4 GB
# ONNX graph inside Kaggle's 30 GiB limit (no swap allowed there).
import gc, torch
from qai_hub_models.models.llama_v3_2_3b_instruct import model as _M
_orig_fp = _M.Llama3_2_3B_PreSplit.from_pretrained.__func__
def _cast(x, src, dst):
    if torch.is_tensor(x):
        return x.to(dst) if x.dtype == src else x
    if isinstance(x, (list, tuple)):
        return type(x)(_cast(y, src, dst) for y in x)
    if isinstance(x, dict):
        return {{k: _cast(v, src, dst) for k, v in x.items()}}
    return x
def _fp_bf16(cls, *a, **k):
    m = _orig_fp(cls, *a, **k)
    m = m.to(torch.bfloat16)
    gc.collect()
    fwd = m.forward
    def forward(*fa, **fk):
        return _cast(fwd(*_cast(fa, torch.float32, torch.bfloat16), **_cast(fk, torch.float32, torch.bfloat16)),
                     torch.bfloat16, torch.float32)
    m.forward = forward
    print("calibhook: FP model kept in bf16", flush=True)
    return m
_M.Llama3_2_3B_PreSplit.from_pretrained = classmethod(_fp_bf16)
''')
NUM_IT = int(os.environ.get("NUM_IT", "16"))
CTX = int(os.environ.get("CTX", "2048"))
open(f"{W}/recipe.yaml", "w").write(f"""precision:
  activations: int16
  kv_cache:    int8
  embedding:   int16
  lm_head:
    qtype:       int8
    granularity: PCQ
  blocks:
    default:
      qtype:       int4
      granularity: PCQ
recipe:
  - name: Calibration
    num_iterations: {NUM_IT}
    dataset:
      name:  Wikitext
      split: train
""")

# 4. quantize (CPU only; calibration needs no CUDA)
env = dict(os.environ, CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
           PYTHONPATH=f"{W}/hooks", PYTHONUNBUFFERED="1")
driver = (f"import calibhook, runpy, sys; sys.argv=['quantize','--checkpoint','{W}/merged','--output-dir','{W}/ck',"
          f"'--precision','{W}/recipe.yaml','--context-length','{CTX}','--calibration-sequence-length','1024'];"
          f"runpy.run_module('qai_hub_models.models.llama_v3_2_3b_instruct.quantize', run_name='__main__')")
open(f"{W}/driver.py", "w").write(driver)
try:
    sh(f"{PY} {W}/driver.py", env=env)
finally:
    for f in ("model.encodings", "args.json"):
        if os.path.exists(f"{W}/ck/{f}"):
            shutil.copy(f"{W}/ck/{f}", f"{OUT}/{f}")
    log("out:", os.listdir(OUT))

# 5. sanity: activation encodings must name tensors of our graph
e = json.load(open(f"{OUT}/model.encodings"))
acts = e["activation_encodings"]
names = [a["name"] for a in acts] if isinstance(acts, list) else list(acts)
log("activation encodings:", len(names), "param encodings:", len(e["param_encodings"]))
log("DONE")
