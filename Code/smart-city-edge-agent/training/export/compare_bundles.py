"""Compare two Genie bundles on the SAME prompts and prove they are functionally identical.

Used when a bundle is recompiled with different graph shapes (e.g. extra context lengths) from the
SAME checkpoint and encodings. The weights did not change, so every generated string must match
byte-for-byte. Any mismatch means the export changed something it should not have, and the new
bundle must not be shipped.

  python compare_bundles.py --a /data/local/tmp/genie_bundle_ft --b /data/local/tmp/genie_bundle_ft2 -n 20

Also reports Genie's own profiler numbers per bundle, so the speed gain is measured on the exact
same prompts that proved identity.
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


def sh(cmd, timeout=300, input_text=None):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout,
                          input=input_text, encoding="utf-8", errors="replace")


def run(bundle_dir, prompt, prof="/data/local/tmp/_cmp_prof.json", config="smartcity_agent.json"):
    path = "/data/local/tmp/_cmp_prompt.txt"
    sh("mkdir -p /data/local/tmp")
    sh(f"cat > {path}", input_text=prompt[len("<|begin_of_text|>"):] if prompt.startswith("<|begin_of_text|>") else prompt)
    sh(f"rm -f {prof}")
    r = sh(f"cd {bundle_dir} && LD_LIBRARY_PATH={BASE}/qairt_2_50_libs:{BASE}/aarch64-android:{BASE} "
           f"ADSP_LIBRARY_PATH='{BASE}/dsp_2_50;{BASE}/dsp;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp' "
           f"{BASE}/genie-t2t-run-2.50 -c {config} --prompt_file {path} --profile {prof}", timeout=240)
    out = r.stdout
    i, j = out.find("[BEGIN]:"), out.rfind("[END]")
    text = (out[i + 8:j] if i >= 0 and j > i else (out[i + 8:] if i >= 0 else "")).strip()
    p = sh(f"cat {prof}").stdout
    g = lambda k: (re.search(r'"%s":\s*{\s*"value":\s*([0-9.]+)' % k, p) or [None, None])[1]
    return PREFILL + text, {
        "init_ms": round(float(g("init-time") or 0) / 1000),
        "ttft_ms": round(float(g("time-to-first-token") or 0) / 1000),
        "prompt_tok": int(float(g("num-prompt-tokens") or 0)),
        "gen_tok": int(float(g("num-generated-tokens") or 0)),
        "decode_ms": round(float(g("token-generation-time") or 0) / 1000),
        "rate": round(float(g("token-generation-rate") or 0), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="/data/local/tmp/genie_bundle_ft")
    ap.add_argument("--b", required=True)
    ap.add_argument("-n", type=int, default=20)
    # Comparing two CONFIGS inside one bundle (e.g. basic vs lade) is as useful as comparing two
    # bundles, and it isolates the config change from any difference in the binaries themselves.
    ap.add_argument("--cfg-a", default="smartcity_agent.json")
    ap.add_argument("--cfg-b", default="smartcity_agent.json")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    # spread across roles and patterns rather than taking the first N of one role
    seen, pick = set(), []
    for r in rows:
        k = (r["role"], r["pattern"])
        if k not in seen:
            seen.add(k)
            pick.append(r)
        if len(pick) >= a.n:
            break

    same = 0
    agg = {f"A {a.a}:{a.cfg_a}": [], f"B {a.b}:{a.cfg_b}": []}
    for n, r in enumerate(pick, 1):
        prompt = r["prompt"] + PREFILL
        ta, ma = run(a.a, prompt, config=a.cfg_a)
        tb, mb = run(a.b, prompt, config=a.cfg_b)
        agg[f"A {a.a}:{a.cfg_a}"].append(ma)
        agg[f"B {a.b}:{a.cfg_b}"].append(mb)
        ok = ta == tb
        same += ok
        print(f"[{n}/{len(pick)}] {r['role']:11} {r['pattern']:22} identical={ok} "
              f"A {ma['rate']} tok/s / B {mb['rate']} tok/s", flush=True)
        if not ok:
            print("   A:", ta[:160])
            print("   B:", tb[:160])

    print(f"\nidentical outputs: {same}/{len(pick)}")
    for name, ms in agg.items():
        if not ms:
            continue
        f = lambda k: round(sum(m[k] for m in ms) / len(ms), 1)
        print(f"{name}\n   init {f('init_ms')}ms  ttft {f('ttft_ms')}ms  prompt_tok {f('prompt_tok')}  "
              f"gen_tok {f('gen_tok')}  decode {f('decode_ms')}ms  rate {f('rate')} tok/s")
    if same != len(pick):
        print("\nMISMATCH - do not ship bundle B")
        sys.exit(1)


if __name__ == "__main__":
    main()
