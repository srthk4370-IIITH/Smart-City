"""Greedy generation of a Q4_0 GGUF on the laptop CPU with llama-server (WSL, ~/gpu_work/llama.cpp/build-host,
CPU-only: no CUDA toolkit in WSL). Same request as training/v2/post/host_eval_v2.py gen_gguf: prompt without the
leading <|begin_of_text|> (server adds BOS; checked via /tokenize), + PREFILL '{"pattern": "', temperature 0,
top_k 1, n_predict 160, stop ['"action"', '<|eot_id|>'] (the app/htpd stop at the top-level "action" key).
Raw outputs only (scoring on Windows by score_all.py with common_v2). Resumable.
  python3 gen_host.py --model X.gguf --tag v2 --prompts prompts_place.jsonl prompts_host400.jsonl [--threads 4 --np 4]"""
import argparse, json, os, socket, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PREFILL = '{"pattern": "'
BOS = "<|begin_of_text|>"
LLAMA = Path.home() / "gpu_work" / "llama.cpp" / "build-host" / "bin" / "llama-server"
HERE = Path(__file__).resolve().parent


def post(url, body, timeout=3600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8", errors="replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--prompts", nargs="+", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--np", type=int, default=4)
    ap.add_argument("--slot-ctx", type=int, default=2048)
    ap.add_argument("--max-new", type=int, default=160)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out = HERE / "raw" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    sp = out / "outputs.jsonl"
    done = {json.loads(l)["key"] for l in open(sp, encoding="utf-8")} if sp.exists() else set()
    todo = []
    for pf in a.prompts:
        todo += [r for r in map(json.loads, open(HERE / pf, encoding="utf-8")) if r["key"] not in done]
    todo.sort(key=lambda r: r["prompt"])          # shared prefixes adjacent: per-slot prompt cache hits
    if a.limit:
        todo = todo[:a.limit]
    print(f"{a.tag}: {len(todo)} to run ({len(done)} done)", flush=True)
    if not todo:
        return
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    args = [str(LLAMA), "-m", a.model, "-t", str(a.threads), "-tb", str(a.threads), "-c", str(a.slot_ctx * a.np),
            "-np", str(a.np), "--port", str(port), "--host", "127.0.0.1", "-ngl", "0", "-fa", "auto", "--temp", "0"]
    log = open(out / "server.log", "a", encoding="utf-8")
    log.write("ARGS " + " ".join(args) + "\n"); log.flush()
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(900):
            try:
                with urllib.request.urlopen(base + "/health", timeout=5) as f:
                    if json.loads(f.read()).get("status") == "ok":
                        break
            except Exception:
                pass
            if proc.poll() is not None:
                raise SystemExit("llama-server exited")
            time.sleep(1)
        r0 = todo[0]["prompt"]
        t_srv = post(base + "/tokenize", {"content": r0[len(BOS):], "add_special": True})["tokens"]
        t_raw = post(base + "/tokenize", {"content": r0, "add_special": False})["tokens"]
        chk = {"bos_count": t_srv.count(128000), "equal_to_htpd_tokens": t_srv == t_raw, "n_tokens": len(t_srv)}
        (out / "tokenize_check.json").write_text(json.dumps(chk))
        print("tokenize", chk, flush=True)
        if chk["bos_count"] != 1 or not chk["equal_to_htpd_tokens"]:
            raise SystemExit("tokenisation differs from device path")

        def one(r):
            t0 = time.time()
            p = r["prompt"][len(BOS):] if r["prompt"].startswith(BOS) else r["prompt"]
            res = post(base + "/completion", {"prompt": p + PREFILL, "n_predict": a.max_new, "temperature": 0, "top_k": 1,
                                              "cache_prompt": True, "stop": ['"action"', "<|eot_id|>"]})
            text = PREFILL + res.get("content", "")
            if res.get("stop_type") == "word" and res.get("stopping_word") == '"action"':
                text += '"action"'
            tm = res.get("timings", {})
            o = {k: r[k] for k in r if k != "prompt"}
            o.update(text=text, stop_type=res.get("stop_type"), stopping_word=res.get("stopping_word"),
                     tokens=res.get("tokens_predicted"), prompt_n=tm.get("prompt_n"), prompt_ms=tm.get("prompt_ms"),
                     predicted_ms=tm.get("predicted_ms"), cached=res.get("tokens_cached"), wall_s=round(time.time() - t0, 2))
            return o

        t_all, n = time.time(), 0
        with open(sp, "a", encoding="utf-8") as fh, ThreadPoolExecutor(a.np) as ex:
            for o in ex.map(one, todo):
                fh.write(json.dumps(o) + "\n"); fh.flush(); n += 1
                if n % 20 == 0:
                    el = time.time() - t_all
                    print(f"  {n}/{len(todo)} {el / n:.1f}s/row eta {(len(todo) - n) * el / n / 3600:.2f} h", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
