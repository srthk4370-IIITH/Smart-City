"""Mode 1 vs 2 vs 3 comparison grid, through the real app on the QIDK (HANDBOOK 2.36 plan B).

Every case creates ONE incident in Mode 3 from an injected fault, then reruns that same incident in
Mode 1 and Mode 2 (/api/incidents/<id>/rerun?mode=m). A rerun reuses the incident's own sensor
windows, so the three modes judge identical data and the comparison is paired.

Cases (fixed seed, defined before the run):
  - scenario cases: each of the 10 app scenarios x time-of-day x sensor-jitter variations
  - excursion cases: a random sensor held at a random out-of-band value (high or low)
Ground truth is the injected fault itself (EXPECT below, fixed before the run and saved in the
manifest). The run is resumable: finished case ids are skipped on restart.

Writes proofs/<date>_grid_modes123/:
  manifest.json   git commit, device, bundle files, gold table, settings
  samples.jsonl   one line per case: variation, gold, and the full incident JSON for each mode
  log.txt         progress

  python grid_run.py [--out DIR] [--cases N] [--excursions N] [--cool 70]
"""
import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]                                   # repo root (qidk)
ADB = str(HERE.parents[2] / "platform-tools" / "adb.exe")  # Code/platform-tools
B = "http://127.0.0.1:8000"

# Ground truth per scenario: what the injected fault IS. pattern/cause = the target sensor's agent;
# label = the incident report. Sets list every answer we accept as correct, decided before the run.
EXPECT = {
    "ventilation_failure": {"pattern": ["exponential_increase", "gradual_increase", "step_increase"],
                            "cause": ["ventilation_insufficient", "occupancy_load"],
                            "label": ["ventilation_issue", "occupancy_driven_load"]},
    "pm_spike": {"pattern": ["spike"], "cause": ["outdoor_pollution_ingress", "indoor_emission_source"],
                 "label": ["air_pollution_event"]},
    "power_throttling": {"pattern": ["throttling", "gradual_increase", "exponential_increase", "step_increase"],
                         "cause": ["capacity_limit_throttling", "gradual_load_growth", "load_surge"],
                         "label": ["power_load_anomaly"]},
    "load_surge": {"pattern": ["spike"], "cause": ["load_surge", "equipment_startup"],
                   "label": ["power_load_anomaly"]},
    "tank_leak": {"pattern": ["gradual_decrease", "step_decrease", "dip"], "cause": ["possible_leak", "tank_draining"],
                  "label": ["water_leak_or_overuse"]},
    "pump_cycling": {"pattern": ["oscillation", "erratic"], "cause": ["pump_cycling"],
                     "label": ["water_supply_issue", "water_leak_or_overuse"]},
    "stuck_sensor": {"pattern": ["flatline"], "cause": ["sensor_fault"], "label": ["sensor_fault"]},
    "heat_buildup": {"pattern": ["gradual_increase", "exponential_increase", "step_increase"],
                     "cause": ["heat_buildup", "hvac_cooling_issue"],
                     "label": ["hvac_or_thermal_issue", "weather_driven"]},
    "off_hours_presence": {"pattern": ["off_hours_presence", "occupied", "arrival", "intermittent"],
                           "cause": ["off_hours_presence"], "label": ["occupancy_driven_load"]},
    "crowded_room": {"pattern": ["arrival", "occupied", "gradual_increase", "step_increase"],
                     "cause": ["occupancy_load", "ventilation_insufficient", "equipment_startup", "load_surge",
                               "gradual_load_growth", "arrival", "normal_occupancy"],
                     "label": ["occupancy_driven_load", "ventilation_issue"]},
}
DAY_CLOCKS = ["08:30", "10:00", "11:30", "13:00", "14:30", "16:00", "17:30"]
NIGHT_CLOCKS = ["22:00", "23:30", "01:00", "02:30", "04:00", "21:30", "00:30"]
NOISE = [0.6, 1.0, 1.4]


