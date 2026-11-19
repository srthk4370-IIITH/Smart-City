"""Incident runner of the rsn_ft strict gate (llama-server --jinja, greedy), = 2026-11-12_topup_r4/train/post/run_think.py plus a
v4 mode and explicit output dirs (nothing is written into the round-1 eval/results or p0/results trees).
--think 1 = app reasoner_think=adaptive (enable_thinking=true; the model reasons or closes the block at once); the reasoning is
moved out of the content before scoring and kept per item in "think" (every turn, tool turns included). --think 0 = round-1 runner.
  r3 prompts (prompts.SYSTEM_INCIDENT_SHORT + tools_v3 "incident", RowExec), as gate_r3 / gate_r4:
    python3 run_ft.py --think 1 --tag T --port P --resdir D v3 --suites rwh,dev,rw6,p0 [--p0-root R]
    python3 run_ft.py --think 1 --tag T --port P --resdir D suite --name rwh2 --file F
  v4 prompts (the row's own system + tools_v4.json[row "tools"], RowExec on the row):
    python3 run_ft.py --think 1 --tag T --port P --resdir D v4 --name test_taxonomy --file F --tools tools_v4.json
Output: D/<tag>/<name>.jsonl (resumable). P0: <p0-root>/results/<tag>/*.jsonl (default D/p0)."""
import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
QIDK = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
R1 = os.path.join(QIDK, "proofs", "2026-10-25_reasoner_final")
R1E = os.path.join(R1, "eval")
sys.path[:0] = [R1E, os.path.join(R1E, "p0")]

ap = argparse.ArgumentParser()
ap.add_argument("--think", type=int, choices=(0, 1), required=True)
ap.add_argument("--tag", required=True)
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--resdir", required=True)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--max-tokens", type=int, default=0, help="0 = 1200 (r3 runners) / 1500 (v4)")
sub = ap.add_subparsers(dest="mode", required=True)
s1 = sub.add_parser("v3")
s1.add_argument("--suites", required=True)
s1.add_argument("--p0-root", default="")
s2 = sub.add_parser("suite")
s2.add_argument("--name", required=True)
s2.add_argument("--file", required=True)
s3 = sub.add_parser("v4")
s3.add_argument("--name", required=True)
s3.add_argument("--file", required=True)
s3.add_argument("--tools", required=True)
A = ap.parse_args()
THINK = bool(A.think)
THINKS = []

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
    if (msg.get("reasoning_content") or "").strip():
        THINKS.append(msg["reasoning_content"].strip())
    return msg, tim, dt


RB.Client.chat = chat
import run_v3 as RV  # noqa: E402

if os.environ.get("FT_NO_COOL") == "1":      # dry run: no nvidia-smi, no 2 s gap
    RV.gpu_cool = lambda: None


def out_path(name):
    d = os.path.join(A.resdir, A.tag)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name + ".jsonl")


def rows_of(path):
    rows = RV.load(path)
    for r in rows:
        r.setdefault("family", r.get("slice") or r.get("family") or "")
    return rows


def run_v4(cli, rows, out, tools, limit, max_tokens):
    if limit:      # dry runs / spot checks: round-robin over reasoning types so every type is hit
        g = {}
        for r in rows:
            g.setdefault(r.get("reasoning_type") or "none", []).append(r)
        rows = [x for t in zip(*[v + [None] * (max(map(len, g.values())) - len(v)) for v in g.values()]) for x in t if x]
    done = RV.done_ids(out)
    n = 0
    for r in rows:
        if r["id"] in done:
            continue
        if limit and n >= limit:
            break
        RV.gpu_cool()
        del THINKS[:]
        ex = RV.RowExec(r)
        t0 = time.time()
        res = RB.run_loop(cli, ex, r["messages"][0]["content"], [{"role": "user", "content": r["messages"][1]["content"]}],
                          tools[r.get("tools") or "incident_v4"], max_tokens=max_tokens)
        rec = {"id": r["id"], "family": r.get("family"), "wall_s": round(time.time() - t0, 2), "calls": res["calls"], "final": res["final"],
               "turns": res["turns"], "think": "\n".join(THINKS), "think_mode": A.think}
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        n += 1
    return n


def main():
    cli = RB.Client(A.port, A.max_tokens or 1200)
    t0 = time.time()
    if A.mode == "v3":
        D = os.path.join(R1, "data")
        for s in A.suites.split(","):
            t1 = time.time()
            if s == "p0":
                root = A.p0_root or os.path.join(A.resdir, "p0")
                os.makedirs(os.path.join(root, "results"), exist_ok=True)
                RB.HERE = root                       # run_bench writes HERE/results/<model>
                RV.run_p0(A.tag, A.port, A.limit, "v3")
                n = -1
            else:
                src = {"rw6": ("rw6.jsonl", 0), "rwh": ("incidents_rwh.ok.jsonl", 0), "dev": ("incidents_dev.ok.jsonl", 120)}[s]
                rows = RV.load(os.path.join(D, src[0]))
                rows = rows[:src[1]] if src[1] else rows
                n = RV.run_items(cli, rows, out_path(s), A.limit)
            print("%s %s: %d items in %.0f s (think %d)" % (A.tag, s, n, time.time() - t1, A.think), flush=True)
    elif A.mode == "suite":
        n = RV.run_items(cli, rows_of(A.file), out_path(A.name), A.limit)
        print("%s %s: %d items in %.0f s (think %d)" % (A.tag, A.name, n, time.time() - t0, A.think))
    else:
        tools = json.load(open(A.tools, encoding="utf-8"))
        n = run_v4(cli, rows_of(A.file), out_path(A.name), tools, A.limit, A.max_tokens or 1500)
        print("%s v4 %s: %d items in %.0f s (think %d)" % (A.tag, A.name, n, time.time() - t0, A.think))


if __name__ == "__main__":
    main()
