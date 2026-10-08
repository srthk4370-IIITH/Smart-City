"""Stage 1: stream the cleaned SCRC CSVs into per-node 5-minute series.

Stdlib only (runs on Windows Python or WSL). One worker process per source file.
Values outside physical ranges (from `meta data.xlsx`) and known sentinels are
dropped *before* bucketing, so the series contain only plausible readings.

Output: data/series/<domain>/<node>.csv  with header  bucket,<metric>,...
        bucket = UTC epoch seconds of the 5-minute bucket start; empty cell = no data.
        data/series/_extract_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

csv.field_size_limit(10**9)
BUCKET = 300  # seconds


def f(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def rng(lo, hi):
    def check(x):
        return x is not None and lo <= x <= hi
    return check


# Per-source extraction specs: domain, metrics -> (column candidates, valid-range check, scale)
# Ranges follow meta data.xlsx sensor specs, tightened where the sheet allows nonsense.
SPECS = {
    "SR-AQ.csv": {
        "domain": "air_quality",
        "metrics": {
            "co2": (["CO2"], rng(250, 5000), 1.0),
            "pm25": (["Calibrated PM2.5", "PM2.5"], rng(0, 1000), 1.0),
            "temp": (["Temperature"], rng(5, 55), 1.0),
            "rh": (["Relative Humidity"], rng(1, 100), 1.0),
        },
    },
    "air_qulaity.csv": {
        "domain": "outdoor_air",
        "metrics": {
            "pm25": (["Calibrated PM2.5", "PM2.5"], rng(0, 999), 1.0),
            "pm10": (["Calibrated PM10", "PM10"], rng(0, 999), 1.0),
            "temp": (["Calibrated Temperature", "Temperature"], rng(5, 55), 1.0),
            "rh": (["Calibrated Relative Humidity", "Relative Humidity"], rng(1, 100), 1.0),
        },
    },
    "WM-WL.csv": {
        "domain": "water",
        "metrics": {
            "level": (["Water Level"], rng(0.5, 500), 1.0),
        },
    },
    "WM-WF.csv": {
        "domain": "water",
        "metrics": {
            "flow": (["Flowrate"], rng(0, 40), 1.0),          # m3/h, spec max 31.25
            "total_flow": (["Total Flow"], rng(0, 1e8), 1.0),
        },
    },
    "WM_WD.csv": {
        "domain": "water",
        "metrics": {
            "tds": (["Compensated TDS value"], rng(1, 1000), 1.0),
            "ph": (["pH"], rng(1, 14), 1.0),
        },
    },
    "SR-EM.csv": {
        "domain": "power",
        "metrics": {
            # V1 firmware reports W, V2 reports kW (verified: V1 mean 7174, V2 mean 7-12)
            "power_kw": (["Power"], rng(0, 500), "srem"),
            "current": (["Current"], rng(0, 1000), 1.0),
        },
    },
    "EM.csv": {
        "domain": "power",
        "nodes": {"EM-CR-SB00-00"},  # 11 kV feeder; KH95-00 uses a shifted layout, SB00-01 mostly zero
        "metrics": {
            "power_kw": (["GDPower"], rng(0, 2000), 0.001),  # W -> kW
            "pf": (["GDPower Factor"], rng(0, 1), 1.0),
        },
    },
    "SL.csv": {
        "domain": "power",
        "metrics": {
            "power_kw": (["3_Active_power", "ActivePower"], rng(0, 2000), 1.0),
        },
    },
    "we.csv": {
        "domain": "weather",
        "metrics": {
            "temp": (["Temperature"], rng(5, 50), 1.0),
            "rh": (["Relative Humidity"], rng(1, 100), 1.0),
            "wind": (["Wind Speed"], rng(0, 44), 1.0),
            "solar": (["Solar Radiation"], rng(0, 1500), 1.0),
            "rain": (["Rain"], rng(0, 10.2), 1.0),
        },
    },
    "SR-AC.csv": {
        "domain": "hvac",  # aggregated per floor; used for occupancy inference + context
        "special": "srac",
    },
}


def parse_ts(s: str):
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def floor_of(node: str) -> str:
    # SR-AC-KH02-07 -> KH02
    parts = node.split("-")
    return parts[2] if len(parts) >= 4 else node


def extract(args):
    fname, src_dir, out_dir = args
    spec = SPECS[fname]
    t0 = time.time()
    path = Path(src_dir) / fname
    domain = spec["domain"]
    rows = kept = dropped = 0
    if spec.get("special") == "srac":
        on_units = defaultdict(lambda: defaultdict(set))
        rep_units = defaultdict(lambda: defaultdict(set))
        temp_acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                rows += 1
                node = r.get("Node_id", "")
                ts = parse_ts(r.get("Timestamp", ""))
                if ts is None:
                    dropped += 1
                    continue
                b = int(ts // BUCKET) * BUCKET
                fl = floor_of(node)
                rep_units[fl][b].add(node)
                if f(r.get("Start Stop Status")) == 1.0:
                    on_units[fl][b].add(node)
                rt = f(r.get("Room Temp"))
                if rt is not None and 10 <= rt <= 45:
                    a = temp_acc[fl][b]; a[0] += rt; a[1] += 1
                kept += 1
        d = Path(out_dir) / domain
        d.mkdir(parents=True, exist_ok=True)
        nodes_out = {}
        for fl, buckets in rep_units.items():
            name = f"AC-{fl}"
            with open(d / f"{name}.csv", "w", newline="") as o:
                w = csv.writer(o)
                w.writerow(["bucket", "ac_units_on", "ac_units_reporting", "room_temp"])
                for b in sorted(buckets):
                    a = temp_acc[fl].get(b)
                    w.writerow([b, len(on_units[fl].get(b, ())), len(buckets[b]),
                                round(a[0] / a[1], 3) if a and a[1] else ""])
            nodes_out[name] = len(buckets)
        return fname, {"rows": rows, "kept": kept, "dropped": dropped, "nodes": nodes_out, "sec": round(time.time() - t0, 1)}

    metrics = spec["metrics"]
    only = spec.get("nodes")
    acc = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0])))
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            node = r.get("Node_id", "")
            if only and node not in only:
                continue
            ts = parse_ts(r.get("Timestamp", ""))
            if ts is None:
                dropped += 1
                continue
            b = int(ts // BUCKET) * BUCKET
            got = False
            for m, (cols, ok, scale) in metrics.items():
                x = None
                for c in cols:
                    x = f(r.get(c))
                    if x is not None:
                        break
                if x is None:
                    continue
                if scale == "srem":
                    x = x / 1000.0 if r.get("Version", "").startswith("V1") else x
                else:
                    x = x * scale
                if not ok(x):
                    dropped += 1
                    continue
                a = acc[node][b][m]; a[0] += x; a[1] += 1
                got = True
            kept += got
    d = Path(out_dir) / domain
    d.mkdir(parents=True, exist_ok=True)
    nodes_out = {}
    mnames = list(metrics)
    for node, buckets in acc.items():
        with open(d / f"{node}.csv", "w", newline="") as o:
            w = csv.writer(o)
            w.writerow(["bucket"] + mnames)
            for b in sorted(buckets):
                row = [b]
                for m in mnames:
                    a = buckets[b].get(m)
                    row.append(round(a[0] / a[1], 4) if a and a[1] else "")
                w.writerow(row)
        nodes_out[node] = len(buckets)
    return fname, {"rows": rows, "kept": kept, "dropped_values": dropped, "nodes": nodes_out, "sec": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--src", default=str(root.parents[1] / "ihub-clean-datasets"))
    ap.add_argument("--out", default=str(root / "data" / "series"))
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    # biggest first so the pool finishes evenly
    order = ["SR-AC.csv", "air_qulaity.csv", "SR-AQ.csv", "SL.csv", "EM.csv", "WM-WF.csv",
             "SR-EM.csv", "WM-WL.csv", "we.csv", "WM_WD.csv"]
    report = {}
    with Pool(a.workers) as pool:
        for fname, rep in pool.imap_unordered(extract, [(n, a.src, a.out) for n in order]):
            report[fname] = rep
            print(f"{fname}: {rep['rows']:,} rows, {len(rep['nodes'])} nodes, {rep['sec']}s", flush=True)
    (Path(a.out) / "_extract_report.json").write_text(json.dumps(report, indent=1))
    print("done ->", a.out)


if __name__ == "__main__":
    sys.exit(main())
