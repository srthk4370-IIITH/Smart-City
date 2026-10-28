"""v2 agent accuracy on the QIDK NPU (htpd, batched), on the SAME rows and with the SAME scoring as the host
eval (common_v2), so host vs device is a paired comparison (RETRAIN_V2_SPEC decision #2).

Needs the QIDK on USB and htpd v2 running:  bash htpd_v2.sh start
  py eval_htpd_v2.py --set host400 --out ..\\..\\..\\..\\..\\..\\proofs\\2026-10-20_v2_post\\device\\host400
  py eval_htpd_v2.py --set test    --out ...\\device\\test_all          # all 2,965 test rows (~2-3 h)
  py eval_htpd_v2.py --compare HOST_SAMPLES.jsonl --out DIR               # host vs device table only
host400 = the frozen eval_set.json (copied to proofs/2026-10-20_v2_post/ by post_all.sh). Resumable.
Thermal pacing as window_study.run: a batch waits while the board is >= --hot C, until --cool C.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common_v2 as C  # noqa: E402

PROOF = C.ROOT.parents[1] / "proofs" / "2026-10-20_v2_post"
ADB = str(C.ROOT.parent / "platform-tools" / "adb.exe")


def call(req, port):
    s = socket.create_connection(("127.0.0.1", port), timeout=900)
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        d = s.recv(1 << 20)
        if not d:
            break
        buf += d
    s.close()
    return json.loads(buf.decode("utf-8", errors="replace"))


def board_c():
    try:
        r = subprocess.run([ADB, "shell", "cat /sys/class/thermal/thermal_zone*/temp"], capture_output=True, text=True, timeout=30)
        v = [int(x) for x in r.stdout.split() if x.lstrip("-").isdigit()]
        return max(v) // 1000 if v else -1
    except Exception:  # noqa: BLE001
        return -1


def pace(hot, cool):
    """Thermal pacing before a batch. An unreadable temperature (-1: adb timed out under load) counts as HOT:
    on 2026-10-23 the read failed from batch 23 on, the run never paused, and every garbage answer of that run
    came from those unpaced batches (proofs/2026-10-23_3d_quant_fix/RESULTS.md)."""
    c = board_c()
    for _ in range(3):
        if c >= 0:
            break
        time.sleep(5)
        c = board_c()
    if c < 0:
        print("board temperature unreadable: fixed 120 s cool-down", flush=True)
        time.sleep(120)
        return board_c()
    if c >= hot:
        print(f"board {c} C, cooling to {cool} C ...", flush=True)
        t0 = time.time()
        while True:
            c = board_c()
            if 0 <= c <= cool or time.time() - t0 > 900:
                break
            time.sleep(10)
    return c


def compare(host_samples, dev_samples, out):
    h = {s["id"]: s for s in map(json.loads, open(host_samples, encoding="utf-8"))}
    d = {s["id"]: s for s in map(json.loads, open(dev_samples, encoding="utf-8"))}
    ids = [i for i in h if i in d]
    res = {"n_paired": len(ids), "host": str(host_samples)}
    lines = [f"# Host vs QIDK NPU (paired, n = {len(ids)})", "", "| metric | n | host | device | delta (pts) | McNemar p |",
             "|---|---|---|---|---|---|"]
    for k in C.METRICS:
        pr = [(h[i][k], d[i][k]) for i in ids if h[i].get(k) is not None and d[i].get(k) is not None]
        if not pr:
            continue
        ra, rb = sum(x for x, _ in pr) / len(pr), sum(y for _, y in pr) / len(pr)
        mc = C.mcnemar([x for x, _ in pr], [y for _, y in pr])
        res[k] = {"host": round(ra, 3), "device": round(rb, 3), "n": len(pr), "mcnemar": mc}
        lines.append(f"| {k} | {len(pr)} | {100 * ra:.1f} | {100 * rb:.1f} | {100 * (rb - ra):+.1f} | {mc['p']} |")
    same = sum(1 for i in ids if h[i].get("pred") and d[i].get("pred") and all(
        h[i]["pred"][k] == d[i]["pred"][k] for k in ("pattern", "status", "likely_cause")))
    res["same_pattern_status_cause"] = round(same / max(1, len(ids)), 3)
    lines.append(f"\nsame (pattern, status, cause) on host and device: {100 * res['same_pattern_status_cause']:.1f}%")
    (out / "host_vs_device.json").write_text(json.dumps(res, indent=1))
    (out / "host_vs_device.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["host400", "test"], default="host400")
    ap.add_argument("--eval-set", default=str(PROOF / "eval_set.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=8, help="must be <= htpd --agents")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--hot", type=int, default=80)
    ap.add_argument("--cool", type=int, default=70)
    ap.add_argument("--compare", default=None, help="host samples.jsonl (default: proofs .../eval/gguf_q4_0)")
    ap.add_argument("--compare-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sp = out / "samples.jsonl"
    host = Path(a.compare) if a.compare else PROOF / "eval" / "gguf_q4_0" / "samples.jsonl"
    if not a.compare_only:
        rows = C.read_jsonl(C.DATA / "test.jsonl")
        if a.set == "host400":
            ids = json.loads(Path(a.eval_set).read_text())["ids"]
            by = {r["id"]: r for r in rows}
            rows = [by[i] for i in ids]
        done = {json.loads(l)["id"] for l in open(sp, encoding="utf-8")} if sp.exists() else set()
        todo = [r for r in rows if r["id"] not in done]
        # same role per batch: the prefix cache (system prompt per role) then serves the whole batch
        todo.sort(key=lambda r: (r["role"], r.get("n") or 48))
        print(f"{len(todo)} of {len(rows)} rows to run, batch {a.batch}", flush=True)
        t_all = time.time()
        with open(sp, "a", encoding="utf-8") as fh:
            for b0 in range(0, len(todo), a.batch):
                chunk = todo[b0:b0 + a.batch]
                c = pace(a.hot, a.cool)
                t0 = time.time()
                r = call({"kind": "agents", "prompts": [x["prompt"] + C.PREFILL for x in chunk]}, a.port)
                dt = time.time() - t0
                for x, o in zip(chunk, r["outputs"]):
                    s = C.score_one(x, C.PREFILL + o["text"])
                    s.update(text=C.PREFILL + o["text"], stop=o.get("stop"), tokens=o.get("tokens"), batch_s=round(dt, 2),
                             batch_size=len(chunk), prefill_ms=r.get("prefill_ms"), board_c_before=c)
                    fh.write(json.dumps(s, default=str) + "\n")
                fh.flush()
                print(f"[{min(b0 + a.batch, len(todo))}/{len(todo)}] {chunk[0]['role']} x{len(chunk)} {dt:.1f}s", flush=True)
        scored = [json.loads(l) for l in open(sp, encoding="utf-8")]
        agg = C.aggregate(scored)
        summ = {"set": a.set, "n": len(scored), "metrics": agg, "wall_s_this_run": round(time.time() - t_all, 1),
                "mean_batch_s": round(sum(s["batch_s"] for s in scored) / max(1, len(scored)), 2),
                "stops": {k: sum(1 for s in scored if s.get("stop") == k) for k in ("action", "json", "eog", "max", "ctx")}}
        (out / "summary.json").write_text(json.dumps(summ, indent=1))
        (out / "tables.md").write_text("# QIDK NPU (htpd) v2 eval\n\n" + C.table_md(a.set, agg, C.headline_keys(agg)), encoding="utf-8")
        print(C.table_md(a.set, agg, C.headline_keys(agg)))
    if host.exists() and sp.exists():
        compare(host, sp, out)


if __name__ == "__main__":
    main()
