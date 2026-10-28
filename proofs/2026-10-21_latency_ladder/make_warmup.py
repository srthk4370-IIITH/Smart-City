"""Warm-up requests for a freshly started htpd (lever L2 in PLAN.md; read by htpdWarmup in patches/backend_latency.patch).
One agents request with a 4 h prompt per role (the early-alert window: every incident starts there), optionally the
8 h and 12 h windows too, and one synthesizer prompt. They fill htpd's per-role system-turn KV cache and its
recent-output draft memory. Prompts come from the Go/Python parity fixtures (byte-identical to the app's prompts)
and from a real app synthesizer call; the answers are thrown away.
  py -3 make_warmup.py [--windows 48,96,144] [--out htpd_warmup.jsonl]
Push:  adb push htpd_warmup.jsonl /data/local/tmp/smart_city_edge/htpd_warmup.jsonl   (the backend's workDir)
"""
import argparse, glob, json
from pathlib import Path
H = Path(__file__).resolve().parent
Q = Path(r"C:\Users\hp\Desktop\qidk")
AGENT_PREFILL = '{"pattern": "'
ROLES = ["air_quality", "power", "water", "weather", "occupancy", "hvac"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="48", help="readings per window to warm (48 = 4 h; 96, 144 = 8 h, 12 h)")
    ap.add_argument("--out", default=str(H / "htpd_warmup.jsonl"))
    a = ap.parse_args()
    fx = json.load(open(Q / "Code/smart-city-edge-agent/app/backend/testdata/v2_prompt_fixtures.json", encoding="utf-8"))["fixtures"]
    lines = []
    for n in [int(x) for x in a.windows.split(",")]:
        ps = []
        for role in ROLES:
            c = next((f for f in fx if f["role"] == role and f["n"] == n), None)
            if c is None:
                print(f"no fixture for {role} at n={n}, skipped")
                continue
            ps.append(c["prompt"] + AGENT_PREFILL)
        lines.append({"kind": "agents", "prompts": ps})
    syn = None
    for f in sorted(glob.glob(str(Q / "proofs/2026-10-21_v2_app/refine_v7/INC-*_early.json"))):
        fin = json.load(open(f, encoding="utf-8")).get("final") or {}
        if fin.get("prompt") and fin.get("latency_ms"):
            syn = fin["prompt"]  # already ends with the report prefill {"root_cause": "
            break
    if syn:
        lines.append({"kind": "synth", "prompts": [syn]})
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        for l in lines:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    print(f"{a.out}: {len(lines)} requests ({', '.join(str(len(l['prompts'])) + ' ' + l['kind'] for l in lines)})")

if __name__ == "__main__":
    main()
