"""Study A runner: live B50 GGUF (Code/models_stage/ft_B50_q4_0.gguf) on llama-server CUDA b11815 (-ngl 99, np 4, greedy,
device prompt + prefill + app stop rule = host_eval_v2.gen_gguf via host_eval3e.use_cuda). Guards on every request: 2 s
pacing (owner thermal rule), GPU >= 92 C -> pause until <= 88 C, Windows free RAM < 500 MB -> pause. Resumable."""
import json, subprocess, sys, threading, time
from pathlib import Path
T = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2"
sys.path[:0] = [T + "/topup3e", T + "/post"]
import common_v2 as C, host_eval_v2 as H, host_eval3e as M
RAW = Path(__file__).resolve().parent.parent / "raw"
_p, _lk, _st = H._post, threading.Lock(), {"t": 0.0}
def temp():
    o = subprocess.run("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader | head -1 | cut -d. -f1 | tr -dc 0-9",
                       shell=True, capture_output=True, text=True).stdout
    return int(o or 0)
def free_mb():
    try:
        o = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                           capture_output=True, text=True, timeout=60).stdout
        return int(o.strip()) // 1024
    except Exception:
        return 99999
def guard():
    with _lk:
        if time.time() - _st["t"] < 30:
            return
        if temp() >= 92:
            print("GPU hot, pausing", flush=True)
            while temp() > 88: time.sleep(10)
        while free_mb() < 500:
            print("Windows RAM < 500 MB, pausing", flush=True); time.sleep(30)
        _st["t"] = time.time()
def post(url, body, *a, **k):
    if url.endswith("/completion"):
        guard(); time.sleep(2)
    return _p(url, body, *a, **k)
H._post = post
M.use_cuda()
class A: model = "/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/ft_B50_q4_0.gguf"; threads = 2; np = 4; slot_ctx = 1536; max_new = 160
rows = C.read_jsonl(RAW / "rows_A.jsonl")
sp = RAW / "samples_A.jsonl"
done = {json.loads(l)["id"] for l in open(sp)} if sp.exists() else set()
todo = [r for r in rows if r["id"] not in done]
print(len(todo), "to run", flush=True)
fh = open(sp, "a")
def cb(r, text, meta):
    s = C.score_one(r, text); s.update(text=text, variant=r["variant"], slices=r["slices_all"], **meta)
    fh.write(json.dumps(s, default=str) + "\n"); fh.flush()
t0 = time.time()
if todo:
    H.gen_gguf(todo, A, cb, RAW)
print("done", round(time.time() - t0), "s", flush=True)
