"""Aggregate calibration statistics from the REAL laptop series (data/series). Output: core/calib_stats.json.

Owner rule: only aggregates leave this script (quantiles, profiles, rates). No sample, window or timestamp is
written. The JSON is checked by `assert_no_samples` (no list longer than 24 numbers except named profiles).

usage: python3 calib.py [--max-files-per-dir 40]
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SERIES = ROOT / "Code" / "smart-city-edge-agent" / "data" / "series"
OUT = HERE / "calib_stats.json"
IST = timezone(timedelta(hours=5, minutes=30))

# (domain dir, file prefix) -> metric columns, calibration key
GROUPS = [
    ("air_quality", "SR-AQ", {"co2": "co2_indoor", "temp": "temp_indoor", "rh": "rh_indoor", "pm25": "pm25_indoor"}),
    ("outdoor_air", "AQ-", {"pm25": "pm25_outdoor", "pm10": "pm10_outdoor"}),
    ("weather", "WE-", {"temp": "weather_temp", "rh": "weather_rh", "wind": "weather_wind", "rain": "weather_rain"}),
    ("water", "WM-WL", {"level": "tank_level"}),
    ("water", "WM-WF", {"flow": "water_flow"}),
    ("water", "WM-WD", {"tds": "water_tds", "ph": "water_ph"}),
    ("power", "SR-EM", {"power_kw": "power_load_room"}),
    ("power", "EM-", {"power_kw": "power_load_feeder", "pf": "power_pf"}),
    ("power", "SL-", {"power_kw": "power_solar"}),
    ("occupancy", "SR-OC", {"occ": "occupancy"}),
    ("hvac_units", "SR-AC", {"room_temp": "hvac_room_temp", "setpoint": "hvac_setpoint", "on": "hvac_on"}),
]


def q(v, p):
    if not v:
        return None
    s = sorted(v)
    k = (len(s) - 1) * p
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 4)


def median(v):
    return q(v, 0.5)


def robust_noise(xs):
    d = sorted(xs[i] - xs[i - 1] for i in range(1, len(xs)))
    if len(d) < 4:
        return None
    med = d[len(d) // 2]
    dev = sorted(abs(x - med) for x in d)
    return 1.4826 * dev[len(dev) // 2] / math.sqrt(2)


def read(path, cols):
    out = {c: [] for c in cols}
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            b = int(row["bucket"])
            for c in cols:
                v = row.get(c, "")
                if v not in ("", None):
                    try:
                        out[c].append((b, float(v)))
                    except ValueError:
                        pass
    return out


def stats_for(pairs):
    """pairs: [(bucket, value)] of ONE sensor -> partial aggregates."""
    pairs.sort()
    vals = [v for _, v in pairs]
    res = {"n": len(vals), "vals_q": [q(vals, p) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]}
    # gaps (in 5-min points)
    gaps = defaultdict(int)
    for i in range(1, len(pairs)):
        g = (pairs[i][0] - pairs[i - 1][0]) // 300 - 1
        if g >= 1:
            gaps["1" if g == 1 else "2" if g == 2 else "3-5" if g <= 5 else "6-11" if g <= 11 else "12-47" if g <= 47 else "48+"] += 1
    res["gaps"] = dict(gaps)
    # 4 h contiguous chunks: noise, jumps, autocorr
    noises, jumps, ac1, step1h = [], [], [], []
    chunk = []
    prev_b = None
    hour_vals = defaultdict(list)
    for b, v in pairs:
        if prev_b is not None and b - prev_b != 300:
            chunk = []
        chunk.append(v)
        prev_b = b
        if len(chunk) == 48:
            nz = robust_noise(chunk)
            if nz is not None:
                noises.append(nz)
            d = [chunk[i] - chunk[i - 1] for i in range(1, 48)]
            jumps.extend(abs(x) for x in d[::4])
            m = sum(d) / len(d)
            den = sum((x - m) ** 2 for x in d)
            if den > 0:
                ac1.append(sum((d[i] - m) * (d[i - 1] - m) for i in range(1, len(d))) / den)
            hm = [sum(chunk[i:i + 12]) / 12 for i in range(0, 48, 12)]
            step1h.extend(abs(hm[i] - hm[i - 1]) for i in range(1, 4))
            chunk = []
        t = datetime.fromtimestamp(b, IST)
        hour_vals[(t.weekday() >= 5, t.hour)].append(v)
    res["noise"] = noises
    res["jumps"] = jumps
    res["ac1"] = ac1
    res["step1h"] = step1h
    res["hour"] = {k: median(v) for k, v in hour_vals.items() if v}
    res["hour_n"] = {k: len(v) for k, v in hour_vals.items()}
    return res


def merge(parts):
    allv = [p for p in parts if p["n"] > 0]
    if not allv:
        return None
    noise = [x for p in allv for x in p["noise"]]
    jumps = [x for p in allv for x in p["jumps"]]
    ac1 = [x for p in allv for x in p["ac1"]]
    st = [x for p in allv for x in p["step1h"]]
    gaps = defaultdict(int)
    for p in allv:
        for k, v in p["gaps"].items():
            gaps[k] += v
    # diurnal profile: median over sensors of the per-sensor hourly median, weekday and weekend
    prof = {}
    for wk in (False, True):
        hrs = []
        for h in range(24):
            v = [p["hour"][(wk, h)] for p in allv if (wk, h) in p["hour"]]
            hrs.append(median(v) if v else None)
        prof["weekend" if wk else "workday"] = hrs
    wd = [v for v in prof["workday"] if v is not None]
    we = [v for v in prof["weekend"] if v is not None]
    lvl = [p["vals_q"][2] for p in allv]
    out = {
        "sensors": len(allv), "points": sum(p["n"] for p in allv),
        "level_q05_q25_q50_q75_q95_median_over_sensors": [median([p["vals_q"][i] for p in allv]) for i in range(5)],
        "level_median_range_over_sensors": [min(lvl), max(lvl)],
        "noise_q10_q50_q90": [q(noise, 0.1), q(noise, 0.5), q(noise, 0.9)],
        "abs_jump_q50_q90_q99": [q(jumps, 0.5), q(jumps, 0.9), q(jumps, 0.99)],
        "diff_autocorr1_q50": q(ac1, 0.5),
        "abs_hourly_mean_step_q50_q90_q99": [q(st, 0.5), q(st, 0.9), q(st, 0.99)],
        "gap_count_by_len_pts": dict(gaps),
        "diurnal_hourly_median_workday": [None if v is None else round(v, 3) for v in prof["workday"]],
        "diurnal_hourly_median_weekend": [None if v is None else round(v, 3) for v in prof["weekend"]],
        "weekend_over_workday_mean": round((sum(we) / len(we)) / (sum(wd) / len(wd)), 3) if wd and we and sum(wd) else None,
        "peak_hour_workday": (max(range(24), key=lambda h: prof["workday"][h] if prof["workday"][h] is not None else -1e18)
                              if wd else None),
        "trough_hour_workday": (min(range(24), key=lambda h: prof["workday"][h] if prof["workday"][h] is not None else 1e18)
                                if wd else None),
    }
    return out


def tank_rates(parts_pairs):
    """Fill / drain rates (level units per 5 min) from contiguous level runs."""
    fill, drain = [], []
    for pairs in parts_pairs:
        pairs.sort()
        for i in range(1, len(pairs)):
            if pairs[i][0] - pairs[i - 1][0] == 300:
                d = pairs[i][1] - pairs[i - 1][1]
                (fill if d > 0.5 else drain if d < -0.05 else []).append(abs(d))
    return {"fill_rate_per5min_q25_q50_q90": [q(fill, 0.25), q(fill, 0.5), q(fill, 0.9)],
            "drain_rate_per5min_q25_q50_q90": [q(drain, 0.25), q(drain, 0.5), q(drain, 0.9)]}


def assert_no_samples(obj, path="$"):
    """Fail when anything looks like a raw sample list (long numeric lists that are not 24-hour profiles)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_samples(v, f"{path}.{k}")
    elif isinstance(obj, list):
        if len(obj) > 24:
            raise AssertionError(f"list too long at {path}: {len(obj)}")
        for i, v in enumerate(obj):
            assert_no_samples(v, f"{path}[{i}]")


