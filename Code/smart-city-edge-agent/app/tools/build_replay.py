"""Build the on-device replay pack from data/series (stdlib only).

Picks the KH-centred node set (plus campus weather/outdoor air/substation), finds the 7-day span in the
whole of 2025 (water sensors are sparse after Aug; replay is demo input, eval uses held-out Nov-Dec) with the best coverage, and writes:
  app/device/data/replay.csv   bucket,node,metric,value   (sorted by bucket; 5-min buckets, UTC epoch)
  app/device/data/nodes.json   topology: node -> role, metrics, location, building, level, kind
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training"))
import features as F  # noqa: E402
from generate_dataset import describe  # noqa: E402

SERIES = ROOT / "data" / "series"
OUT = ROOT / "app" / "device" / "data"
IST = timezone(timedelta(hours=5, minutes=30))

NODES = {
    # role, folder, metrics
    "SR-AQ-KH00-01": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "SR-AQ-KH00-02": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "SR-AQ-KH03-01": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "SR-AQ-KH03-02": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "SR-AQ-KH03-03": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "SR-AQ-KH95-00": ("air_quality", "air_quality", ["co2", "pm25", "temp", "rh"]),
    "AQ-KN00-00": ("air_quality", "outdoor_air", ["pm25", "pm10"]),
    "AQ-VN90-00": ("air_quality", "outdoor_air", ["pm25", "pm10"]),
    "WM-WL-KH00-00": ("water", "water", ["level"]),
    "WM-WL-KH98-00": ("water", "water", ["level"]),
    "WM-WF-KH95-40": ("water", "water", ["flow"]),
    "WM-WF-KH98-40": ("water", "water", ["flow"]),
    "WM-WF-KH98-70": ("water", "water", ["flow"]),
    "WM-WF-PH03-03": ("water", "water", ["flow"]),
    "WM-WD-KH95-00": ("water", "water", ["tds", "ph"]),
    "WM-WD-KH96-00": ("water", "water", ["tds", "ph"]),
    "WM-WD-KH98-00": ("water", "water", ["tds", "ph"]),
    "SR-EM-KH04-00": ("power", "power", ["power_kw"]),
    "SR-EM-KH04-01": ("power", "power", ["power_kw"]),
    "SR-EM-KH04-02": ("power", "power", ["power_kw"]),
    "EM-CR-SB00-00": ("power", "power", ["power_kw", "pf"]),
    "SL-PL00-00": ("power", "power", ["power_kw"]),
    "WE-VN04-00": ("weather", "weather", ["temp", "rh", "wind"]),
    "SR-OC-GW-KH95-01": ("occupancy", "occupancy", ["occ"]),
    "SR-OC-GW-KH95-02": ("occupancy", "occupancy", ["occ"]),
    "SR-OC-GW-KH95-03": ("occupancy", "occupancy", ["occ"]),
    "SR-OC-GW-KH95-21": ("occupancy", "occupancy", ["occ"]),
    "SR-OC-GW-KH95-22": ("occupancy", "occupancy", ["occ"]),
    "SR-OC-GW-KH95-23": ("occupancy", "occupancy", ["occ"]),
    # HVAC context (not an agent): AC units running per KH level
    "AC-KH00": ("hvac", "hvac", ["ac_units_on", "room_temp"]),
    "AC-KH01": ("hvac", "hvac", ["ac_units_on", "room_temp"]),
    "AC-KH02": ("hvac", "hvac", ["ac_units_on", "room_temp"]),
    "AC-KH03": ("hvac", "hvac", ["ac_units_on", "room_temp"]),
}


def load(folder, node, metrics):
    out = defaultdict(dict)
    p = SERIES / folder / f"{node}.csv"
    if not p.exists():
        return out
    with open(p, newline="") as fh:
        for r in csv.DictReader(fh):
            b = int(r["bucket"])
            for m in metrics:
                v = r.get(m, "")
                if v != "":
                    out[m][b] = float(v)
    return out


def main():
    data = {}
    for node, (role, folder, metrics) in NODES.items():
        cols = load(folder, node, metrics)
        for m in metrics:
            if cols.get(m):
                data[(node, m)] = cols[m]
    step = 300
    lo = int(datetime(2025, 1, 2, tzinfo=IST).timestamp()) // step * step
    hi = int(datetime(2025, 12, 31, tzinfo=IST).timestamp()) // step * step
    span = 7 * 288
    hist = F.WINDOW
    best = None
    for start in range(lo + hist * step, hi - span * step, 288 * step):
        sc = 0
        for (node, m), s in data.items():
            have = sum(1 for i in range(-hist, span, 6) if start + i * step in s)
            frac = have / ((span + hist) / 6)
            w = 2.0 if NODES[node][0] in ("water", "occupancy") else 1.0
            sc += w * min(1.0, frac / 0.8)
        if best is None or sc > best[0]:
            best = (sc, start)
    common = best[1]
    start = common - hist * step
    end = common + span * step
    # per node: best whole-week shift (keeps weekday/time-of-day) onto the common clock
    week = 7 * 288 * step
    shifts = {}
    nodes_metrics = defaultdict(list)
    for (node, m) in data:
        nodes_metrics[node].append(m)
    for node, ms in nodes_metrics.items():
        bestn = None
        for k in range(-40, 41):
            off = k * week
            s0 = start + off
            if s0 < lo - hist * step or s0 + (span + hist) * step > hi + 288 * step:
                continue
            have = 0
            for m in ms:
                s = data[(node, m)]
                have += sum(1 for i in range(0, span + hist, 3) if s0 + i * step in s)
            if bestn is None or have > bestn[0]:
                bestn = (have, off)
        shifts[node] = bestn[1] if bestn else 0
    OUT.mkdir(parents=True, exist_ok=True)
    rows = 0
    coverage = {}
    with open(OUT / "replay.csv", "w", newline="") as o:
        w = csv.writer(o)
        w.writerow(["bucket", "node", "metric", "value"])
        for b in range(start, end, step):
            for (node, m), s in sorted(data.items()):
                v = s.get(b + shifts[node])
                if v is not None:
                    w.writerow([b, node, m, round(v, 4)]); rows += 1
    for (node, m), s in data.items():
        coverage[f"{node}:{m}"] = round(sum(1 for b in range(start, end, step) if b + shifts[node] in s) / ((end - start) / step), 3)
    topo = {}
    for node, (role, folder, metrics) in NODES.items():
        have = [m for m in metrics if (node, m) in data]
        if not have:
            continue
        p = node.split("-")
        code = p[2] if node.startswith(("SR-", "WM-")) else (p[1] if node.startswith(("AQ-", "SL-", "WE-", "AC-")) else p[2])
        if node.startswith("SR-OC"):
            code = p[3]
        topo[node] = {"role": role, "metrics": have, "location": describe(node) if role != "hvac" else f"{code[:2]} building, level {code[2:]}, AC units",
                      "building": code[:2], "level": code[2:], "kind": folder}
    meta = {"start": start, "end": end, "start_ist": datetime.fromtimestamp(start, IST).isoformat(),
            "end_ist": datetime.fromtimestamp(end, IST).isoformat(), "rows": rows, "history_points": hist,
            "source_week_start_ist": {n: datetime.fromtimestamp(start + o, IST).strftime("%Y-%m-%d") for n, o in shifts.items()},
            "coverage": coverage, "nodes": topo}
    (OUT / "nodes.json").write_text(json.dumps(meta, indent=1))
    print(f"replay {meta['start_ist']} -> {meta['end_ist']}, {rows} rows, {len(topo)} nodes")
    low = {k: v for k, v in coverage.items() if v < 0.5}
    print("low coverage:", low)


if __name__ == "__main__":
    main()
