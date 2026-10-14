"""Summarise the SCE_TRIM_ACTION A/B captured by ab_trim.sh.

Reads the raw incident JSON dumped per arm and reports, for the NPU agent calls only:
generated tokens, latency, how many outputs the policy gate rejected, and whether the derived
action still came out right. Token count is the honest metric - latency also moves with sim drift
and die temperature.
"""
import json
import re
import sys
from pathlib import Path

TMP = Path("/tmp")


def load(arm):
    p = TMP / f"rows_{arm}.txt"
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8", errors="replace")
    out, depth, start = [], 0, None
    instr = esc = False
    for i, ch in enumerate(raw):          # split concatenated JSON objects
        if instr:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': instr = False
            continue
        if ch == '"': instr = True
        elif ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try: out.append(json.loads(raw[start:i + 1]))
                except Exception: pass
                start = None
    return out


def rows(incidents):
    r = []
    for d in incidents:
        for a in d.get("agents", []):
            if not str(a.get("model", "")).startswith("Llama"):
                continue
            cm = a.get("call_metrics") or {}
            p = a.get("parsed") or {}
            r.append({
                "tokens": cm.get("gen_tokens") or 0,
                "ms": a.get("latency_ms") or 0.0,
                "valid": bool(a.get("valid")),
                "action": p.get("action"),
                "cause": p.get("likely_cause"),
                "errors": a.get("errors") or [],
            })
    return r


def summarise(name, r):
    if not r:
        print(f"{name}: no agent calls captured")
        return None
    n = len(r)
    tk = sum(x["tokens"] for x in r) / n
    ms = sum(x["ms"] for x in r) / n
    bad = [x for x in r if not x["valid"]]
    noact = [x for x in r if not x["action"]]
    print(f"{name}: n={n}  mean_tokens={tk:5.1f}  mean_latency={ms:7.0f}ms  invalid={len(bad)}  missing_action={len(noact)}")
    for x in bad[:3]:
        print(f"    INVALID: {x['errors'][:1]}")
    return tk, ms, len(bad), n


if __name__ == "__main__":
    a = summarise("trim OFF", rows(load(0)))
    b = summarise("trim ON ", rows(load(1)))
    if a and b:
        dtok, dms = a[0] - b[0], a[1] - b[1]
        print()
        print(f"tokens saved / agent call : {dtok:5.1f}")
        print(f"latency delta / agent call: {dms:7.0f} ms")
        print(f"invalid outputs           : off={a[2]}  on={b[2]}   (both must be 0 to ship)")
        verdict = "SHIP" if (b[2] == 0 and dtok > 2) else "DO NOT SHIP"
        print(f"verdict                   : {verdict}")
