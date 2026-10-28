#!/usr/bin/env python3
"""Host check of the later v7 additions (agent layouts, role-draft file, JSON_ABORT=2) against the v6
results of host_e2e.py.

usage (WSL): python3 host_e2e_layouts.py --v7 BIN --model GGUF --prompts prompts.jsonl --base e2e/results.json
             --role-draft role_draft_v2.jsonl --out DIR
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from host_e2e import call, PRE  # noqa: E402
import socket, subprocess  # noqa: E402


def start(binary, model, port, env_extra, extra, log):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HTPD_")}
    env.update(env_extra)
    p = subprocess.Popen([binary, "-m", model, "--device", "CPU", "--port", str(port), "--agents", "2",
                          "--agent-ctx", "1280", "--synth-ctx", "1536", "-t", "2", "--ubatch", "512",
                          "--ubatch-synth", "512"] + extra, env=env, stdout=log, stderr=log)
    for _ in range(600):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return p
        except OSError:
            time.sleep(1)
    raise RuntimeError("htpd did not come up")


def main():
    ap = argparse.ArgumentParser()
    for k in ("v7", "model", "prompts", "base", "role_draft", "out"):
        ap.add_argument("--" + k.replace("_", "-"), dest=k)
    ap.add_argument("--port", type=int, default=8292)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base = json.load(open(a.base))
    v6 = [(o["text"], o["stop"]) for o in base["v6"]["plain"]["lines"][-1][1]["outputs"]]
    rows = [json.loads(l) for l in open(a.prompts)]
    prompts = [r["prompt"] + PRE for r in rows[:2]]
    agents = {"kind": "agents", "prompts": prompts}
    synth = {"kind": "synth", "prompt": rows[2]["prompt"]}
    v6s = [(o["text"], o["stop"]) for o in base["v6"]["synth"]["lines"][-1][1]["outputs"]]
    env = {"HTPD_DRAFT": "1", "HTPD_DRAFT_K": "8", "HTPD_SPEC": "0", "HTPD_LEGACY_PREFILL": "1", "HTPD_PREFIX_CACHE": "1"}
    log = open(os.path.join(a.out, "htpd_host.log"), "ab")
    res, checks = {}, {}

    def run(name, env_x, extra, reqs):
        log.write(f"\n===== {name} {env_x} {extra}\n".encode()); log.flush()
        p = start(a.v7, a.model, a.port, dict(env, **env_x), extra, log)
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

    # 1 stream per layout: a 2-prompt request must be split into 2 sub-batches and merged in order
    run("layouts_split", {}, ["--agent-layouts", "1x1280,1x1536"], [("stream", dict(agents, stream=True, id=5))])
    # first layout too small for 2 prompts, second fits both: one batch after a context swap
    run("layouts_swap", {}, ["--agent-layouts", "1x1280,2x1280"], [("plain", agents)])
    # role-draft file + strict abort + trie from the prompt + cap: on-label outputs must not change
    run("file_draft", {"HTPD_ROLE_DRAFT": "1", "HTPD_ROLE_DRAFT_FILE": a.role_draft, "HTPD_JSON_ABORT": "2",
                       "HTPD_PATTERN_TRIE": "2", "HTPD_AGENT_MAX_NEW": "160", "HTPD_LOGITS_READ": "1",
                       "HTPD_SYNTH_PREFIX_CACHE": "1"}, [],
        [("plain", agents), ("synth1", synth), ("synth2", synth)])
    run("cap", {"HTPD_AGENT_MAX_NEW": "10"}, [], [("plain", agents)])
    json.dump(res, open(os.path.join(a.out, "results_layouts.json"), "w"), indent=1)

    fin = res["layouts_split"]["stream"]["lines"][-1][1]
    got = [""] * 2
    for _, d in res["layouts_split"]["stream"]["lines"][:-1]:
        for i, t in enumerate(d["t"]):
            got[i] += t
    split = [(o["text"], o["stop"]) for o in fin["outputs"]]
    checks[f"split request: outputs in request order, {sum(x == y for x, y in zip(split, v6))}/2 identical to v6 batch"] = \
        all(o["stop"] in ("action", "json") for o in fin["outputs"]) and fin.get("id") == 5
    checks["split request: streamed pieces land on the request index"] = all(
        g.startswith(o["text"][:-1]) for g, o in zip(got, fin["outputs"]))
    sw = res["layouts_swap"]["plain"]["lines"][-1][1]
    checks[f"swap to a fitting layout: one batch, identical to v6 (swap_ms {sw.get('swap_ms')})"] =         [(o["text"], o["stop"]) for o in sw["outputs"]] == v6 and sw.get("swap_ms", 0) > 0
    fd = [(o["text"], o["stop"]) for o in res["file_draft"]["plain"]["lines"][-1][1]["outputs"]]
    checks["role-draft file + abort=2 + trie=2 + cap: identical to v6"] = fd == v6
    for r in ("synth1", "synth2"):
        f = res["file_draft"][r]["lines"][-1][1]
        checks[f"synth prefix cache {r} (prefill {f['prefill_ms']:.0f} ms): identical to v6 synth"] =             [(o["text"], o["stop"]) for o in f["outputs"]] == v6s
    cap = res["cap"]["plain"]["lines"][-1][1]["outputs"]
    checks["agent cap 10: stop max at exactly 10 tokens"] = all(o["stop"] == "max" and o["tokens"] == 10 for o in cap)
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    json.dump({"checks": checks}, open(os.path.join(a.out, "checks_layouts.json"), "w"), indent=1)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
