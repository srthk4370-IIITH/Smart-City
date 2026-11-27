#!/usr/bin/env python3
"""htpd-protocol shim for the early-AI gate study (2026-11-12). Speaks htpd's one-line JSON TCP protocol
(app/backend/htpdclient.go) and answers kind "agents" / "synth" with a host llama-server (/completion, greedy).
Agent answers follow htpd's stop rules (htpd.cpp header): stop when the JSON object opened by the prefill closes
("json"), or where the top-level "action" key starts, the text then being closed with '}' ("action").
v5 rerun (2026-11-27): HTPD_AGENT_MAX_NEW env (default 240 = board profile), Llama 3.2 prefill marker as htpd v9h.  usage: htpd_shim.py PORT AGENT_URL"""
import json, os, socketserver, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

PORT, URL = int(sys.argv[1]), sys.argv[2].rstrip("/")
AGENT_MAX_NEW, SYNTH_MAX_NEW = int(os.environ.get("HTPD_AGENT_MAX_NEW", "240")), 700  # board profile 2026-11-27: 240
POOL = ThreadPoolExecutor(8)


def scan(prefill, gen, trim_action):
    """Cut gen per htpd's rule; prefill is the assistant text already in the prompt (e.g. '{"pattern": "')."""
    depth, ins, esc = 0, False, False
    for ch in prefill:
        if esc: esc = False
        elif ins:
            if ch == "\\": esc = True
            elif ch == '"': ins = False
        elif ch == '"': ins = True
        elif ch in "{[": depth += 1
        elif ch in "}]": depth -= 1
    for i, ch in enumerate(gen):
        if esc: esc = False; continue
        if ins:
            if ch == "\\": esc = True
            elif ch == '"': ins = False
            continue
        if ch == '"':
            if trim_action and depth == 1 and gen.startswith('"action"', i):
                head = gen[:i].rstrip()
                if head.endswith(","): head = head[:-1]
                return head + "}", "action"
            ins = True
        elif ch in "{[": depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return gen[:i + 1], "json"
    return gen, "max"


def prefill_of(p):  # htpd v9h: text after the last "<|end_header_id|>\n\n" (Llama 3.2 agt3); ChatML fallback
    m = "<|end_header_id|>\n\n" if "<|end_header_id|>" in p else "<|im_start|>assistant\n"
    i = p.rfind(m)
    return p[i + len(m):] if i >= 0 else ""


def complete(prompt, n, trim):
    t0 = time.time()
    body = json.dumps({"prompt": prompt, "n_predict": n, "temperature": 0, "top_k": 1, "cache_prompt": True}).encode()
    req = urllib.request.Request(URL + "/completion", body, {"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    text, stop = scan(prefill_of(prompt), r.get("content", ""), trim)
    tm = r.get("timings", {})
    ms = (time.time() - t0) * 1000
    return {"text": text, "tokens": tm.get("predicted_n", 0), "ttft_ms": tm.get("prompt_ms", 0.0), "ms": ms,
            "stop": stop if stop != "max" else ("eog" if r.get("stopped_eos") else "max")}


class H(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        if not line:
            return
        t0 = time.time()
        try:
            q = json.loads(line)
            kind = q.get("kind")
            if kind == "agents":
                outs = list(POOL.map(lambda p: complete(p, AGENT_MAX_NEW, True), q["prompts"]))
            elif kind == "synth":
                outs = [complete(q["prompt"], SYNTH_MAX_NEW, False)]
            else:
                raise ValueError("shim: unsupported kind %r" % kind)
            resp = {"outputs": outs, "prefill_ms": 0.0, "total_ms": (time.time() - t0) * 1000}
        except Exception as ex:  # noqa: BLE001
            resp = {"outputs": [], "error": str(ex)}
        self.wfile.write((json.dumps(resp) + "\n").encode())


class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


S(("127.0.0.1", PORT), H).serve_forever()
