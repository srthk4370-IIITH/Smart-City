"""Round-1 incident runner (eval/run_v3.py, the gate's runner for RWH / dev / RWH-2) with the think mode of the model under test.
--think 1 (r4, = app reasoner_think=adaptive): chat_template_kwargs.enable_thinking=true, so the prompt opens a think block
and the model reasons (multi-domain) or closes it at once; the reasoning is moved out of the content (reasoning_content)
before scoring, as the app strips it (splitReportThink). --think 0 = the unchanged round-1 runner (thinking off).
  python3 run_think.py --think 1 v3 --tag T --port P --suites rwh,dev
  python3 run_think.py --think 1 suite --tag T --port P --suite test_r4 --file F   (rows without "family" get the slice)"""
import json
import os
import sys
import urllib.request

R1E = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "2026-10-25_reasoner_final", "eval"))
sys.path[:0] = [R1E, os.path.join(R1E, "p0")]
assert sys.argv[1] == "--think" and sys.argv[2] in ("0", "1") and sys.argv[3] in ("v3", "suite"), __doc__
THINK, MODE = sys.argv[2] == "1", sys.argv[3]
import run_bench as RB  # noqa: E402

_Req = urllib.request.Request


def _req(url, data=None, *a, **k):
    if data and ("/v1/chat/completions" in url or url.endswith("/apply-template")):
        d = json.loads(data)
        d.setdefault("chat_template_kwargs", {})["enable_thinking"] = THINK
        data = json.dumps(d).encode()
    return _Req(url, data, *a, **k)


urllib.request.Request = _req
_chat = RB.Client.chat


def _split(c):
    i = c.find("</think>")
    if i < 0:
        return "", c
    th = c[:i].strip()
    return (th[len("<think>"):].strip() if th.startswith("<think>") else th), c[i + len("</think>"):].lstrip()


def chat(self, *a, **k):
    msg, tim, dt = _chat(self, *a, **k)
    c = msg.get("content") or ""
    if THINK and "</think>" in c and not msg.get("tool_calls"):
        th, rest = _split(c)
        msg = dict(msg, content=rest, reasoning_content=((msg.get("reasoning_content") or "") + th).strip())
    return msg, tim, dt


RB.Client.chat = chat
import run_v3 as RV  # noqa: E402

if MODE == "v3":
    sys.argv = ["run_v3.py"] + sys.argv[4:]
    RV.main()
else:
    import argparse
    ap = argparse.ArgumentParser()
    for f in ("--tag", "--suite", "--file"):
        ap.add_argument(f, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(sys.argv[4:])
    rows = RV.load(a.file)
    for r in rows:
        r.setdefault("family", r.get("slice") or "")
    od = os.path.join(R1E, "results", a.tag)
    os.makedirs(od, exist_ok=True)
    n = RV.run_items(RB.Client(a.port, 1200), rows, os.path.join(od, a.suite + ".jsonl"), a.limit)
    print("%s %s: %d items (think %d)" % (a.tag, a.suite, n, THINK))
