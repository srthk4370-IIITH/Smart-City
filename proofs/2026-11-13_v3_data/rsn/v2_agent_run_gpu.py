"""v2 step 2 GPU variant: run the FINAL agt_v3 Q4_0 (env AGT_MODEL) on the v2 windows on the GPU (CUDA llama-server, -ngl 99); was CPU ONLY (CUDA_VISIBLE_DEVICES empty, -ngl 0, build-host).
  CUDA_VISIBLE_DEVICES= python3 v2_agent_run.py WINDOWS.jsonl OUT.jsonl [--limit N]
Device path of the agent (host_eval_v2.gen_gguf): greedy, JSON prefill '{"pattern": "', stop at '"action"' / <|eot_id|>,
1 BOS (tokenisation check). Resumable (wids in OUT skipped). Waits while another llama process holds the RAM."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

T = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2"
sys.path[:0] = [T + "/post"]
import common_v2 as C  # noqa: E402
import host_eval_v2 as H  # noqa: E402

MODEL = os.environ["AGT_MODEL"]   # GPU variant (2026-11-16): the FINAL topped-up agent
win, outp = sys.argv[1], Path(sys.argv[2])
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
rows = [json.loads(l) for l in open(win, encoding="utf-8")]
rows = [dict(id=r["wid"], prompt=r["prompt"], role=r["role"]) for r in rows]
done = {json.loads(l)["id"] for l in open(outp)} if outp.exists() else set()
todo = [r for r in rows if r["id"] not in done][: limit or None]
print(len(todo), "to run of", len(rows), flush=True)


def mem_ok():
    busy = subprocess.run("pgrep -f '[l]lama-(imatrix|quantize|perplexity)|[c]onvert_hf_to_gguf' | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
    av = int(next(l for l in open("/proc/meminfo") if l.startswith("MemAvailable")).split()[1]) // 1024
    return busy == "0" and av > 3300, busy, av


LOCK = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK"   # shared GPU lock convention: WAIT, never kill
while os.path.exists(LOCK) and not open(LOCK).read().startswith("v2_agent_run_gpu "):
    print(time.strftime("%H:%M:%S"), "waiting for GPU lock:", open(LOCK).read()[:80].strip(), flush=True)
    time.sleep(300)
open(LOCK, "w").write("v2_agent_run_gpu %s pid=%d\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid()))
import atexit  # noqa: E402
atexit.register(lambda: os.path.exists(LOCK) and open(LOCK).read().startswith("v2_agent_run_gpu ") and os.remove(LOCK))

while True:
    ok, busy, av = mem_ok()
    if ok:
        break
    print(time.strftime("%H:%M:%S"), "waiting: llama procs", busy, "avail MB", av, flush=True)
    time.sleep(120)

C.PREFILL = '{"pattern": "'
_P0 = H.subprocess.Popen


def _popen(args, *k, **kw):   # owner 2026-11-15: no prompt-cache RAM (-cram 0), 3 threads
    if args and str(args[0]).endswith("llama-server"):
        args = [os.path.expanduser("~/llama-cuda-b11815/bin/llama-server")] + list(args[1:]) + ["-cram", "0"]
        if "-ngl" in args:
            args[args.index("-ngl") + 1] = "99"
    return _P0(args, *k, **kw)


H.subprocess.Popen = _popen


class Cfg:
    model = MODEL
    threads = 3
    np = int(os.environ.get("AGT_NP", "1"))  # parallel slots + requests (2026-11-21: 4 for the real-row run)
    slot_ctx = 1600
    max_new = 400


fh = open(outp, "a", encoding="utf-8", newline="\n")


def cb(r, text, meta):
    fh.write(json.dumps(dict(id=r["id"], text=text, **meta), default=str) + "\n")
    fh.flush()
    if os.path.exists(str(outp) + ".STOP"):
        raise SystemExit("STOP file")


t0 = time.time()
if todo:
    H.gen_gguf(todo, Cfg, cb, outp.parent)
print("done", round(time.time() - t0), "s", flush=True)
