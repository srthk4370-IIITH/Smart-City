"""Checks everything the overnight run needs before it starts."""
import json, os, shutil, subprocess, sys
from pathlib import Path

ok = True
def check(cond, msg):
    global ok
    print(("  OK   " if cond else "  FAIL ") + msg)
    ok &= bool(cond)

root = Path(__file__).resolve().parents[1]
try:
    import torch, transformers, peft, bitsandbytes
    check(torch.cuda.is_available(), f"CUDA available: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'}")
    free, total = torch.cuda.mem_get_info()
    check(free / 2**30 > 4.5, f"GPU free memory {free / 2**30:.1f} / {total / 2**30:.1f} GiB (need > 4.5; close games/browsers using the GPU)")
    print(f"       torch {torch.__version__}, transformers {transformers.__version__}, peft {peft.__version__}, bnb {bitsandbytes.__version__}")
except Exception as e:
    check(False, f"training packages import: {e}")
try:
    t = int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout.split()[0])
    check(t < 70, f"GPU starts at {t} C (want < 70; let the laptop cool, clear the vents)")
except Exception as e:
    print(f"  WARN  could not read GPU temperature: {e}")
mem = {l.split(':')[0]: int(l.split()[1]) for l in open('/proc/meminfo') if l.split(':')[0] in ('MemTotal', 'SwapTotal')}
check(mem['MemTotal'] / 2**20 > 8.0, f"WSL RAM {mem['MemTotal'] / 2**20:.1f} GiB (need >8: run 'wsl --shutdown' once so .wslconfig memory=9GB applies)")
check(shutil.disk_usage(Path.home()).free / 2**30 > 20, f"WSL disk free {shutil.disk_usage(Path.home()).free / 2**30:.0f} GiB (need > 20 for merged model)")
snap = Path.home() / ".cache/huggingface/hub/models--meta-llama--Llama-3.2-3B-Instruct/snapshots"
check(snap.exists() and any(snap.glob('*/model-00002-of-00002.safetensors')), "base model Llama-3.2-3B-Instruct in HF cache")
for s in ("train", "dev", "test"):
    p = root / "data" / "sft" / f"{s}.jsonl"
    check(p.exists() and p.stat().st_size > 100000, f"dataset {p.name} ({p.stat().st_size // 1024 if p.exists() else 0} KB)")
sys.exit(0 if ok else 1)
