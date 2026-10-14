"""Prove that batching N prompts through one genie-app process gives the same answers as N
separate genie-t2t-run calls.

Batching is worth ~630 ms per extra prompt because model init (~695 ms) is paid once instead of
once per call. That is only usable if "dialog reset" really returns the dialog to the state a fresh
process would start in. This script is the gate.

It is deliberately strict, and it exists because the LADE experiment on 2026-10-14 looked perfect
on a single repeated prompt (three identical md5s) and then turned out to corrupt answers on a
wider set - "spike" decoded as "sp.peak", a flatline sensor_fault downgraded to normal. One prompt
proves nothing; different prompts in sequence are what catch state leaking between queries.

  python verify_batch.py -n 8 [--bundle /data/local/tmp/genie_bundle_ft]

Exits non-zero on any mismatch.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADB = str(ROOT.parent / "platform-tools" / "adb.exe")
BASE = "/data/local/tmp/genie_bundle"
PREFILL = '{"pattern": "'
ENV = (f"LD_LIBRARY_PATH={BASE}/qairt_2_50_libs:{BASE}/aarch64-android:{BASE} "
       f"ADSP_LIBRARY_PATH='{BASE}/dsp_2_50;{BASE}/dsp;/vendor/dsp/cdsp;"
       f"/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp'")


def sh(cmd, timeout=900, input_text=None):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout,
                          input=input_text, encoding="utf-8", errors="replace")


def strip_bos(p):
    return p[len("<|begin_of_text|>"):] if p.startswith("<|begin_of_text|>") else p


def answers(out: str) -> list[str]:
    """Every [BEGIN]: ... [END] block, in order."""
    return [m.group(1).strip() for m in re.finditer(r"\[BEGIN\]:(.*?)\[END\]", out, re.S)]


def one_by_one(bundle, paths):
    got = []
    for p in paths:
        r = sh(f"cd {bundle} && {ENV} {BASE}/genie-t2t-run-2.50 -c smartcity_agent.json --prompt_file {p}")
        a = answers(r.stdout)
        got.append(a[0] if a else "")
    return got


def batched(bundle, paths):
    lines = ["dialog config create CFG smartcity_agent.json", "dialog create D CFG"]
    for p in paths:
        # reset is what must make query k independent of query k-1
        lines += ["dialog reset D", f"dialog query D {p}"]
    lines.append("exit")
    script = "/data/local/tmp/_vb_script.txt"
    sh(f"cat > {script}", input_text="\n".join(lines) + "\n")
    r = sh(f"cd {bundle} && {ENV} {BASE}/genie-app --script {script}")
    return answers(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="/data/local/tmp/genie_bundle_ft")
    ap.add_argument("-n", type=int, default=8)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    seen, pick = set(), []
    for r in rows:  # spread across roles and patterns, not N of one role
        k = (r["role"], r["pattern"])
        if k not in seen:
            seen.add(k)
            pick.append(r)
        if len(pick) >= a.n:
            break

    paths = []
    for i, r in enumerate(pick):
        p = f"/data/local/tmp/_vb_{i}.txt"
        sh(f"cat > {p}", input_text=strip_bos(r["prompt"] + PREFILL))
        paths.append(p)

    print(f"{len(paths)} prompts, bundle {a.bundle}")
    single = one_by_one(a.bundle, paths)
    batch = batched(a.bundle, paths)

    if len(batch) != len(single):
        print(f"FAIL: batch returned {len(batch)} answers for {len(single)} prompts")
        sys.exit(1)

    same = 0
    for i, r in enumerate(pick):
        ok = single[i] == batch[i]
        same += ok
        print(f"[{i+1}/{len(pick)}] {r['role']:11} {r['pattern']:22} identical={ok}")
        if not ok:
            print("   single:", single[i][:160])
            print("   batch :", batch[i][:160])

    print(f"\nidentical: {same}/{len(pick)}")
    sh("rm -f /data/local/tmp/_vb_*.txt /data/local/tmp/_vb_script.txt")
    if same != len(pick):
        print("MISMATCH - batching changes answers, do not wire it in")
        sys.exit(1)
    print("batching is safe on these prompts")


if __name__ == "__main__":
    main()
