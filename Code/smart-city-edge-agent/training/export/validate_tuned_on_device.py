"""Push the fine-tuned Genie bundle to the QIDK, run held-out agent prompts on the NPU with BOTH the tuned
and the base model, score them, and mark the tuned bundle VALIDATED only if it passes. The running app
switches its agents to the tuned model automatically (it re-checks on every /api/status), otherwise it
keeps using the base model (fallback).

  python validate_tuned_on_device.py --bundle <dir with llama_v3_2_3b_instruct_part_{1,2,3}_of_3.bin>
  python validate_tuned_on_device.py --skip-push          # re-score an already pushed bundle
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADB = str(ROOT.parent / "platform-tools" / "adb.exe")
BASE = "/data/local/tmp/genie_bundle"
FT = "/data/local/tmp/genie_bundle_ft"
PREFILL = '{"pattern": "'
sys.path.insert(0, str(ROOT / "training"))
import features as F  # noqa: E402


def sh(cmd, timeout=300, input_text=None):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout, input=input_text,
                          encoding="utf-8", errors="replace")


def run_genie(bundle_dir, prompt):
    sh("mkdir -p /data/local/tmp/smart_city_edge/state/prompts")
    path = "/data/local/tmp/smart_city_edge/state/prompts/val.txt"
    # Genie adds BOS itself; strip ours so the device sees exactly the training token sequence
    sh(f"cat > {path}", input_text=prompt[len("<|begin_of_text|>"):] if prompt.startswith("<|begin_of_text|>") else prompt)
    t0 = time.time()
    r = sh(f"cd {bundle_dir} && LD_LIBRARY_PATH={BASE}/qairt_2_50_libs:{BASE}/aarch64-android:{BASE} "
           f"ADSP_LIBRARY_PATH='{BASE}/dsp_2_50;{BASE}/dsp;{BASE}/dsp/unsigned;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp' "
           f"{BASE}/genie-t2t-run-2.50 -c smartcity_agent.json --prompt_file {path}", timeout=180)
    dt = time.time() - t0
    out = r.stdout
    i, j = out.find("[BEGIN]:"), out.rfind("[END]")
    text = out[i + 8:j] if i >= 0 and j > i else (out[i + 8:] if i >= 0 else "")
    return PREFILL + text.strip(), dt, (r.returncode, out[-300:] if i < 0 else "")


def first_json(text):
    s = text.find("{")
    depth = 0
    for k in range(s, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:k + 1])
                except json.JSONDecodeError:
                    return None
    return None


def score(role, gold, text):
    p = first_json(text)
    r = {"json": isinstance(p, dict)}
    if not r["json"]:
        return r
    norm = lambda v: str(v).strip().lower().replace(" ", "_").replace("-", "_")
    for k in ("pattern", "status", "likely_cause", "action"):
        r[k] = norm(p.get(k, "")) == gold[k]
    # action is a deterministic function of (cause, status) - the same mapping that generated the
    # training targets - so also score the action we would DERIVE instead of the one generated.
    try:
        from generate_dataset import action_of as _action_of
        r["action_derived"] = _action_of(norm(p.get("likely_cause", "")), norm(p.get("status", ""))) == gold["action"]
    except Exception:
        r["action_derived"] = r.get("action", False)
    r["_pred"] = {k: norm(p.get(k, "")) for k in ("pattern", "status", "likely_cause", "action")}
    r["_gold"] = {k: gold[k] for k in ("pattern", "status", "likely_cause", "action")}
    obs = p.get("observations") or []
    ids = re.findall(r"\bE\d+\b", " ".join(map(str, obs)))
    valid = {f"E{i}" for i in range(1, 9)}
    r["evidence"] = bool(ids) and all(i in valid for i in ids)
    pats = F.OCC_PATTERNS if role == "occupancy" else F.CONT_PATTERNS
    r["policy"] = (norm(p.get("pattern")) in pats and norm(p.get("likely_cause")) in F.CAUSES[role]
                   and norm(p.get("action")) in F.ACTIONS and r["evidence"])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", help="local folder with the 3 tuned .bin files")
    ap.add_argument("--skip-push", action="store_true")
    ap.add_argument("--tuned-only", action="store_true", help="skip the base-model control run")
    ap.add_argument("--per-role", type=int, default=4)
    ap.add_argument("--min-policy", type=float, default=0.6, help="tuned policy-pass rate needed to validate")
    a = ap.parse_args()
    was_running = "edge-agent" in sh("pgrep -xl edge-agent").stdout
    sh("pkill -x edge-agent")  # the NPU must not be shared with the app during validation
    print("waiting for the NPU to cool below 80 C ...", flush=True)
    for _ in range(60):
        t = sh("cat /sys/class/thermal/thermal_zone*/type /dev/null | paste - - >/dev/null 2>&1; "
               "for z in /sys/class/thermal/thermal_zone*; do case $(cat $z/type) in nsp*) cat $z/temp;; esac; done | sort -n | tail -1").stdout.strip()
        if t and int(t) < 80000:
            break
        time.sleep(30)
    sh(f"rm -f {FT}/VALIDATED")
    if not a.skip_push:
        b = Path(a.bundle)
        # AI Hub names them part1_of_3.bin; older/local exports use llama_..._part_1_of_3.bin
        bins = sorted(b.glob("part[0-9]_of_3.bin")) or sorted(b.glob("*part_[0-9]_of_3.bin"))
        if len(bins) != 3:
            raise SystemExit(f"expected 3 context binaries in {b}, found {[x.name for x in bins]}")
        sh(f"mkdir -p {FT}")
        for i, f in enumerate(bins, 1):
            print(f"pushing {f.name} ({f.stat().st_size / 2**20:.0f} MB) ...", flush=True)
            subprocess.run([ADB, "push", str(f), f"{FT}/llama_v3_2_3b_instruct_part_{i}_of_3.bin"], check=True)
        for extra in ("tokenizer.json", "htp_backend_ext_config.json"):
            src = b / extra
            if src.is_file():
                subprocess.run([ADB, "push", str(src), f"{FT}/{extra}"], check=True)
            else:
                sh(f"cp {BASE}/{extra} {FT}/")
        # Build the agent config from the exported genie_config.json, but force greedy decoding and our
        # token cap. The exported default is temp 0.8 / top-k 40 (random), which would break both the
        # app's exact-prompt cache and reproducibility.
        cfg = json.loads((b / "genie_config.json").read_text())
        d = cfg["dialog"]
        d["max-num-tokens"] = 320
        d["sampler"] = {"version": 1, "seed": 42, "temp": 0.0, "top-k": 1, "top-p": 0.0}
        d["engine"]["n-threads"] = 4
        d["engine"]["backend"]["QnnHtp"]["cpu-mask"] = "0xf0"
        d["engine"]["model"]["binary"]["ctx-bins"] = [f"llama_v3_2_3b_instruct_part_{i}_of_3.bin" for i in (1, 2, 3)]
        tmp = Path(os.environ.get("TEMP", ".")) / "smartcity_agent_ft.json"
        tmp.write_text(json.dumps(cfg, indent=2))
        subprocess.run([ADB, "push", str(tmp), f"{FT}/smartcity_agent.json"], check=True)
        print("pushed fine-tuned bundle + greedy agent config")
    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    pick, seen = [], defaultdict(int)
    for r in rows:
        key = r["role"]
        if seen[key] < a.per_role and sum(1 for x in pick if x["pattern"] == r["pattern"] and x["role"] == key) == 0:
            pick.append(r); seen[key] += 1
    res = {"tuned": defaultdict(list), "base": defaultdict(list)}
    for n, r in enumerate(pick, 1):
        gold = json.loads(r["completion"].replace("<|eot_id|>", ""))
        prompt = r["prompt"] + PREFILL
        models = (("tuned", FT),) if a.tuned_only else (("tuned", FT), ("base", BASE))
        for name, d in models:
            text, dt, err = run_genie(d, prompt)
            s = score(r["role"], gold, text)
            s["latency_s"] = round(dt, 1)
            res[name][r["role"]].append(s)
            print(f"[{n}/{len(pick)}] {name:5} {r['role']:11} gold={gold['pattern']:20} json={s['json']} "
                  f"pattern={s.get('pattern')} policy={s.get('policy')} {dt:.1f}s {err[1] if err[1] else ''}", flush=True)
    summary = {}
    for name in res:
        allr = [x for v in res[name].values() for x in v]
        if not allr:
            continue
        summary[name] = {k: round(sum(1 for x in allr if x.get(k)) / len(allr), 3)
                         for k in ("json", "pattern", "status", "likely_cause", "action", "action_derived", "evidence", "policy")}
        summary[name]["mean_latency_s"] = round(sum(x["latency_s"] for x in allr) / len(allr), 1)
    ok = summary["tuned"]["policy"] >= a.min_policy and (a.tuned_only or summary["tuned"]["pattern"] >= summary["base"]["pattern"])
    out = ROOT / "training" / "results" / "device_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "validated": ok, "n": len(pick)}, indent=1))
    with open(out.with_name("device_eval_samples.jsonl"), "w", encoding="utf-8") as fh:
        for name in res:
            for role, rows in res[name].items():
                for x in rows:
                    fh.write(json.dumps({"model": name, "role": role, **x}) + "\n")
    lines = ["# On-device evaluation (QIDK NPU, w4a16, held-out Nov-Dec windows)", "",
             "| model | JSON | pattern | status | cause | action (generated) | action (derived) | evidence | policy pass | latency s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name in [n for n in ("tuned", "base") if n in summary]:
        m = summary[name]
        lines.append(f"| {name} | {m['json']} | {m['pattern']} | {m['status']} | {m['likely_cause']} | {m['action']} | {m['action_derived']} | {m['evidence']} | {m['policy']} | {m['mean_latency_s']} |")
    (out.with_suffix(".md")).write_text("\n".join(lines) + f"\n\nValidated for the app: {ok}\n")
    print("\n".join(lines))
    if ok:
        sh(f"date > {FT}/VALIDATED")
        print("\nVALIDATED: the app now uses the fine-tuned model for its domain agents (base model stays as fallback).")
    else:
        print("\nNOT validated: the app keeps the base model for agents. See device_eval.md.")


if __name__ == "__main__":
    main()
