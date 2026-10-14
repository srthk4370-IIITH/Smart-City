"""A/B the SCE_TRIM_ACTION optimisation through the real app path.

`action` is a deterministic function of (cause, status) and policy.go now always derives it, so the
tokens the model spends emitting `, "action": "..."` are pure latency. This measures what stopping
before that field actually buys, and checks nothing breaks.

  py app/tools/ab_trim.py

Runs each sensor as a single-sensor mode-3 incident (isolated: one NPU agent call, no synthesizer),
so the agent path is measured on its own. Reports generated tokens and latency per arm.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADB = str(ROOT / "platform-tools" / "adb.exe")
D = "/data/local/tmp/smart_city_edge"
SENSORS = [
    ("SR-AQ-KH03-03", "co2"), ("SR-AQ-KH03-03", "temp"), ("WM-WD-KH98-00", "ph"),
    ("WE-VN04-00", "temp"), ("EM-CR-SB00-00", "pf"), ("SR-OC-GW-KH95-01", "occ"),
]


def sh(cmd, timeout=120):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace").stdout


def wait_health(n=40):
    for _ in range(n):
        if sh('curl -s -o /dev/null -w %{http_code} -m 3 http://127.0.0.1:8000/api/status').strip() == "200":
            return True
        time.sleep(3)
    return False


def wait_idle(n=60):
    for _ in range(n):
        try:
            st = json.loads(sh("curl -s http://127.0.0.1:8000/api/status"))
            if not st["npu"]["busy"] and st["npu"]["queue"] == 0:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def run_arm(trim: int):
    sh("am force-stop com.iiith.smartcityedge; pkill -x edge-agent; sleep 2")
    sh(f"cd {D} && SCE_TRIM_ACTION={trim} setsid nohup ./edge-agent --dir {D} "
       f"--genie /data/local/tmp/genie_bundle --mode 3 --clock-unix $(date +%s) "
       f"> state/agent.log 2>&1 < /dev/null & sleep 3; echo started", timeout=60)
    if not wait_health():
        raise SystemExit(f"backend did not come up for trim={trim}")
    sh(f"pkill -x edge-agent; sleep 1; rm -f {D}/state/incidents.jsonl")
    sh(f"cd {D} && SCE_TRIM_ACTION={trim} setsid nohup ./edge-agent --dir {D} "
       f"--genie /data/local/tmp/genie_bundle --mode 3 --clock-unix $(date +%s) "
       f"> state/agent.log 2>&1 < /dev/null & sleep 3; echo started", timeout=60)
    wait_health()

    for node, metric in SENSORS:
        body = json.dumps({"node": node, "metric": metric, "mode": 3}).replace('"', '\\"')
        sh(f'curl -s -m 5 -X POST -d "{body}" http://127.0.0.1:8000/api/analyze')
        time.sleep(3)
        wait_idle()

    incs = json.loads(sh("curl -s http://127.0.0.1:8000/api/incidents"))
    rows = []
    for o in incs:
        d = json.loads(sh(f"curl -s http://127.0.0.1:8000/api/incidents/{o['id']}"))
        for a in d.get("agents", []):
            if not str(a.get("model", "")).startswith("Llama"):
                continue
            p = a.get("parsed") or {}
            rows.append({
                "ref": a.get("ref"), "tokens": (a.get("call_metrics") or {}).get("gen_tokens"),
                "latency_ms": a.get("latency_ms"), "valid": a.get("valid"),
                "cause": p.get("likely_cause"), "action": p.get("action"),
                "errors": a.get("errors"),
            })
    return rows


def summarise(name, rows):
    ok = [r for r in rows if r["tokens"] and r["latency_ms"]]
    if not ok:
        print(f"{name}: no usable rows"); return None
    tk = sum(r["tokens"] for r in ok) / len(ok)
    lt = sum(r["latency_ms"] for r in ok) / len(ok)
    bad = [r for r in rows if not r["valid"]]
    print(f"{name}: n={len(ok)} mean_tokens={tk:.1f} mean_latency={lt:.0f}ms invalid={len(bad)}")
    for r in bad[:3]:
        print("   INVALID:", r["ref"], r["errors"])
    return tk, lt, len(bad)


if __name__ == "__main__":
    off = run_arm(0)
    on = run_arm(1)
    print()
    a = summarise("trim OFF", off)
    b = summarise("trim ON ", on)
    if a and b:
        print(f"\ntokens saved per agent call: {a[0] - b[0]:.1f}")
        print(f"latency delta: {a[1] - b[1]:.0f} ms per call")
        print(f"invalid outputs: off={a[2]} on={b[2]}  (must both be 0)")
