#!/usr/bin/env python3
"""Host overhead of the synth-context LoRA: one htpd v8 process, plain greedy (no drafting, no prefix cache),
interleaved off/on requests on the same prompt, N rounds. Prefill tok/s = prompt tokens / prefill_ms,
decode tok/s = (tokens-1) / (ms - ttft_ms).
usage: python3 host_speed.py --bin B --model M --lora L [--via env|flag] --prompt-file agents.jsonl --out F
"""
import argparse, json, os, socket, statistics, subprocess, time


def call(port, req):
    s = socket.create_connection(("127.0.0.1", port), timeout=3600)
    s.sendall((json.dumps(req) + "\n").encode())
    d = json.loads(s.makefile("rb").readline())
    s.close()
    return d


def main():
    ap = argparse.ArgumentParser()
    for k in ["bin", "model", "lora", "prompt-file", "out"]:
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--via", default="flag")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-new", type=int, default=64)
    ap.add_argument("--port", type=int, default=8392)
    a = ap.parse_args()
    prompt = json.loads(open(a.prompt_file).readline())["prompt"] + '{"pattern": "'
    env = {k: v for k, v in os.environ.items() if not k.startswith("HTPD_")}
    env["HTPD_SPEC"] = "0"
    args = [a.bin, "-m", a.model, "--device", "CPU", "--port", str(a.port), "--agents", "1", "--agent-ctx", "1280",
            "--synth-ctx", "2048", "-t", "4", "--ubatch-synth", "512", "--max-new", str(a.max_new)]
    if a.via == "env":
        env["HTPD_LORA_SYNTH"] = a.lora
    else:
        args += ["--lora-synth", a.lora]
    log = open(a.out + ".log", "wb")
    p = subprocess.Popen(args, env=env, stdout=log, stderr=log)
    for _ in range(900):
        try:
            socket.create_connection(("127.0.0.1", a.port), timeout=1).close(); break
        except OSError:
            time.sleep(1)
    n_prompt = None
    rows = []
    try:
        call(a.port, {"kind": "synth", "prompt": prompt, "lora": False})  # warm-up (page cache, graph)
        for r in range(a.rounds):
            for lora in ([False, True] if r % 2 == 0 else [True, False]):
                d = call(a.port, {"kind": "synth", "prompt": prompt, "lora": lora})
                o = d["outputs"][0]
                rows.append({"round": r, "lora": lora, "lora_scale": d.get("lora_scale"), "tokens": o["tokens"], "prefill_ms": d["prefill_ms"],
                             "decode_tok_s": (o["tokens"] - 1) / ((o["ms"] - o["ttft_ms"]) / 1000), "text": o["text"]})
                print(rows[-1]["lora"], rows[-1]["tokens"], round(rows[-1]["prefill_ms"]), round(rows[-1]["decode_tok_s"], 2), flush=True)
    finally:
        p.terminate(); p.wait()
    for line in open(a.out + ".log", errors="replace"):
        if "v8 LoRA" in line or "LoRA buffer" in line:
            print(line.strip())
    med = lambda lora, k: statistics.median(x[k] for x in rows if x["lora"] == lora)
    summ = {"bin": a.bin, "model": a.model, "lora": a.lora, "via": a.via, "rounds": a.rounds,
            "prefill_ms_off": med(False, "prefill_ms"), "prefill_ms_on": med(True, "prefill_ms"),
            "decode_tok_s_off": med(False, "decode_tok_s"), "decode_tok_s_on": med(True, "decode_tok_s")}
    summ["prefill_overhead_pct"] = 100 * (summ["prefill_ms_on"] / summ["prefill_ms_off"] - 1)
    summ["decode_overhead_pct"] = 100 * (summ["decode_tok_s_off"] / summ["decode_tok_s_on"] - 1)
    summ["texts_stable"] = len({x["text"] for x in rows if x["lora"]}) == 1 and len({x["text"] for x in rows if not x["lora"]}) == 1
    json.dump({"summary": summ, "rows": rows}, open(a.out, "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
