"""CPU stand-in for llama-server in the rsn_ft gate dry run (no GPU, no model). Serves /health, /v1/chat/completions (incident
runners, P0) and /completion (chat loops). It answers like a near-perfect model so that every runner, executor, parser and
scorer path is exercised with known results:
- incidents: finds the row by its user block; replies with the row's gold report (its reasoning_content when thinking is on);
  rows without a gold report (round-1 suites with a "gold" block, P0) get a fixed valid report; every 3rd row first makes one
  related_context tool call (tool path); every 5th row (md5 of the user text) gets a wrong severity (failure path);
- chat: finds the record by its last user question in the rendered prompt; gold calls of the current round (Qwen XML), then the
  gold final / reference answer; a short plan when a think block is open on a hard record, else an empty think; every 5th record
  answers with an invented id (failure path).
  python3 stub_server.py --port P [--model M]   (--model is only logged; candidate and base get the same answers)"""
import argparse
import glob
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

Q = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
INC_FILES = [Q + "2026-10-25_reasoner_final/data/incidents_rwh.ok.jsonl", Q + "2026-10-25_reasoner_final/data/incidents_dev.ok.jsonl",
             Q + "2026-10-25_reasoner_final/data/rw6.jsonl", Q + "2026-10-29_rsn_v3/kaggle/build/r1/heldout/incidents_rwh2.jsonl",
             Q + "2026-11-06_4b_local/data/final/incidents_test_r2.jsonl", Q + "2026-11-12_topup_r4/data/final/test_inc_r4.jsonl"] + \
    sorted(glob.glob(Q + "2026-11-13_v3_data/rsn/data/final/tests/test_*_inc.jsonl")) + \
    [Q + "2026-11-13_v3_data/rsn/data/final/tests/%s.jsonl" % n for n in ("test_unseen_metric", "test_unseen_layout", "test_taxonomy", "test_real_agent")]
CHAT_FILES = [Q + "2026-10-29_rsn_v3/data/chat3_dev.jsonl", Q + "2026-11-06_4b_local/data/final/chat_test_r3.jsonl",
              Q + "2026-11-12_topup_r4/data/final/test_chat_r4.jsonl", Q + "2026-11-13_v3_data/rsn/data/final/tests/test_fog.jsonl",
              Q + "2026-11-13_v3_data/rsn/data/final/tests/test_campus_chat.jsonl"]
FIXED = {"title": "Stub report", "severity": "warning", "label": "normal", "root_cause": "stub", "causal_chain": "S1.E1", "observations":
         [{"text": "stub", "src": ["S1.E1"]}], "agent_checks": [], "affected_domains": [], "suspect_sensors": [], "evidence": ["S1.E1"],
         "confidence": 0.5, "checklist": [{"action": "check_sensor", "target": "S1", "why": "stub"}], "monitor_next": "stub",
         "needs_more_data": False, "needs_deeper": False, "explanation": "Stub report: no data are available here."}

INC, CHAT = {}, {}
for p in INC_FILES:
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            INC.setdefault(r["messages"][1]["content"].strip(), r)
for p in CHAT_FILES:
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            lu = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
            if not r.get("gold_calls") or "round" not in r["gold_calls"][0]:      # site rows: rounds from the gold transcript
                k, gc = 0, []
                for m in r["messages"][lu + 1:]:
                    for tc in m.get("tool_calls") or []:
                        a = tc["function"]["arguments"]
                        gc.append({"round": k, "name": tc["function"]["name"], "args": json.loads(a) if isinstance(a, str) else a})
                    k += bool(m.get("tool_calls"))
                r = dict(r, gold_calls=gc, reference_answer=r["messages"][-1]["content"] if r["messages"][-1]["role"] == "assistant" else "")
            CHAT.setdefault("\n".join(m["content"].strip() for m in r["messages"][:lu + 1] if m["role"] == "user"), r)


def bad(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % 5 == 0


def call_text(c):
    ps = "".join("<parameter=%s>\n%s\n</parameter>\n" % (k, v if isinstance(v, str) else json.dumps(v)) for k, v in (c["args"] or {}).items())
    return "<tool_call>\n<function=%s>\n%s</function>\n</tool_call>" % (c["name"], ps)


def chat_answer(prompt, think_phase):
    turns = prompt.split("<|im_start|>user\n")
    qi = max(i for i, t in enumerate(turns) if not t.startswith("<tool_response>"))
    q = turns[qi].split("<|im_end|>")[0].strip()
    qs = [t.split("<|im_end|>")[0].strip() for t in turns[1:qi + 1] if not t.startswith("<tool_response>")]
    r = CHAT.get("\n".join(qs))      # key = every user question of the session (last questions repeat across records)
    rnd = "".join(turns[qi:]).count("<tool_call>")
    if think_phase:
        return "Find the unit first, then read its status." if r and r.get("hard") and rnd == 0 else ""
    if r is None:
        return "I cannot answer that: it is not available."
    gold = [c for c in r.get("gold_calls") or [] if c.get("round", 0) == rnd]
    if gold and rnd < 4:
        return "\n".join(call_text(c) for c in gold)
    ans = (r.get("gold_text") or {}).get("answer") or r.get("reference_answer") or ""
    return ans + (" See [INC-999999]." if bad(q) else "")


def incident(body):
    msgs = body["messages"]
    user = next((m["content"] for m in msgs if m["role"] == "user"), "")
    think = (body.get("chat_template_kwargs") or {}).get("enable_thinking")
    r = INC.get(user.strip())
    ntool = sum(1 for m in msgs if m["role"] == "tool")
    if body.get("tools") and ntool == 0 and int(hashlib.md5(user.encode()).hexdigest(), 16) % 3 == 0 and r is not None:
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "related_context",
                                                                                                                  "arguments": "{}"}}]}
    rc = ""
    if r is not None and r["messages"][-1]["role"] == "assistant":
        gm = r["messages"][-1]
        c = gm["content"]
        if "</think>" in c:
            th, c = c.split("</think>", 1)
            rc = th.replace("<think>", "").strip()
        rc = gm.get("reasoning_content") or rc
        try:
            rep = json.loads(c)
        except Exception:
            rep = dict(FIXED)
    else:
        rep = dict(FIXED)
    if bad(user):
        rep["severity"] = "critical" if rep.get("severity") != "critical" else "warning"
    return {"role": "assistant", "content": json.dumps(rep), "reasoning_content": rc if think else None}


def p0_or_chat(body):
    return {"role": "assistant", "content": "That information is not available in the data I can read."}


class Hd(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, o):
        b = json.dumps(o).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self.send({"status": "ok"})

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/v1/chat/completions"):
            user = next((m["content"] for m in b["messages"] if m["role"] == "user"), "")
            msg = incident(b) if user.strip() in INC or "JSON" in user else p0_or_chat(b)
            self.send({"choices": [{"message": msg, "finish_reason": "stop"}], "timings": {"prompt_n": 100, "predicted_n": 50}})
        elif self.path.startswith("/completion"):
            t = chat_answer(b["prompt"], "</think>" in (b.get("stop") or []))
            self.send({"content": t, "tokens_predicted": len(t) // 4, "stop_type": "eos"})
        else:
            self.send({"prompt": ""})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="")
    a = ap.parse_args()
    print("stub server: %d incident rows, %d chat records, model %s" % (len(INC), len(CHAT), a.model), flush=True)
    HTTPServer(("127.0.0.1", a.port), Hd).serve_forever()
