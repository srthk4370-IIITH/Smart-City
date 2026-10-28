#!/usr/bin/env python3
"""P0 host (x86 CPU) check of htpd v8 --lora-synth against v7, over the real TCP protocol.

usage (WSL): python3 host_lora_test.py --v7 BIN --v8 BIN --out DIR --agents agents.jsonl --synth synth.jsonl \
                 --model-b V2_Q4_0 --lora-b DELTA.gguf --ref-b 3D_Q4_0 --model-a BASE_Q8_0 --lora-a V2LORA.gguf --ref-a V2_Q8_0

Test B (deployment shape): the deployed v2 Q4_0 model + a small delta adapter (3d step 50 - v2, r=16, F16).
  - v8 without --lora-synth == v7 (every response, byte for byte apart from timings)
  - v8 --lora-synth: agents == v7; synth "lora":false == v7; synth with the adapter differs and moves towards
    the 3d model (ref-b, merged 3d Q4_0); prefix cache keyed per adapter (on/off/on order gives on == on)
Test A (large, predictable effect): base Llama-3.2-3B Q8_0 + the v2 LoRA (r=32, F16) on the synth context must
  reproduce the merged v2 model (ref-a, v2 Q8_0), while the agent context stays the base model (== v7 on base).
Writes DIR/results.json (all raw lines), DIR/checks.json, DIR/htpd_host.log.
"""
import argparse, difflib, json, os, re, socket, subprocess, time

PRE = '{"pattern": "'
ENV = {"HTPD_SPEC": "0", "HTPD_LEGACY_PREFILL": "1", "HTPD_DRAFT": "1", "HTPD_DRAFT_K": "8", "HTPD_PREFIX_CACHE": "1",
       "HTPD_AGENT_MAX_NEW": "160", "HTPD_JSON_ABORT": "2", "HTPD_SYNTH_PREFIX_CACHE": "1"}


def call(port, req, timeout=7200):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((json.dumps(req) + "\n").encode())
    f = s.makefile("rb")
    t0 = time.time()
    while True:
        l = f.readline()
        if not l:
            raise RuntimeError("connection closed")
        d = json.loads(l)
        if "outputs" in d or "error" in d:
            s.close()
            return d, time.time() - t0


