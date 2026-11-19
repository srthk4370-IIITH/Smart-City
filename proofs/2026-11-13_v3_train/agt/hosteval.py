"""hosteval.py --model GGUF --rows ROWS.jsonl --out SAMPLES.jsonl [--max-new 400] [--limit N]
Host proxy of the board (host Q4_0 = board 207/208): llama-server CUDA b11815 (-ngl 99, np 4, greedy, device prompt + the row's
JSON prefill + the app stop rule at '"action"') via host_eval_v2.gen_gguf / host_eval3e.use_cuda, the same path as the B50
study (proofs/2026-11-12_agents_holes/scripts/run_A.py), with its guards: 2 s pacing, GPU >= 92 C pause to 88 C, Windows free
RAM < 500 MB pause. Rows in any rows.py form (v3 agt rows or v2 B50 rows). Resumable (ids already in OUT are skipped).
The caller holds the GPU lock (lib.sh gpu_take)."""
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2"
sys.path[:0] = [str(HERE / "kaggle"), T + "/topup3e", T + "/post"]
import rows as RW  # noqa: E402
import common_v2 as C  # noqa: E402
import host_eval_v2 as H  # noqa: E402
import host_eval3e as M  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--rows", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--max-new", type=int, default=400)
ap.add_argument("--limit", type=int, default=0)
a = ap.parse_args()

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
    except Exception:  # noqa: BLE001
        return 99999


def guard():
    with _lk:
        if time.time() - _st["t"] < 30:
            return
        if temp() >= 92:
            print("GPU hot, pausing", flush=True)
            while temp() > 88:
                time.sleep(10)
        while free_mb() < 500:
            print("Windows RAM < 500 MB, pausing", flush=True)
            time.sleep(30)
        _st["t"] = time.time()


def post(url, body, *x, **k):
    if url.endswith("/completion"):
        guard()
        time.sleep(2)
    return _p(url, body, *x, **k)


H._post = post
M.use_cuda()
rows = [RW.norm(r) for r in RW.read_jsonl(a.rows)]
if a.limit:
    rows = rows[:a.limit]
pre = {RW.prefill(r["completion"]) for r in rows}
if len(pre) != 1:
    raise SystemExit("rows mix JSON prefills %s: split the file" % pre)
C.PREFILL = pre.pop()
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
done = {json.loads(l)["id"] for l in open(out)} if out.exists() else set()
todo = [r for r in rows if r["id"] not in done]
print(len(todo), "to run of", len(rows), "prefill", repr(C.PREFILL), flush=True)


class Cfg:
    model = a.model
    threads = 2
    np = 4
    slot_ctx = 2048
    max_new = a.max_new


fh = open(out, "a")


def cb(r, text, meta):
    s = RW.score(r["gold"], text)
    s.update(id=r["id"], text=text, role=r["role"], family=r["family"], **meta)
    fh.write(json.dumps(s, default=str) + "\n")
    fh.flush()


t0 = time.time()
if todo:
    H.gen_gguf(todo, Cfg, cb, out.parent)
print("done", round(time.time() - t0), "s", flush=True)