def _req(path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method="POST" if data is not None else "GET",
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def req(path, body=None, timeout=30):
    code, out = _req(path, body, timeout)
    if code == 0:  # backend restarting / forward lost: restore and retry once
        t0 = time.time()
        while time.time() - t0 < 240:
            subprocess.run([ADB, "forward", "tcp:8000", "tcp:8000"], capture_output=True, timeout=30)
            if _req("/api/status", None, 5)[0] == 200:
                break
            time.sleep(5)
        code, out = _req(path, body, timeout)
    return code, out


def adb(cmd, timeout=60):
    try:
        return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"adb error: {e}"


def temps():
    _, st = req("/api/status")
    d = st.get("device", {}) if isinstance(st, dict) else {}
    return {"npu_c": d.get("npu_c"), "skin_c": d.get("skin_c"), "max_c": d.get("thermal_max_c"),
            "guard": d.get("thermal_guard")}


def cool(limit, log):
    t0 = time.time()
    while True:
        t = temps()
        if (t["max_c"] or 0) < limit and not t["guard"]:
            return round(time.time() - t0, 1)
        if time.time() - t0 > 900:
            log(f"  still {t['max_c']} C after 15 min, continuing")
            return round(time.time() - t0, 1)
        time.sleep(10)


def incident_ids():
    _, d = req("/api/incidents?limit=20")
    return [i["id"] for i in d] if isinstance(d, list) else []


def wait_new(before, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        new = [i for i in incident_ids() if i not in before]
        if new:
            return new[0]
        time.sleep(1)
    return None


def wait_done(iid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        code, inc = req(f"/api/incidents/{iid}")
        if isinstance(inc, dict) and inc.get("state") not in ("running", None):
            return inc
        time.sleep(1.5)
    return None


def reset(clock, noise):
    req("/api/inject", {"scenario": "clear"})
    req("/api/sensors", {"reset_values": True, "noise_scale": noise})
    req("/api/replay", {"restart": True, "clock": clock, "poll_ms": 1000, "playing": True})


def rerun(iid, mode, log):
    before = set(incident_ids())
    code, out = req(f"/api/incidents/{iid}/rerun?mode={mode}", {})
    if code != 200:
        log(f"  rerun mode {mode} refused: {code} {str(out)[:80]}")
        return None
    nid = wait_new(before, 600)
    return wait_done(nid) if nid else None


def build_cases(rng, n_scen_var, n_exc, sensors, scenarios):
    cases = []
    for sc in scenarios:
        night = sc == "off_hours_presence"
        combos = [(c, n) for c in (NIGHT_CLOCKS if night else DAY_CLOCKS) for n in NOISE]
        rng.shuffle(combos)
        for k, (clock, noise) in enumerate(combos[:n_scen_var]):
            cases.append({"id": f"scn-{sc}-{k:02d}", "kind": "scenario", "scenario": sc, "clock": clock, "noise": noise})
    pool = [s for s in sensors if s["role"] not in ("hvac", "occupancy")]
    for k in range(n_exc):
        s = rng.choice(pool)
        hi = rng.random() < 0.7
        frac = rng.uniform(0.7, 0.95)
        target = s["default"] + (s["max"] - s["default"]) * frac if hi else s["default"] - (s["default"] - s["min"]) * frac
        cases.append({"id": f"exc-{k:03d}", "kind": "excursion", "node": s["node"], "metric": s["metric"],
                      "role": s["role"], "direction": "high" if hi else "low", "value": round(target, 3),
                      "default": s["default"], "clock": rng.choice(DAY_CLOCKS), "noise": rng.choice(NOISE)})
    rng.shuffle(cases)  # mix kinds so heat and drift spread evenly
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "proofs" / f"{datetime.now():%Y-%m-%d}_grid_modes123"))
    ap.add_argument("--scenario-variations", type=int, default=13)  # 10 x 13 = 130 cases
    ap.add_argument("--excursions", type=int, default=70)           # + 70 = 200 cases x 3 modes = 600
    ap.add_argument("--cool", type=float, default=70, help="wait until the board is below this before a case")
    ap.add_argument("--seed", type=int, default=20261016)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cases (smoke test)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.txt", "a", encoding="utf-8")

    def log(msg):
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    if req("/api/status")[0] != 200:
        sys.exit("backend not reachable on :8000 (adb forward tcp:8000 tcp:8000)")
    _, sens = req("/api/sensors")
    _, scs = req("/api/scenarios")
    scenarios = [s["id"] for s in scs]
    rng = random.Random(a.seed)
    cases = build_cases(rng, a.scenario_variations, a.excursions, sens["sensors"], scenarios)
    if a.limit:
        cases = cases[:a.limit]

    if not (out / "manifest.json").exists():
        git = subprocess.run(["git", "-C", str(REPO), "describe", "--always", "--dirty"], capture_output=True, text=True).stdout.strip()
        _, st = req("/api/status")
        bundle = adb("cd /data/local/tmp/genie_bundle_ft && ls -l *.bin *.json | awk '{print $5, $NF}'")
        manifest = {
            "what": "Mode 1 vs 2 vs 3, paired by rerun of the same incident; ground truth = injected fault",
            "created": datetime.now().isoformat(timespec="seconds"), "git": git, "seed": a.seed,
            "command": " ".join(sys.argv), "cases": len(cases), "modes": [3, 1, 2],
            "device": adb("getprop ro.serialno") + " " + adb("getprop ro.board.platform"),
            "models": st.get("models") if isinstance(st, dict) else None,
            "agent_bundle_files": bundle.splitlines(), "gold": EXPECT,
            "variations": {"day_clocks": DAY_CLOCKS, "night_clocks": NIGHT_CLOCKS, "noise_scale": NOISE},
            "case_list_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
            "cool_below_c": a.cool,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "cases.json").write_text(json.dumps(cases, indent=1), encoding="utf-8")

    done = set()
    sp = out / "samples.jsonl"
    if sp.exists():
        done = {json.loads(l)["case"]["id"] for l in sp.read_text(encoding="utf-8").splitlines() if l.strip()}
    log(f"{len(cases)} cases, {len(done)} already done")
    req("/api/mode", {"mode": 3})
    t_run = time.time()
    for n, case in enumerate(cases, 1):
        if case["id"] in done:
            continue
        waited = cool(a.cool, log)
        reset(case["clock"], case["noise"])
        req("/api/mode", {"mode": 3})
        time.sleep(2)
        before = set(incident_ids())
        t0 = time.time()
        rec = {"case": case, "gold": EXPECT.get(case.get("scenario"), None), "cooldown_s": waited,
               "temp_start": temps(), "started": datetime.now().isoformat(timespec="seconds"), "modes": {}}
        if case["kind"] == "scenario":
            code, _ = req("/api/inject", {"scenario": case["scenario"]})
            iid = wait_new(before, 200) if code == 200 else None
        else:
            iid = None
            while time.time() - t0 < 120 and not iid:
                req("/api/ingest", {"node": case["node"], "metric": case["metric"], "value": case["value"]})
                time.sleep(1)
                new = [i for i in incident_ids() if i not in before]
                iid = new[0] if new else None
            iid = iid or wait_new(before, 30)
        rec["gate_s"] = round(time.time() - t0, 1)
        if not iid:
            rec["error"] = "no incident raised"
            log(f"[{n}/{len(cases)}] {case['id']}: NO INCIDENT")
        else:
            inc3 = wait_done(iid)
            req("/api/inject", {"scenario": "clear"})  # stop the fault; reruns reuse the stored windows
            rec["modes"]["3"] = inc3
            for m in (1, 2):
                rec["modes"][str(m)] = rerun(iid, m, log) if inc3 else None
            got = {m: ((v or {}).get("final") or {}).get("parsed", {}) or {} for m, v in rec["modes"].items()}
            log(f"[{n}/{len(cases)}] {case['id']}: {iid} "
                f"M3 {(inc3 or {}).get('total_ms', 0)/1000:.1f}s label={got.get('3', {}).get('label')} "
                f"M2 label={got.get('2', {}).get('label')} M1 label={((rec['modes'].get('1') or {}).get('mode1_report') or {}).get('label')}")
        rec["temp_end"] = temps()
        rec["finished"] = datetime.now().isoformat(timespec="seconds")
        with open(sp, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    req("/api/inject", {"scenario": "clear"})
    req("/api/sensors", {"reset_values": True, "noise_scale": 1.0})
    req("/api/replay", {"poll_ms": 2000})
    log(f"grid finished in {(time.time() - t_run)/3600:.2f} h")


if __name__ == "__main__":
    main()