def start(binary, model, port, extra, log, threads):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HTPD_")}
    env.update(ENV)
    p = subprocess.Popen([binary, "-m", model, "--device", "CPU", "--port", str(port), "--agents", "3", "--agent-ctx", "1280",
                          "--synth-ctx", "4096", "-t", str(threads), "--ubatch", "512", "--ubatch-synth", "512"] + extra,
                         env=env, stdout=log, stderr=log)
    for _ in range(900):
        if p.poll() is not None:
            raise RuntimeError(f"htpd exited rc={p.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return p
        except OSError:
            time.sleep(1)
    raise RuntimeError("htpd did not come up")


def strip_times(d):
    """response without timing fields (the bytes that must be identical)"""
    s = json.dumps(d, sort_keys=True)
    return re.sub(r'"(ttft_ms|ms|prefill_ms|swap_ms|total_ms)": [0-9.e+-]+', r'"\1": 0', s)


def texts(d):
    return [(o["text"], o["stop"], o["tokens"]) for o in d["outputs"]]


def decode_tps(d):
    o = d["outputs"][0]
    dt = (o["ms"] - o["ttft_ms"]) / 1000.0
    return {"tokens": o["tokens"], "ttft_ms": o["ttft_ms"], "ms": o["ms"], "decode_tok_s": (o["tokens"] - 1) / dt if dt > 0 else None,
            "prefill_ms": d.get("prefill_ms")}


def sim(a, b):
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


def main():
    ap = argparse.ArgumentParser()
    for k in ["v7", "v8", "out", "agents", "synth", "model-b", "lora-b", "ref-b", "model-a", "lora-a", "ref-a"]:
        ap.add_argument("--" + k)
    ap.add_argument("--port", type=int, default=8391)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--n-synth", type=int, default=2)
    ap.add_argument("--only", default="A,B")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    arows = [json.loads(l) for l in open(a.agents)]
    srows = [json.loads(l) for l in open(a.synth)][: a.n_synth]
    agent_prompts = [r["prompt"] + PRE for r in arows[:3]]
    synth_prompts = [r["prompt"] for r in srows]
    agents_req = {"kind": "agents", "prompts": agent_prompts}
    log = open(os.path.join(a.out, "htpd_host.log"), "ab")
    rpath = os.path.join(a.out, "results.json")
    res = json.load(open(rpath)) if os.path.exists(rpath) else {}

    def run(name, binary, model, extra, reqs):
        if name in res:
            print("cached", name, flush=True)
            return
        log.write(f"\n===== {name} {binary} {model} {extra} {ENV}\n".encode()); log.flush()
        p = start(binary, model, a.port, extra, log, a.threads)
        out = {}
        try:
            for rn, req in reqs:
                d, wall = call(a.port, req)
                out[rn] = {"resp": d, "wall_s": wall}
                print(name, rn, f"{wall:.1f}s", [(o.get("stop"), o.get("tokens")) for o in d.get("outputs", [])], d.get("lora_scale"), flush=True)
        finally:
            p.terminate(); p.wait()
        res[name] = out
        json.dump(res, open(rpath, "w"), indent=1)

    def synth(i, **kw):
        return dict({"kind": "synth", "prompt": synth_prompts[i]}, **kw)

    # agent prompt as a synth-kind request (no action trim, synth context): shows the adapter on the agent task
    def asynth(i, **kw):
        return dict({"kind": "synth", "prompt": agent_prompts[i]}, **kw)

    base_reqs = [("agents", agents_req)] + [(f"synth{i}", synth(i)) for i in range(len(synth_prompts))] + [("asynth0", asynth(0))]
    lora_reqs = ([("synth0_on", synth(0)), ("synth0_off", synth(0, lora=False)), ("synth0_on2", synth(0, lora=True)),
                  ("agents", agents_req), ("asynth0_on", asynth(0)), ("asynth0_off", asynth(0, lora=0))]
                 + [(f"synth{i}_on", synth(i)) for i in range(1, len(synth_prompts))]
                 + [(f"synth{i}_off", synth(i, lora=False)) for i in range(1, len(synth_prompts))])
    if "B" in a.only:
        run("B_v7", a.v7, a.model_b, [], base_reqs)
        run("B_v8_noflag", a.v8, a.model_b, [], base_reqs)
        run("B_v8_lora", a.v8, a.model_b, ["--lora-synth", a.lora_b], lora_reqs)
        run("B_v7_ref3d", a.v7, a.ref_b, [], [(f"synth{i}", synth(i)) for i in range(len(synth_prompts))] + [("asynth0", asynth(0))])
    if "A" in a.only:
        run("A_v7_base", a.v7, a.model_a, [], base_reqs)
        run("A_v8_lora", a.v8, a.model_a, ["--lora-synth", a.lora_a], lora_reqs)
        run("A_v7_refv2", a.v7, a.ref_a, [], base_reqs)

    R = lambda n, r: res[n][r]["resp"]
    T = lambda n, r: R(n, r)["outputs"][0]["text"]
    checks, info = {}, {}
    ns = len(synth_prompts)
    if "B" in a.only:
        checks["B: v8 no flag == v7, all responses byte-identical (timings aside)"] = all(
            strip_times(R("B_v8_noflag", r)) == strip_times(R("B_v7", r)) for r, _ in base_reqs)
        checks["B: v8 --lora-synth agents == v7 agents"] = texts(R("B_v8_lora", "agents")) == texts(R("B_v7", "agents"))
        checks["B: synth lora:false == v7 synth (after an adapter run; cache keyed)"] = all(
            texts(R("B_v8_lora", f"synth{i}_off")) == texts(R("B_v7", f"synth{i}")) for i in range(ns))
        checks["B: asynth lora:0 == v7"] = T("B_v8_lora", "asynth0_off") == T("B_v7", "asynth0")
        checks["B: adapter on twice -> identical (prefix cache per adapter)"] = texts(R("B_v8_lora", "synth0_on")) == texts(R("B_v8_lora", "synth0_on2"))
        checks["B: lora_scale reported (1 on, 0 off)"] = R("B_v8_lora", "synth0_on").get("lora_scale") == 1 and R("B_v8_lora", "synth0_off").get("lora_scale") == 0
        info["B"] = {}
        for i in range(ns):
            on, off, ref = T("B_v8_lora", f"synth{i}_on"), T("B_v7", f"synth{i}"), T("B_v7_ref3d", f"synth{i}")
            info["B"][f"synth{i}"] = {"on_eq_base": on == off, "on_eq_3d": on == ref, "sim_on_3d": sim(on, ref), "sim_base_3d": sim(off, ref),
                                      "sim_on_base": sim(on, off)}
        on, off, ref = T("B_v8_lora", "asynth0_on"), T("B_v7", "asynth0"), T("B_v7_ref3d", "asynth0")
        info["B"]["asynth0"] = {"on_eq_base": on == off, "on_eq_3d": on == ref, "sim_on_3d": sim(on, ref), "sim_base_3d": sim(off, ref)}
        info["B"]["speed"] = {"synth0_on": decode_tps(R("B_v8_lora", "synth0_on2")), "synth0_off": decode_tps(R("B_v8_lora", "synth0_off")),
                              "synth0_v7": decode_tps(R("B_v7", "synth0"))}
    if "A" in a.only:
        checks["A: v8 --lora-synth agents == v7 agents (base model, adapter not on agents)"] = texts(R("A_v8_lora", "agents")) == texts(R("A_v7_base", "agents"))
        checks["A: synth lora:false == v7 on base"] = all(texts(R("A_v8_lora", f"synth{i}_off")) == texts(R("A_v7_base", f"synth{i}")) for i in range(ns))
        info["A"] = {}
        for i in range(ns):
            on, base, v2 = T("A_v8_lora", f"synth{i}_on"), T("A_v7_base", f"synth{i}"), T("A_v7_refv2", f"synth{i}")
            info["A"][f"synth{i}"] = {"on_eq_v2merged": on == v2, "sim_on_v2": sim(on, v2), "sim_base_v2": sim(base, v2),
                                      "on": on[:400], "base": base[:400], "v2": v2[:400]}
        on, base, v2 = T("A_v8_lora", "asynth0_on"), T("A_v7_base", "asynth0"), T("A_v7_refv2", "asynth0")
        info["A"]["asynth0"] = {"on_eq_v2merged": on == v2, "sim_on_v2": sim(on, v2), "sim_base_v2": sim(base, v2), "on": on, "base": base, "v2": v2}
        info["A"]["speed"] = {"synth0_on": decode_tps(R("A_v8_lora", "synth0_on2")), "synth0_off": decode_tps(R("A_v8_lora", "synth0_off")),
                              "synth0_v7_base": decode_tps(R("A_v7_base", "synth0"))}
    json.dump({"checks": checks, "info": info}, open(os.path.join(a.out, "checks.json"), "w"), indent=1)
    print(json.dumps(checks, indent=1))
    print(json.dumps(info, indent=1)[:6000])


if __name__ == "__main__":
    main()
