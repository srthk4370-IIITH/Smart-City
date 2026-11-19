"""CPU stand-in for llama-server /completion (dry run of chat_r3_eval.py without a GPU): finds the record by its last user
question in the rendered prompt and answers like a perfect model: gold calls of the current round (Qwen XML tool-call
format), then the reference answer; an empty think when the prompt opens <think>. A pass rate near the build's own
verify rate shows the r3 header render, executors and verifier are wired right.
  python3 mock_server.py <port> <records.jsonl> [<records2.jsonl> ...]"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
RECS = {}
for p in sys.argv[2:]:
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        lu = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
        RECS.setdefault(r["messages"][lu]["content"].strip(), r)


def call_text(c):
    ps = "".join("<parameter=%s>\n%s\n</parameter>\n" % (k, v if isinstance(v, str) else json.dumps(v)) for k, v in (c["args"] or {}).items())
    return "<tool_call>\n<function=%s>\n%s</function>\n</tool_call>" % (c["name"], ps)


def answer(prompt):
    if prompt.endswith("<think>\n"):
        return ""
    turns = prompt.split("<|im_start|>user\n")
    qi = max(i for i, t in enumerate(turns) if not t.startswith("<tool_response>"))
    q = turns[qi].split("<|im_end|>")[0].strip()
    r = RECS.get(q)
    if r is None:
        return "I cannot answer that."
    rnd = "".join(turns[qi:]).count("<tool_call>")
    gold = [c for c in r.get("gold_calls") or [] if c.get("round", 0) == rnd]
    if gold and rnd < 4:
        return "\n".join(call_text(c) for c in gold)
    return r["reference_answer"]


class Hd(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        t = answer(b["prompt"])
        o = json.dumps({"content": t, "tokens_predicted": len(t) // 4, "stop_type": "eos"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(o)


HTTPServer(("127.0.0.1", PORT), Hd).serve_forever()
