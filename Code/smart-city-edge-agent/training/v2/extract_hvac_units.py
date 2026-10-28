"""Per-AC-unit 5-minute series from the cleaned SR-AC.csv (HVAC v2 agent input).

The v1 extractor (training/extract_series.py) only kept floor aggregates (units on, floor-mean room
temperature). The HVAC agent needs each indoor unit's own room temperature, setpoint and run state,
which are all in the same source file, so this is a re-extraction of existing data, not new data.

Output (gitignored, private): data/series/hvac_units/<SR-AC-...>.csv
  bucket      5-min bucket start (unix s)
  on          1 if Start Stop Status was on in the majority of the bucket's readings, else 0
  thermo      fraction of readings with Thermo Status on (indoor unit actively calling for cooling)
  comp        fraction of readings with Compressor Status on (shared outdoor-unit compressor)
  room_temp   mean Room Temp (C) over readings in 10..45 C (0 C and >45 C are sensor glitches)
  setpoint    last Temp Adjust (C) in the bucket (16..32 C), rounded to 0.5 C
  mode        last Air Con Mode Status (1 cool, 3 fan, 5 dry - from the value counts)
  alarm       1 if any reading in the bucket had Alarm = 1
  malf        last Malfunction Code other than 1 (1 = no malfunction), else 1
Status columns in the cleaned file contain interpolation residue (1.4e-17, 0.9998); values are
rounded to 0/1 before use.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BUCKET = 300


def f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def b01(s):
    v = f(s)
    return None if v is None else (1 if v >= 0.5 else 0)


def main():
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(root.parents[1] / "ihub-clean-datasets" / "SR-AC.csv"))
    ap.add_argument("--out", default=str(root / "data" / "series" / "hvac_units"))
    a = ap.parse_args()
    # node -> bucket -> accumulators
    acc = defaultdict(lambda: defaultdict(lambda: {"n": 0, "on": 0, "th": 0, "cp": 0, "rt": 0.0, "rtn": 0,
                                                    "sp": None, "mode": None, "alarm": 0, "malf": 1}))
    rows = bad_t = rt_glitch = 0
    with open(a.src, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            try:
                ts = datetime.fromisoformat(r["Timestamp"]).timestamp()
            except (KeyError, ValueError):
                bad_t += 1
                continue
            A = acc[r["Node_id"]][int(ts // BUCKET) * BUCKET]
            A["n"] += 1
            A["on"] += b01(r.get("Start Stop Status")) or 0
            A["th"] += b01(r.get("Thermo Status")) or 0
            A["cp"] += b01(r.get("Compressor Status")) or 0
            rt = f(r.get("Room Temp"))
            if rt is not None and 10 <= rt <= 45:
                A["rt"] += rt; A["rtn"] += 1
            elif rt is not None:
                rt_glitch += 1
            sp = f(r.get("Temp Adjust"))
            if sp is not None and 16 <= sp <= 32:
                A["sp"] = round(sp * 2) / 2
            md = f(r.get("Air Con Mode Status"))
            if md is not None:
                A["mode"] = int(round(md))
            if b01(r.get("Alarm")) == 1:
                A["alarm"] = 1
            mc = f(r.get("Malfunction Code"))
            if mc is not None and round(mc) != 1:
                A["malf"] = int(round(mc))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rep = {"rows": rows, "bad_timestamp": bad_t, "room_temp_glitch_readings": rt_glitch, "nodes": {}}
    for node, bs in sorted(acc.items()):
        with open(out / f"{node}.csv", "w", newline="") as o:
            w = csv.writer(o)
            w.writerow(["bucket", "on", "thermo", "comp", "room_temp", "setpoint", "mode", "alarm", "malf"])
            for b in sorted(bs):
                A = bs[b]
                w.writerow([b, 1 if A["on"] * 2 >= A["n"] else 0, round(A["th"] / A["n"], 2), round(A["cp"] / A["n"], 2),
                            round(A["rt"] / A["rtn"], 2) if A["rtn"] else "", "" if A["sp"] is None else A["sp"],
                            "" if A["mode"] is None else A["mode"], A["alarm"], A["malf"]])
        rep["nodes"][node] = len(bs)
    (out / "_report.json").write_text(json.dumps(rep, indent=1))
    print(f"{rows:,} rows -> {len(acc)} units in {out}")


if __name__ == "__main__":
    main()
