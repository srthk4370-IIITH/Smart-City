"""Throughput bench for the distillation llama-server configs (holds GPU_LOCK). For each config: start the server,
send real chat3 prompts (rendered like the distiller) with concurrency = slots, 200 generated tokens each (ignore_eos),
3 waves; report aggregate generated tok/s, per-request decode tok/s, VRAM. Results -> bench_server.json.
  ~/venvs/rsn/bin/python bench_server.py"""
import json, os, subprocess, sys, threading, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import chatloop as CL  # noqa
LLAMA = os.path.expanduser("~/llama-cuda-b11815"); GG = os.environ.get("GG", os.path.expanduser("~/models/qwen3.5-4b-gguf/qwen3.5-4b-q8_0.gguf"))
LOCK = os.path.join(CL.V3, "GPU_LOCK"); PORT = 18112
CONFIGS = [("np4_base", 4, 7680, "-cram 2048 -ctxcp 4"),
           ("np4_fa_q8kv_ub", 4, 7680, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 2048 -ctxcp 4"),
           ("np6_fa_q8kv", 6, 7680, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 1024 -ctxcp 2"),
           ("np8_fa_q8kv", 8, 7168, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 1024 -ctxcp 2"),
           ("np6_cms256", 6, 7680, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 1024 -ctxcp 8 -cms 256"),
           ("np6_cms256_ub1k", 6, 7680, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 1024 -cram 1024 -ctxcp 8 -cms 256"),
           ("np4_cms256", 4, 7680, "-fa on -ctk q8_0 -ctv q8_0 -b 2048 -ub 512 -cram 1024 -ctxcp 8 -cms 256")]
if len(sys.argv) > 1:
    CONFIGS = [c for c in CONFIGS if c[0] in sys.argv[1:]]

def post(path, body, timeout=900):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def main():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b"))
    tools = CL.load_tools()["chat"]
    recs = [json.loads(l) for l in open(os.path.join(CL.V3, "data", "chat3_train.jsonl"))][:40]
    prompts = [CL.render(tok, CL.prompt_messages(r), tools, False) for r in recs]
    while os.path.exists(LOCK):
        print("waiting for GPU_LOCK", open(LOCK).read().strip(), flush=True); time.sleep(30)
    open(LOCK, "w").write("distill_laptop_bench %s pid=%d\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
    res = []
    try:
        for name, np_, cs, extra in CONFIGS:
            cmd = [os.path.join(LLAMA, "bin", "llama-server"), "-m", GG, "-ngl", "99", "-c", str(np_ * cs), "-np", str(np_), "-t", "4",
                   "--host", "127.0.0.1", "--port", str(PORT), "--no-webui", "--load-mode", "none"] + extra.split()
            lf = open(os.path.join(HERE, "bench_%s.log" % name), "w")
            sp = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=dict(os.environ, LD_LIBRARY_PATH=os.path.join(LLAMA, "bin")))
            ok = False
            for _ in range(120):
                time.sleep(2)
                if sp.poll() is not None: break
                try:
                    ok = b"ok" in urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5).read()
                    if ok: break
                except Exception: pass
            if not ok:
                res.append({"name": name, "error": "server did not start (rc %s)" % sp.poll()}); print(res[-1], flush=True)
                sp.kill(); continue
            vram = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
            stats = []
            def one(p):
                o = post("/completion", {"prompt": p, "n_predict": 200, "ignore_eos": True, "temperature": 0.7, "top_k": 20, "top_p": 0.95, "cache_prompt": True})
                stats.append(o["timings"])
            post("/completion", {"prompt": prompts[0], "n_predict": 8})       # warm-up (header into a slot)
            t0 = time.time(); k = 0
            for wave in range(3):
                th = [threading.Thread(target=one, args=(prompts[(k + i) % len(prompts)],)) for i in range(np_)]
                k += np_
                [t.start() for t in th]; [t.join() for t in th]
            wall = time.time() - t0
            gen = sum(s["predicted_n"] for s in stats)
            r = {"name": name, "np": np_, "ctx_slot": cs, "extra": extra, "vram_mib": vram, "requests": len(stats), "wall_s": round(wall, 1),
                 "agg_tok_s": round(gen / wall, 1), "per_req_decode_tok_s": round(sum(s["predicted_per_second"] for s in stats) / len(stats), 1),
                 "mean_prompt_eval": round(sum(s["prompt_n"] for s in stats) / len(stats)), "prompt_tok_s": round(sum(s["prompt_per_second"] for s in stats) / len(stats))}
            res.append(r); print(r, flush=True)
            sp.terminate(); sp.wait(30)
    finally:
        try:
            if open(LOCK).read().startswith("distill_laptop_bench"): os.remove(LOCK)
        except Exception: pass
        json.dump(res, open(os.path.join(HERE, "bench_server_%s.json" % os.path.basename(GG)), "a"), indent=1)

main()
