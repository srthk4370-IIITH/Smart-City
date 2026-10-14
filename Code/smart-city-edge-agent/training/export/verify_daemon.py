"""Prove genied (the persistent Genie dialog daemon) answers exactly as the per-call CLI does.

genied keeps ONE GenieDialog alive and calls GenieDialog_reset between queries, instead of loading
the model per request. That removes ~600-700 ms of init per call - but it is only safe if reset is
a perfect state wipe. If any KV, position counter or sampler state leaked from one query into the
next, answers would quietly drift. This script is the gate for that.

Method:
  1. With genied STOPPED, run each prompt through genie-t2t-run (the trusted per-call path) and
     record the answer. The daemon must not be running here: two loaded contexts at once is the
     configuration that previously crashed the board (RAM) and hit the DSP SMMU limit.
  2. Start genied, then send the SAME prompts over its socket twice - forward order, then reverse.
     Reverse order means every prompt follows a different predecessor than the first time, so any
     state bleed through reset shows up as a mismatch.

Every daemon answer must equal the CLI answer byte-for-byte.

  # 1. collect reference answers (genied must be stopped)
  python verify_daemon.py collect -n 14
  # 2. start genied on the device, forward its port, then
  adb forward tcp:8777 tcp:8777
  python verify_daemon.py check
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_bundles as cb  # noqa: E402  (reuses its adb plumbing and prompt selection)

REF = HERE / "_daemon_ref.json"
PREFILL = cb.PREFILL
BOS = "<|begin_of_text|>"


def pick_prompts(n):
    rows = [json.loads(l) for l in open(cb.ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    seen, pick = set(), []
    for r in rows:
        k = (r["role"], r["pattern"])
        if k not in seen:
            seen.add(k)
            pick.append(r)
        if len(pick) >= n:
            break
    return pick


def daemon_query(prompt, host="127.0.0.1", port=8777, timeout=180):
    """Send one prompt to genied and return the full generated text (no early abort)."""
    body = prompt[len(BOS):] if prompt.startswith(BOS) else prompt
    data = body.encode("utf-8")
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(struct.pack(">I", len(data)) + data)
        out, t0 = [], time.time()
        while True:
            hdr = _recv_exact(s, 5)
            if hdr is None:
                break
            kind, n = hdr[0], struct.unpack(">I", hdr[1:])[0]
            payload = _recv_exact(s, n) if n else b""
            if kind == 0:
                out.append(payload.decode("utf-8", "replace"))
            elif kind == 1:
                break
            elif kind == 2:
                raise RuntimeError("daemon error: " + payload.decode("utf-8", "replace"))
        return "".join(out), time.time() - t0


def _recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            return None if not buf else buf
        buf += chunk
    return buf


def norm(text):
    """Both paths return the continuation after the prefill; compare it trimmed and without the
    CLI's [END] marker."""
    t = text.strip()
    i = t.find("[END]")
    return (t[:i] if i >= 0 else t).strip()


def collect(n):
    out = []
    for k, r in enumerate(pick_prompts(n), 1):
        prompt = r["prompt"] + PREFILL
        text, m = cb.run("/data/local/tmp/genie_bundle_ft", prompt)
        cont = text[len(PREFILL):] if text.startswith(PREFILL) else text
        out.append({"role": r["role"], "pattern": r["pattern"], "prompt": prompt, "cli": norm(cont),
                    "cli_ms": m["init_ms"] + m["ttft_ms"] + m["decode_ms"]})
        print(f"[{k}/{n}] {r['role']:11} {r['pattern']:22} CLI {out[-1]['cli_ms']} ms", flush=True)
    REF.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved {len(out)} reference answers to {REF.name}")


def check():
    ref = json.loads(REF.read_text(encoding="utf-8"))
    order = list(range(len(ref))) + list(reversed(range(len(ref))))   # forward, then reverse
    same, total, ms = 0, 0, []
    for pass_no, i in enumerate(order):
        r = ref[i]
        text, dt = daemon_query(r["prompt"])
        got = norm(text)
        ok = got == r["cli"]
        same += ok
        total += 1
        ms.append(dt * 1000)
        tag = "fwd" if pass_no < len(ref) else "rev"
        print(f"[{tag} {i + 1:2}] {r['role']:11} {r['pattern']:22} identical={ok} daemon {dt * 1000:.0f} ms "
              f"(CLI {r['cli_ms']} ms)", flush=True)
        if not ok:
            print("   CLI   :", r["cli"][:180])
            print("   daemon:", got[:180])
    cli_avg = sum(r["cli_ms"] for r in ref) / len(ref)
    print(f"\nidentical: {same}/{total}  (each prompt checked twice, forward then reverse order)")
    print(f"mean per call: CLI {cli_avg:.0f} ms  ->  daemon {sum(ms) / len(ms):.0f} ms")
    if same != total:
        print("\nMISMATCH - do not use genied")
        sys.exit(1)