def main():
    mx = 40
    if "--max-files-per-dir" in sys.argv:
        mx = int(sys.argv[sys.argv.index("--max-files-per-dir") + 1])
    out = {"about": "Aggregate statistics of the real IIITH SCRC 5-min series on the laptop (data/series). "
                    "No samples, windows or timestamps. Used only to set simulator parameter ranges.",
           "metrics": {}, "sources": {}}
    tank_pairs = []
    for d, pref, cols in GROUPS:
        files = sorted(p for p in (SERIES / d).glob(pref + "*.csv"))[:mx]
        parts = defaultdict(list)
        for f in files:
            r = read(f, list(cols))
            for c, key in cols.items():
                if len(r[c]) >= 48:
                    parts[key].append(stats_for(list(r[c])))
                    if key == "tank_level":
                        tank_pairs.append(list(r[c]))
        for key, ps in parts.items():
            m = merge(ps)
            if m:
                out["metrics"][key] = m
        out["sources"][f"{d}/{pref}*"] = len(files)
        print(d, pref, len(files), flush=True)
    out["metrics"].setdefault("tank_level", {}).update(tank_rates(tank_pairs))
    # occupancy schedule: P(occupied) by hour = the diurnal medians of the 0/1 series are too coarse; use means
    occ = defaultdict(lambda: [0, 0])
    for f in sorted((SERIES / "occupancy").glob("SR-OC*.csv")):
        r = read(f, ["occ"])
        for b, v in r["occ"]:
            t = datetime.fromtimestamp(b, IST)
            k = ("weekend" if t.weekday() >= 5 else "workday", t.hour)
            occ[k][0] += v >= 0.5
            occ[k][1] += 1
    out["occupancy_schedule"] = {w: [round(occ[(w, h)][0] / occ[(w, h)][1], 3) if occ[(w, h)][1] else None for h in range(24)]
                                 for w in ("workday", "weekend")}
    hv = defaultdict(lambda: [0, 0])
    for f in sorted((SERIES / "hvac_units").glob("SR-AC*.csv"))[:mx]:
        r = read(f, ["on"])
        for b, v in r["on"]:
            t = datetime.fromtimestamp(b, IST)
            k = ("weekend" if t.weekday() >= 5 else "workday", t.hour)
            hv[k][0] += v >= 0.5
            hv[k][1] += 1
    out["hvac_on_fraction_by_hour"] = {w: [round(hv[(w, h)][0] / hv[(w, h)][1], 3) if hv[(w, h)][1] else None for h in range(24)]
                                       for w in ("workday", "weekend")}
    try:
        out["e10_count_thresholds"] = json.loads((ROOT / "Code" / "smart-city-edge-agent" / "data" / "sft_v2" / "kthr.json").read_text())
    except Exception:  # noqa: BLE001
        pass
    assert_no_samples(out)
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, len(out["metrics"]), "metrics")


if __name__ == "__main__":
    main()
