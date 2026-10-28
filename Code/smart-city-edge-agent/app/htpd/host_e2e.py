#!/usr/bin/env python3
"""Host (x86 CPU) end-to-end check of htpd v7 against v6: same model, same prompts, real TCP protocol.

usage (WSL): python3 host_e2e.py --v6 BIN --v7 BIN --model GGUF --prompts prompts.jsonl --out DIR
Writes DIR/results.json. Checks: v7 with no v7 flags == v6 (texts, stops); streamed pieces concatenate to the
final text; all v7 flags on leave on-label outputs unchanged; the label constraint forces a label; the agent
token cap; logprobs; synth streaming.
"""
import argparse, json, os, socket, subprocess, sys, time

PRE = '{"pattern": "'


def call(port, req, timeout=3600):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall((json.dumps(req) + "\n").encode())
    f = s.makefile("rb")
    lines = []
    t0 = time.time()
    while True:
        l = f.readline()
        if not l:
            break
        d = json.loads(l)
        lines.append((time.time() - t0, d))
        if "outputs" in d or "error" in d:
            break
    s.close()
    return lines


def start(binary, model, port, env_extra, log):
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("HTPD_"):
            del env[k]
    env.update(env_extra)
    p = subprocess.Popen([binary, "-m", model, "--device", "CPU", "--port", str(port), "--agents", "2",
                          "--agent-ctx", "1280", "--synth-ctx", "1536", "-t", "2", "--ubatch", "512", "--ubatch-synth", "512"],
                         env=env, stdout=log, stderr=log)
    for _ in range(600):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return p
        except OSError:
            time.sleep(1)
    raise RuntimeError("htpd did not come up")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v6"); ap.add_argument("--v7"); ap.add_argument("--model"); ap.add_argument("--prompts")
    ap.add_argument("--out"); ap.add_argument("--port", type=int, default=8291)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = [json.loads(l) for l in open(a.prompts)]
    prompts = [r["prompt"] + PRE for r in rows[:2]]
    synth = rows[2]["prompt"]  # any prompt; synth kind = no action trim, no v7 agent features
    base_env = {"HTPD_DRAFT": "1", "HTPD_DRAFT_K": "8", "HTPD_SPEC": "0", "HTPD_LEGACY_PREFILL": "1", "HTPD_PREFIX_CACHE": "1"}
    res = {}
    log = open(os.path.join(a.out, "htpd_host.log"), "ab")

    def run(name, binary, env, reqs):
        log.write(f"\n===== {name} {binary} {env}\n".encode()); log.flush()
        p = start(binary, a.model, a.port, env, log)
        try:
            out = {}
            for rn, req in reqs:
                t0 = time.time()
                out[rn] = {"lines": call(a.port, req), "wall_s": time.time() - t0}
                fin = out[rn]["lines"][-1][1]
                print(name, rn, f"{out[rn]['wall_s']:.1f}s", [(o.get("stop"), o.get("tokens")) for o in fin.get("outputs", [])], flush=True)
            res[name] = out
        finally:
            p.terminate(); p.wait()

    agents = {"kind": "agents", "prompts": prompts}
    run("v6", a.v6, base_env, [("plain", agents), ("synth", {"kind": "synth", "prompt": synth})])
    run("v7_off", a.v7, base_env, [("plain", agents), ("stream", dict(agents, stream=True)),
                                   ("synth", {"kind": "synth", "prompt": synth}),
                                   ("synth_stream", {"kind": "synth", "prompt": synth, "stream": True})])
    texts6 = [o["text"] for o in res["v6"]["plain"]["lines"][-1][1]["outputs"]]
    on_env = dict(base_env, HTPD_AGENT_MAX_NEW="160", HTPD_JSON_ABORT="1", HTPD_PATTERN_TRIE="2",
                  HTPD_ROLE_DRAFT="1", HTPD_LOGITS_READ="1")
    # draft corpus = the v6 outputs of the OTHER prompt (verified drafts: must not change anything)
    run("v7_on", a.v7, on_env, [("plain", dict(agents, draft=[texts6[1], texts6[0]], logprobs=True, id="r1")),
                                ("stream", dict(agents, stream=True)),
                                ("force", dict(agents, labels=[["spike", "dip"], {"pattern": ["oscillation"], "status": ["critical"]}]))])
    run("v7_cap", a.v7, dict(base_env, HTPD_AGENT_MAX_NEW="10"), [("plain", agents)])
    json.dump(res, open(os.path.join(a.out, "results.json"), "w"), indent=1)

    # ---- checks
    fin = lambda n, r: res[n][r]["lines"][-1][1]
    T = lambda n, r: [(o["text"], o["stop"]) for o in fin(n, r)["outputs"]]
    checks = {}
    checks["v7 flags off == v6 (agents)"] = T("v7_off", "plain") == T("v6", "plain")
    checks["v7 flags off == v6 (synth)"] = T("v7_off", "synth") == T("v6", "synth")
    checks["stream: final line unchanged"] = T("v7_off", "stream") == T("v6", "plain")
    checks["synth stream: final line unchanged"] = T("v7_off", "synth_stream") == T("v6", "synth")

    def streamed(n, r, k):
        got = [""] * k
        nl = 0
        for _, d in res[n][r]["lines"][:-1]:
            assert d["kind"] == "toks"
            nl += 1
            for i, t in enumerate(d["t"]):
                got[i] += t
        return got, nl

    for n, r, k in (("v7_off", "stream", 2), ("v7_off", "synth_stream", 1), ("v7_on", "stream", 2)):
        got, nl = streamed(n, r, k)
        raw_ok = True
        for i, o in enumerate(fin(n, r)["outputs"]):
            txt = o["text"]
            if o["stop"] == "action":  # streamed pieces are raw: the trimmed text is a prefix of them up to the cut
                cut = txt[:-1]
                raw_ok &= got[i].startswith(cut) and '"action"' in got[i][len(cut):]
            else:
                raw_ok &= got[i] == txt
        checks[f"{n}/{r}: {nl} progress lines, pieces rebuild the text"] = raw_ok and nl > 0
    on = fin("v7_on", "plain")
    checks["all v7 flags on: on-label texts unchanged"] = [(o["text"], o["stop"]) for o in on["outputs"]] == T("v6", "plain")
    checks["all v7 flags on: 0 forced tokens"] = all(o.get("forced") == 0 for o in on["outputs"])
    checks["logprobs: 5 per output, sorted"] = all(len(o["logprobs"]) == 5 and o["logprobs"][0]["lp"] >= o["logprobs"][-1]["lp"] for o in on["outputs"])
    checks["id echoed"] = on.get("id") == "r1"
    fo = fin("v7_on", "force")["outputs"]
    f0 = json.loads(PRE + fo[0]["text"]) if fo[0]["stop"] in ("action", "json") else {}
    f1 = json.loads(PRE + fo[1]["text"]) if fo[1]["stop"] in ("action", "json") else {}
    checks[f"forced labels honoured ({f0.get('pattern')}, {f1.get('pattern')}/{f1.get('status')})"] = (
        f0.get("pattern") in ("spike", "dip") and f1.get("pattern") == "oscillation" and f1.get("status") == "critical")
    cap = fin("v7_cap", "plain")["outputs"]
    checks["agent cap 10: stop max at 10 tokens"] = all(o["stop"] == "max" and o["tokens"] == 10 for o in cap)
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    json.dump({"checks": checks}, open(os.path.join(a.out, "checks.json"), "w"), indent=1)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
