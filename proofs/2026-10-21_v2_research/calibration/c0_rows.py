"""D4 calibration rows: one row per device v2 agent answer, with the onset age computed EXACTLY as the app's
RecalibrateConfidence does it (features_v2.go onsetAge: readings from the model's own onset HH:MM to the window
end, searched within the window's n readings; 1 = onset at the last reading; -1 = no onset / not in window).

  py -3 c0_rows.py                                   -> rows.json (placement_v2 + host400 + test_all)
  py -3 c0_rows.py --placement DIR [--placement DIR2] -> also any further placement set (e.g. 2026-10-21_v2_confirm/placement_s24)

Read-only on the inputs. Scoring = common_v2 (exact match): placement truth = the injected pattern
(clean -> stable), test rows = the teacher label (pattern/status/cause booleans from the device eval).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROOFS = HERE.parents[1]
REPO = PROOFS.parent
DEV = PROOFS / "2026-10-20_v2_post" / "device"
TEST = REPO / "Code" / "smart-city-edge-agent" / "data" / "sft_v2" / "test.jsonl"
IST = timezone(timedelta(hours=5, minutes=30))
sys.path.insert(0, str(PROOFS / "2026-10-21_v2_research" / "accuracy"))
from a1_confusion import parse, norm  # noqa: E402  (same JSON cut as the app: stop at "action")

RE_WIN = re.compile(r"WINDOW: .*? -> (\d\d):(\d\d) IST, (\d+) x 5 min")
RE_LIM = re.compile(r"LIMITS: (.*)")


def onset_age(onset: str, n: int, end_hh: int, end_mm: int) -> int:
    """features_v2.go onsetAge: idxTimeN(end, n, i) == onset for i = n-1..0 -> n - i."""
    if not onset or not re.fullmatch(r"\d\d:\d\d", onset):
        return -1
    end = end_hh * 60 + end_mm
    for i in range(n - 1, -1, -1):
        t = (end - (n - 1 - i) * 5) % 1440
        if f"{t // 60:02d}:{t % 60:02d}" == onset:
            return n - i
    return -1


def win_of(prompt: str):
    m = RE_WIN.search(prompt)
    return (int(m[1]), int(m[2]), int(m[3])) if m else (None, None, None)

NUM = r"([-+]?\d+(?:\.\d+)?)"


def prompt_nums(prompt: str) -> dict:
    """E1 last / E2 max / E3 min, the first SERIES means and the LIMITS numbers shown to the agent."""
    u = prompt[prompt.find("user<|end_header_id|>"):]
    o = {}
    for k, pat in (("last", r"E1 last = " + NUM), ("max", r"E2 max = " + NUM), ("min", r"E3 min = " + NUM)):
        m = re.search(pat, u)
        o[k] = float(m[1]) if m else None
    m = re.search(r"SERIES \([^)]*\): (.*)", u)
    xs = [float(x) for x in m[1].split() if re.fullmatch(NUM, x)] if m else []
    o["series_head"] = xs[:6]
    m = re.search(r"warning (above|below) " + NUM + r", critical (?:above|below) " + NUM, u)
    o["lim_dir"], o["lim_warn"], o["lim_crit"] = (m[1], float(m[2]), float(m[3])) if m else (None, None, None)
    return o


def month_of(epoch):
    return datetime.fromtimestamp(epoch, IST).strftime("%Y-%m") if epoch else None


def placement_rows(d: Path, src: str):
    cases = {c["id"]: c for c in map(json.loads, open(d / "cases.jsonl", encoding="utf-8"))}
    prompts = {(p["id"], p["d"], p["n"]): p for p in map(json.loads, open(d / "prompts.jsonl", encoding="utf-8"))}
    out = []
    for r in map(json.loads, open(d / "samples.jsonl", encoding="utf-8")):
        p = prompts[(r["id"], r["d"], r["n"])]
        c = cases[r["id"]]
        a = parse(r["text"])
        hh, mm, n = win_of(p["prompt"])
        truth = "stable" if p["truth"].get("clean") else p["truth"]["pattern"]
        pred = norm(a.get("pattern", "")) if a else "INVALID"
        conf = a.get("confidence") if a else None
        onset = str(a.get("onset", "")) if a else ""
        lim = RE_LIM.search(p["prompt"])
        out.append({"src": src, "id": r["id"], "event": src + ":" + r["id"], "d": r["d"], "n": n or r["n"],
                    "role": c["role"], "node": c["node"], "metric": c["metric"], "month": month_of(c.get("end_epoch")),
                    "clean": bool(p["truth"].get("clean")), "gold_pattern": truth, "gold_status": "normal" if p["truth"].get("clean") else None,
                    "gold_cause": None, "pred": pred, "pred_status": norm(a.get("status", "")) if a else "INVALID",
                    "pred_cause": norm(a.get("likely_cause", "")) if a else "INVALID",
                    "conf": float(conf) if isinstance(conf, (int, float)) else None, "onset": onset,
                    "age": onset_age(onset, n or r["n"], hh, mm) if hh is not None else -1, "end_hm": f"{hh:02d}:{mm:02d}" if hh is not None else None,
                    "ok_pattern": pred == truth, "ok_status": (norm(a.get("status", "")) == "normal") if (a and p["truth"].get("clean")) else None,
                    "ok_cause": None, "limits": lim[1] if lim else None, "family": "clean" if p["truth"].get("clean") else "event", **prompt_nums(p["prompt"])})
    return out


def test_rows():
    want = {}
    for name in ("test_all", "host400"):  # test_all first: an id in both keeps the test_all answer
        for r in map(json.loads, open(DEV / name / "samples.jsonl", encoding="utf-8")):
            want.setdefault(r["id"], (name, r))
    meta = {}
    with open(TEST, encoding="utf-8") as fh:
        for line in fh:
            j = json.loads(line)
            i = j.get("id")
            if i in want:
                meta[i] = {k: j.get(k) for k in ("node", "metric", "end_epoch", "d", "n", "pattern", "status", "likely_cause", "sub", "family")}
                meta[i]["prompt"] = j["prompt"]
    out = []
    for i, (name, r) in want.items():
        m = meta.get(i)
        if m is None:
            continue
        hh, mm, n = win_of(m["prompt"])
        a = parse(r["text"])
        conf = a.get("confidence") if a else None
        onset = str(a.get("onset", "")) if a else ""
        lim = RE_LIM.search(m["prompt"])
        out.append({"src": name, "id": i, "event": "test:" + i, "d": m.get("d"), "n": n or r["n"], "role": r["role"],
                    "node": m["node"], "metric": m["metric"], "month": month_of(m["end_epoch"]), "clean": bool(r["negative"]),
                    "gold_pattern": r["gold_pattern"], "gold_status": r["gold_status"], "gold_cause": m["likely_cause"],
                    "pred": (r.get("pred") or {}).get("pattern") or ("INVALID" if not a else norm(a.get("pattern", ""))),
                    "pred_status": (r.get("pred") or {}).get("status"), "pred_cause": (r.get("pred") or {}).get("likely_cause"),
                    "conf": float(conf) if isinstance(conf, (int, float)) else None, "onset": onset,
                    "age": onset_age(onset, n or r["n"], hh, mm) if hh is not None else -1, "end_hm": f"{hh:02d}:{mm:02d}" if hh is not None else None,
                    "ok_pattern": bool(r["pattern"]), "ok_status": bool(r["status"]), "ok_cause": bool(r["cause"]),
                    "limits": lim[1] if lim else None, "family": r["family"], "sub": m.get("sub"), "age_bucket": r.get("age"), "end_epoch": m["end_epoch"], **prompt_nums(m["prompt"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placement", action="append", default=[], help="extra placement dir(s) (same format as placement_v2)")
    ap.add_argument("--out", default=str(HERE / "rows.json"))
    a = ap.parse_args()
    rows = placement_rows(DEV / "placement_v2", "placement_v2") + test_rows()
    for d in a.placement:
        p = Path(d)
        rows += placement_rows(p, p.name)
    json.dump(rows, open(a.out, "w", encoding="utf-8"), indent=0)
    from collections import Counter
    print(Counter(r["src"] for r in rows), "no-conf", sum(r["conf"] is None for r in rows), "age=-1", sum(r["age"] < 0 for r in rows))


if __name__ == "__main__":
    main()
