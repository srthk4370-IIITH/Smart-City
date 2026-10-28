"""Write the app's v2 per-unit HVAC sensors (D1): app/device/data/sensors_hvac_v2.json.

Picks a few real, healthy AC indoor units from data/series/hvac_units (two office units on different floors
and one continuous-duty unit, one unit per floor) and gives each three live sensors (room_temp, setpoint, ac_on) plus the unit's
usual schedule (duty, on-fraction per IST hour) from TRAIN months, exactly what hvac.py puts in ctx["duty"] /
ctx["hour_on"]. The backend loads this file only when the v2 agent is on (agentversion.go).

  python3 training/v2/make_app_hvac_units.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hvac as H  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "app" / "device" / "data" / "sensors_hvac_v2.json"


def main():
    U = H.load_hvac_series(ROOT / "data" / "series")
    cand = []
    for node, u in sorted(U.items()):
        if u["faulty"] or u["duty"] == "idle":
            continue
        temps = [r[2] for r in u["rows"].values() if r[0] and r[2] is not None]
        sps = [r[3] for r in u["rows"].values() if r[0] and r[3] is not None]
        if len(temps) < 2000 or not sps:
            continue
        cand.append((u["duty"], -sum(u["hour_on"]), node, statistics.median(temps), statistics.median(sps)))
    picks, buildings = [], set()
    for duty, want in (("office", 2), ("continuous", 1)):
        for c in sorted(x for x in cand if x[0] == duty):
            b = c[2].split("-")[2]  # building + level: one unit per floor
            if b in buildings and duty == "office":
                continue
            picks.append(c)
            buildings.add(b)
            if sum(1 for p in picks if p[0] == duty) >= want:
                break
    sensors, units = [], {}
    for duty, _, node, t, sp in picks:
        p = node.split("-")
        b, lvl = p[2][:2], p[2][2:]
        loc = H.describe(node)
        base = dict(node=node, role="hvac", location=loc, building=b, level=lvl)
        sensors += [
            dict(base, metric="room_temp", label="Room temperature", min=10, max=45, step=0.1, value=round(t, 1), noise=0.1),
            dict(base, metric="setpoint", label="AC setpoint", min=16, max=32, step=0.5, value=round(sp * 2) / 2, noise=0),
            dict(base, metric="ac_on", label="AC running (1 = on)", min=0, max=1, step=1, value=1, noise=0),
        ]
        units[node] = {"duty": duty, "hour_on": [round(v, 4) for v in U[node]["hour_on"]], "mode": 1}
    OUT.write_text(json.dumps({"source": "training/v2/make_app_hvac_units.py (data/series/hvac_units, TRAIN months)",
                               "sensors": sensors, "units": units}, indent=1))
    print(json.dumps({k: v["duty"] for k, v in units.items()}), "->", OUT)


if __name__ == "__main__":
    main()
