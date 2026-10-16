"""Accuracy of the llama.cpp Hexagon path (htpd, batched) on the held-out test set, scored exactly like
validate_tuned_on_device.py scores Genie, with per-sample rows saved for proofs.

htpd must be running on the QIDK with `adb forward tcp:8091 tcp:8091`.

  python eval_htpd.py --set device54   # the 54 windows of training/results/device_eval (paired with Genie)
  python eval_htpd.py --set test900    # every window of data/sft/test.jsonl
"""
import argparse
import json
import socket
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
from validate_tuned_on_device import PREFILL, score  # noqa: E402


def call(req):
    s = socket.create_connection(("127.0.0.1", 8091), timeout=900)
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        d = s.recv(1 << 20)
        if not d:
            break
        buf += d
    s.close()
    return json.loads(buf)


def pick_device54(rows, per_role=12):
    # same selection as validate_tuned_on_device.py: first test row per (role, pattern), capped per role
    pick, seen = [], defaultdict(int)
    for r in rows:
        key = r["role"]
        if seen[key] < per_role and sum(1 for x in pick if x["pattern"] == r["pattern"] and x["role"] == key) == 0:
            pick.append(r)
            seen[key] += 1
    return pick


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["device54", "test900"], default="device54")
    ap.add_argument("--batch", type=int, default=13)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    pick = pick_device54(rows) if a.set == "device54" else rows
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    samples = open(out / "samples.jsonl", "w", encoding="utf-8")
    agg = defaultdict(list)
    t_all = time.time()
    for b0 in range(0, len(pick), a.batch):
        chunk = pick[b0:b0 + a.batch]
        t0 = time.time()
        r = call({"kind": "agents", "prompts": [x["prompt"] + PREFILL for x in chunk]})
        dt = time.time() - t0
        for x, o in zip(chunk, r["outputs"]):
            gold = json.loads(x["completion"].replace("<|eot_id|>", ""))
            s = score(x["role"], gold, PREFILL + o["text"])
            s.update(role=x["role"], gold_pattern=gold["pattern"], stop=o["stop"], tokens=o["tokens"])
            agg[x["role"]].append(s)
            samples.write(json.dumps(s, default=str) + "\n")
        print(f"[{min(b0 + a.batch, len(pick))}/{len(pick)}] batch of {len(chunk)} in {dt:.1f}s", flush=True)
    samples.close()
    allr = [s for v in agg.values() for s in v]
    keys = ("json", "pattern", "status", "likely_cause", "action_derived", "evidence", "policy")
    summary = {k: round(sum(1 for s in allr if s.get(k)) / len(allr), 3) for k in keys}
    summary["n"] = len(allr)
    summary["per_role_pattern"] = {k: round(sum(1 for s in v if s.get("pattern")) / len(v), 3) for k, v in agg.items()}
    summary["wall_s"] = round(time.time() - t_all, 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