def batch(width):
    """Continuous-batching gate: send `width` prompts to genied AT THE SAME TIME (it must be running
    with -slots >= width) and require every answer to still equal the CLI's. Then compare the wall
    time of each concurrent group against the same prompts sent one after another."""
    import concurrent.futures as cf

    ref = json.loads(REF.read_text(encoding="utf-8"))
    groups = [ref[i:i + width] for i in range(0, len(ref) - width + 1, width)]
    same = total = 0
    t_seq = t_par = 0.0
    for g in groups:
        t0 = time.time()
        for r in g:
            daemon_query(r["prompt"])
        t_seq += time.time() - t0

        t0 = time.time()
        with cf.ThreadPoolExecutor(len(g)) as ex:
            outs = list(ex.map(lambda r: daemon_query(r["prompt"])[0], g))
        dt = time.time() - t0
        t_par += dt
        ok = [norm(o) == r["cli"] for o, r in zip(outs, g)]
        same += sum(ok)
        total += len(ok)
        print(f"group of {len(g)}: {dt * 1000:.0f} ms concurrent, identical {sum(ok)}/{len(ok)} "
              f"({', '.join(r['pattern'] for r in g)})", flush=True)
        for o, r, k in zip(outs, g, ok):
            if not k:
                print(f"   {r['pattern']}: CLI    {r['cli'][:150]}")
                print(f"   {r['pattern']}: batch  {norm(o)[:150]}")
    print(f"\nidentical: {same}/{total}")
    print(f"same prompts: one-at-a-time {t_seq:.1f} s  ->  concurrent {t_par:.1f} s  "
          f"({(1 - t_par / t_seq) * 100:.0f}% less)")
    if same != total:
        print("\nMISMATCH - batching changes answers")
        sys.exit(1)


LARGE = "/data/local/tmp/genie_bundle_ft_4096"
REF_LARGE = HERE / "_daemon_ref_large.json"


def daemon_query_large(prompt, host="127.0.0.1", port=8777, timeout=300):
    """Like daemon_query, but sets bit 31 of the length: genied swaps in the large-context bundle."""
    body = prompt[len(BOS):] if prompt.startswith(BOS) else prompt
    data = body.encode("utf-8")
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(struct.pack(">I", len(data) | (1 << 31)) + data)
        out, t0 = [], time.time()
        while True:
            hdr = _recv_exact(s, 5)
            if hdr is None:
                break
            kind, n = hdr[0], struct.unpack(">I", hdr[1:])[0]
            payload = _recv_exact(s, n) if n else b""
            if kind == 0:
                out.append(payload.decode("utf-8", "replace"))
            elif kind == 1:
                break
            elif kind == 2:
                raise RuntimeError("daemon error: " + payload.decode("utf-8", "replace"))
        return "".join(out), time.time() - t0


def collect_large(prompt_file):
    """Reference answer for a LARGE prompt from the CLI on the ctx-4096 bundle (genied stopped)."""
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    text, m = cb.run(LARGE, prompt)
    cont = text[len(cb.PREFILL):] if text.startswith(cb.PREFILL) else text
    REF_LARGE.write_text(json.dumps({"prompt": prompt, "cli": norm(cont), "prompt_tok": m["prompt_tok"],
                                     "cli_ms": m["init_ms"] + m["ttft_ms"] + m["decode_ms"]}), encoding="utf-8")
    print(f"large reference: {m['prompt_tok']} prompt tokens, CLI {m['init_ms'] + m['ttft_ms'] + m['decode_ms']} ms")


def windows():
    """Gate for context-window switching: small prompts on the normal window, a large prompt on the
    large window, and back - every answer identical to the CLI on the matching bundle."""
    small = json.loads(REF.read_text(encoding="utf-8"))[:3]
    large = json.loads(REF_LARGE.read_text(encoding="utf-8"))
    seq = [("normal", small[0]), ("large", large), ("normal", small[1]), ("large", large), ("normal", small[2])]
    same = 0
    for kind, r in seq:
        text, dt = daemon_query_large(r["prompt"]) if kind == "large" else daemon_query(r["prompt"])
        ok = norm(text) == r["cli"]
        same += ok
        print(f"  {kind:6} window  identical={ok}  {dt * 1000:.0f} ms (includes any swap)")
        if not ok:
            print("     CLI   :", r["cli"][:160])
            print("     daemon:", norm(text)[:160])
    print(f"\nidentical: {same}/{len(seq)}")
    if same != len(seq):
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("collect-large", "windows"):
        collect_large(sys.argv[2]) if sys.argv[1] == "collect-large" else windows()
        sys.exit(0)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("-n", type=int, default=14)
    sub.add_parser("check")
    b = sub.add_parser("batch")
    b.add_argument("-w", type=int, default=3)
    a = ap.parse_args()
    {"collect": lambda: collect(a.n), "check": check, "batch": lambda: batch(a.w)}[a.cmd]()
