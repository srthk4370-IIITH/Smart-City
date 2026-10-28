"""Evaluate one served model (llama-server --jinja) on the reasoner suites, with the v3 prompts and compact tools.
  python3 run_v3.py --tag base_v3 --port 18095 --suites rw6,rwh,dev,chatdev,p0 [--limit N] [--p0-prompt v3|p0]
Suites: rw6 (tonight's 6 stories), rwh (held-out realistic), dev (incident dev), chatdev (chat dev),
p0 (P0 regression: 127 scenarios + 65 chat + 15 reading + consistency, run through the P0 loop into p0/results/<tag>).
Outputs: results/<tag>/<suite>.jsonl (resumable). Prints one line per suite."""
import argparse
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "p0"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import run_bench as RB  # noqa: E402
from prompts import SYSTEM_INCIDENT_SHORT as SYSTEM_INCIDENT, SYSTEM_CHAT, NET_OFF  # noqa: E402

TOOLS = json.load(open(os.path.join(ROOT, "pipeline", "tools_v3.json")))
SYS_CHAT = SYSTEM_CHAT.format(now="2026-10-22 12:00", dow="Thursday", net=NET_OFF)


class RowExec:
    """Tool executor for generated items: returns the stored tool result when the call matches the gold tool,
    else 'nothing more' (the deciding evidence is already in the prompt)."""
    def __init__(self, row):
        self.res = {}
        for m in row["messages"]:
            if m["role"] == "assistant" and m.get("tool_calls"):
                self.pending = m["tool_calls"][0]["function"]["name"]
            if m["role"] == "tool":
                self.res[self.pending] = json.loads(m["content"])
        self.calls = 0

    def run(self, name, args):
        self.calls += 1
        if name in self.res:
            return copy.deepcopy(self.res[name])
        if name == "related_context":
            return {"related": [], "note": "all causally related sensors are already in the prompt"}
        if name == "get_action_history":
            return {"items": [], "note": "no past incidents or maintenance recorded for these sensors in the last 90 days"}
        if name == "get_sensor_history":
            return {"summary": [], "note": "no stored readings beyond the incident window", "coverage": {"source": "device", "complete": False}}
        return {"items": [], "note": "no matching incidents"}


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def done_ids(p):
    return {json.loads(l)["id"] for l in open(p)} if os.path.exists(p) else set()


def gpu_cool():
    """thermal safety (owner, 2026-10-27): pause at >= 75 C until <= 65 C; 2 s gap between items"""
    import subprocess
    def t():
        try:
            return int(subprocess.check_output(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"]).decode().strip())
        except Exception:
            return 0
    if t() >= int(os.environ.get("HEAT_HI", 75)):
        t0 = time.time()
        while t() > int(os.environ.get("HEAT_LO", 65)):
            time.sleep(10)
        print("THERMAL pause %.0f s" % (time.time() - t0), flush=True)
    time.sleep(2)


def run_items(cli, rows, out, limit, chat=False):
    done = done_ids(out)
    n = 0
    for r in rows:
        gpu_cool()
        if r["id"] in done:
            continue
        if limit and n >= limit:
            break
        if chat:
            from tools_impl import Executor
            ex = Executor(path=os.path.join(ROOT, "data", "train_store.sqlite"))
            msgs = [{"role": "user", "content": r["messages"][1]["content"]}]
            t0 = time.time()
            res = RB.run_loop(cli, ex, SYS_CHAT, msgs, TOOLS["chat"], max_tokens=400)
        else:
            ex = RowExec(r)
            t0 = time.time()
            res = RB.run_loop(cli, ex, SYSTEM_INCIDENT, [{"role": "user", "content": r["messages"][1]["content"]}], TOOLS["incident"], max_tokens=1200)
        rec = {"id": r["id"], "family": r["family"], "wall_s": round(time.time() - t0, 2), "calls": res["calls"], "final": res["final"],
               "turns": res["turns"]}
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        n += 1
    return n


def run_p0(tag, port, limit, prompt):
    """the P0 loop with the v3 (or original) prompts and compact (or original) tools; results in p0/results/<tag>"""
    if prompt == "v3":
        RB.SYSTEM_INCIDENT = SYSTEM_INCIDENT
        RB.SYSTEM_CHAT = SYS_CHAT
        RB.openai_tools = _pick
    sys.argv = ["run_bench.py", "--model", tag, "--port", str(port)] + (["--limit", str(limit)] if limit else [])
    RB.main()


def _pick(names):
    seen, out = set(), []
    for t in TOOLS["chat"] + TOOLS["incident"]:
        n = t["function"]["name"]
        if n in names and n not in seen:
            seen.add(n)
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--port", type=int, default=18095)
    ap.add_argument("--suites", default="rw6,rwh,dev,chatdev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--p0-prompt", default="v3")
    a = ap.parse_args()
    od = os.path.join(HERE, "results", a.tag)
    os.makedirs(od, exist_ok=True)
    cli = RB.Client(a.port, 1200)
    D = os.path.join(ROOT, "data")
    for s in a.suites.split(","):
        t0 = time.time()
        if s == "rw6":
            n = run_items(cli, load(os.path.join(D, "rw6.jsonl")), os.path.join(od, "rw6.jsonl"), a.limit)
        elif s == "rwh":
            n = run_items(cli, load(os.path.join(D, "incidents_rwh.ok.jsonl")), os.path.join(od, "rwh.jsonl"), a.limit)
        elif s == "rwh_lim":
            n = run_items(cli, load(os.path.join(D, "incidents_rwh.ok.jsonl"))[:60], os.path.join(od, "rwh.jsonl"), a.limit)
        elif s == "dev":
            n = run_items(cli, load(os.path.join(D, "incidents_dev.ok.jsonl"))[:120], os.path.join(od, "dev.jsonl"), a.limit)
        elif s == "chatdev":
            n = run_items(cli, load(os.path.join(D, "chat_dev.ok.jsonl"))[:100], os.path.join(od, "chatdev.jsonl"), a.limit, chat=True)
        elif s == "p0":
            run_p0(a.tag, a.port, a.limit, a.p0_prompt)
            n = -1
        print("%s %s: %d items in %.0f s" % (a.tag, s, n, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
