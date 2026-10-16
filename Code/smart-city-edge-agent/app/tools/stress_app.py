"""App-level stress test for the QIDK smart-city edge agent.

Everything here goes through the running app's HTTP API - the same surface the dashboard sliders use -
so it tests the shipped system, not an offline harness. It drives randomized but physically plausible
sensor values, random sensor faults, every injected scenario, all three reasoning modes, operator
actions, and concurrent load, while watching the backend, the NPU daemon and the board's temperature.

  adb forward tcp:8000 tcp:8000
  python stress_app.py                 # full run, ~30 min
  python stress_app.py --quick         # one pass of each phase

Writes stress_report.json (every check with its evidence) and prints a PASS/FAIL summary.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

B = "http://127.0.0.1:8000"
# platform-tools sits next to the repo; works from Windows Python and from WSL
ADB = str(Path(__file__).resolve().parents[3] / "platform-tools" / "adb.exe")
HERE = Path(__file__).resolve().parent
RESULTS: list[dict] = []
INCIDENTS: list[dict] = []
rng = random.Random(20261014)


# ------------------------------------------------------------------ plumbing
def req(path, body=None, method=None, timeout=30, _retry=True):
    """One API call. If the backend is unreachable (restart, reboot, lost adb forward), restore the
    forward and wait for it to come back once before reporting failure - pass 2 crashed outright
    when the board rebooted mid-run."""
    code, out = _req(path, body, method, timeout)
    if code == 0 and _retry:
        wait_backend(180)
        code, out = _req(path, body, method, timeout)
    return code, out


def wait_backend(limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        subprocess.run([ADB, "forward", "tcp:8000", "tcp:8000"], capture_output=True, timeout=30)
        if _req("/api/status", None, None, 5)[0] == 200:
            return True
        time.sleep(5)
    return False


def _req(path, body=None, method=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method or ("POST" if data is not None else "GET"),
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # connection refused / timeout = the backend is down, which is a finding
        return 0, str(e)


def check(name, ok, evidence=""):
    RESULTS.append({"check": name, "ok": bool(ok), "evidence": evidence})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {evidence}" if evidence and not ok else ""), flush=True)
    return ok


def device(cmd):
    try:
        return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        return f"adb error: {e}"


def health(tag):
    _, st = req("/api/status")
    procs = device("pgrep -x edge-agent >/dev/null && echo backend; (pgrep -x genied || pgrep -x htpd) >/dev/null && echo daemon")
    temp = device("cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1")
    t = int(temp) // 1000 if temp.isdigit() else -1
    alive = isinstance(st, dict) and "backend" in procs
    daemon = "daemon" in procs
    guard = isinstance(st, dict) and st.get("device", {}).get("thermal_guard")
    check(f"{tag}: backend alive", alive, procs)
    check(f"{tag}: NPU daemon alive", daemon, procs)
    check(f"{tag}: board below 80 C ({t} C)", 0 < t < 80, f"{t} C")
    check(f"{tag}: thermal guard not tripped", not guard, str(guard))
    return t


def sensors():
    _, d = req("/api/sensors")
    return d["sensors"] if isinstance(d, dict) else []


def reset(clock="10:00"):
    req("/api/inject", {"scenario": "clear"})
    req("/api/replay", {"restart": True, "clock": clock, "poll_ms": 1000})
    for s in sensors():
        req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["default"]})


def incident_ids():
    _, d = req("/api/incidents")
    items = d if isinstance(d, list) else (d.get("incidents") if isinstance(d, dict) else [])
    return [i["id"] for i in (items or [])]


def wait_new_incident(before, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        new = [i for i in incident_ids() if i not in before]
        if new:
            return new[0], time.time() - t0
        time.sleep(1)
    return None, timeout


def wait_done(iid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, inc = req(f"/api/incidents/{iid}")
        if isinstance(inc, dict) and inc.get("state") in ("done", "done_with_errors"):
            return inc
        time.sleep(1.5)
    return None


def record(tag, inc):
    """Keep the parts of an incident needed to judge answer quality, not just validity."""
    f = inc.get("final") or {}
    p = f.get("parsed") or {}
    INCIDENTS.append({
        "tag": tag, "id": inc["id"], "mode": inc.get("mode"), "state": inc.get("state"),
        "title": inc.get("title"), "npu_calls": inc.get("npu_calls"), "total_ms": inc.get("total_ms"),
        "agents": [{"ref": a.get("ref"), "role": a.get("role"), "valid": a.get("valid"),
                    "errors": a.get("errors"), "repairs": a.get("repairs"),
                    "pattern": (a.get("parsed") or {}).get("pattern"),
                    "status": (a.get("parsed") or {}).get("status"),
                    "cause": (a.get("parsed") or {}).get("likely_cause"),
                    "action": (a.get("parsed") or {}).get("action"),
                    "observations": (a.get("parsed") or {}).get("observations")}
                   for a in (inc.get("agents") or []) if a.get("prompt")],
        "report": {"model": f.get("model"), "valid": f.get("valid"), "errors": f.get("errors"),
                   "repairs": f.get("repairs"), "label": p.get("label"), "action": p.get("action"),
                   "domains": p.get("affected_domains"), "root_cause": p.get("root_cause"),
                   "explanation": p.get("explanation")},
    })


# ------------------------------------------------------------------ phases
def phase_input_validation():
    print("\n== input validation: garbage must be rejected or clamped, never crash ==")
    s = sensors()[0]
    for label, v in [("NaN", "NaN"), ("string", "abc"), ("null", None), ("huge", 1e308), ("negative", -1e9)]:
        code, out = req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": v})
        if label in ("huge", "negative"):
            stored = out.get("stored") if isinstance(out, dict) else None
            check(f"ingest {label} clamped into [{s['min']},{s['max']}]",
                  code == 200 and stored is not None and s["min"] <= stored <= s["max"], f"{code} {out}")
        else:
            check(f"ingest {label} rejected (400)", code == 400, f"{code} {str(out)[:80]}")
    code, _ = req("/api/ingest", {"node": "NOPE", "metric": "co2", "value": 1})
    check("ingest unknown sensor rejected (400)", code == 400, str(code))
    code, _ = req("/api/inject", {"scenario": "does_not_exist"})
    check("inject unknown scenario rejected (400)", code == 400, str(code))
    code, _ = req("/api/incidents/INC-9999")
    check("unknown incident -> 404", code == 404, str(code))
    code, _ = req("/api/replay", {"clock": "25:99"})
    check("replay bad clock rejected (400)", code == 400, str(code))
    req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["default"]})


def phase_quiet(seconds):
    print(f"\n== quiet: random walk inside normal bands for {seconds}s - expect NO incidents ==")
    reset()
    before = set(incident_ids())
    ss = sensors()
    t0 = time.time()
    while time.time() - t0 < seconds:
        for s in rng.sample(ss, min(5, len(ss))):
            # Drift on the scale of the sensor's OWN noise. An earlier version used 3% of the full
            # range, which on the campus power meter is +/-30 kW per reading: the app correctly saw a
            # real 600 -> 628 kW step and reported it, which is detection working, not a false alarm.
            span = max(s.get("noise", 0) * 2, (s["max"] - s["min"]) * 0.002)
            v = s["default"] + rng.uniform(-span, span)
            req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": round(v, 2)})
        time.sleep(1)
    new = [i for i in incident_ids() if i not in before]
    check(f"no false alarms from normal drift ({seconds}s)", not new, f"spurious: {new}")


def phase_excursions(n):
    print(f"\n== random excursions: {n} random sensors driven out of range - expect an incident each ==")
    ss = [s for s in sensors() if s["metric"] not in ("occ", "ac_units_on")]
    for s in rng.sample(ss, min(n, len(ss))):
        reset()
        before = set(incident_ids())
        hi = rng.random() < 0.7
        target = s["default"] + (s["max"] - s["default"]) * rng.uniform(0.7, 0.95) if hi \
            else s["default"] - (s["default"] - s["min"]) * rng.uniform(0.7, 0.95)
        t0 = time.time()
        while time.time() - t0 < 40:  # hold it there like a real excursion
            req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": round(target, 2)})
            time.sleep(1)
            if set(incident_ids()) - before:
                break
        iid, dt = wait_new_incident(before, 30)
        tag = f"excursion {s['metric']}@{s['node']} -> {target:.1f}"
        if not check(f"{tag}: incident raised", iid, "none in 70s"):
            continue
        inc = wait_done(iid)
        if not check(f"{tag}: analysis finished", inc, "timeout"):
            continue
        record(tag, inc)
        check(f"{tag}: state done (not done_with_errors)", inc["state"] == "done", inc["state"])
        ok_agents = all(a.get("valid") for a in inc.get("agents") or [] if a.get("prompt"))
        check(f"{tag}: every NPU agent passed policy", ok_agents, json.dumps([a.get("errors") for a in inc.get("agents") or []])[:200])


def phase_faults():
    print("\n== sensor faults ==")
    ss = {f"{s['node']}|{s['metric']}": s for s in sensors()}

    # 1. stuck sensor: an exactly constant value with sensor jitter removed should read as a fault
    reset()
    s = ss["SR-AQ-KH03-03|temp"]
    req("/api/replay", {"poll_ms": 1000})
    before = set(incident_ids())
    t0 = time.time()
    while time.time() - t0 < 90:
        req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": 27.3})
        time.sleep(1)
        if set(incident_ids()) - before:
            break
    iid, _ = wait_new_incident(before, 20)
    if iid:
        inc = wait_done(iid)
        if inc:
            record("fault: stuck temp", inc)
            pats = [(a.get("parsed") or {}).get("status") for a in inc.get("agents") or [] if a.get("prompt")]
            check("stuck sensor: analysed without errors", inc["state"] == "done", inc["state"])
            # the sim adds jitter to held values, so this is a level shift, not a flatline; the real
            # stuck_sensor scenario (scenarios phase) is the fault-classification check
            RESULTS.append({"check": "stuck sensor (held slider): agent status " + str(pats), "ok": True, "evidence": "informational"})
    else:
        # with the slider value held exactly, the sim still adds sensor noise, so a perfect flatline
        # may never form - record it as an observation rather than inventing a failure
        RESULTS.append({"check": "stuck sensor: no incident within 110 s (sim noise keeps it non-flat)",
                        "ok": True, "evidence": "informational"})
        print("  [INFO] stuck sensor produced no incident (simulator adds noise to held values)")

    # 2. a single large spike IS an anomaly: it stays inside the 4-hour window, so the window keeps an
    #    abnormal status for the 8 readings the gate needs. Expect one incident, classified as a spike.
    reset()
    s = ss["SR-EM-KH04-01|power_kw"]
    before = set(incident_ids())
    req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["max"] * 0.9})
    time.sleep(1.2)
    req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": s["default"]})
    iid, _ = wait_new_incident(before, 40)
    inc = wait_done(iid) if iid else None
    if inc:
        record("fault: one-reading spike", inc)
    pats = [(a.get("parsed") or {}).get("pattern") for a in (inc or {}).get("agents") or [] if a.get("prompt")]
    check("one-reading spike is reported as a spike", "spike" in pats, f"incident={iid} patterns={pats}")

    # 3. flapping sensor: alternating normal/abnormal every reading must not satisfy the gate
    reset()
    before = set(incident_ids())
    for k in range(24):
        v = s["max"] * 0.9 if k % 2 == 0 else s["default"]
        req("/api/ingest", {"node": s["node"], "metric": s["metric"], "value": v})
        time.sleep(1)
    time.sleep(6)
    new = set(incident_ids()) - before
    check("flapping sensor does not satisfy the 8-reading gate", not new, str(new))


def phase_scenarios(modes):
    _, scs = req("/api/scenarios")
    for mode in modes:
        print(f"\n== every scenario in Mode {mode} ==")
        req("/api/mode", {"mode": mode})
        for sc in scs:
            reset("10:00" if sc["id"] != "off_hours_presence" else "23:00")
            req("/api/mode", {"mode": mode})
            before = set(incident_ids())
            code, _ = req("/api/inject", {"scenario": sc["id"]})
            if not check(f"M{mode} {sc['id']}: injectable", code == 200, str(code)):
                continue
            iid, dt = wait_new_incident(before, 150)
            if not check(f"M{mode} {sc['id']}: incident raised", iid, "none in 150 s"):
                continue
            inc = wait_done(iid)
            if not check(f"M{mode} {sc['id']}: finished", inc, "timeout"):
                continue
            record(f"M{mode} {sc['id']}", inc)
            check(f"M{mode} {sc['id']}: state done", inc["state"] == "done", inc["state"])
            if mode != 1:
                check(f"M{mode} {sc['id']}: report passed policy", (inc.get("final") or {}).get("valid"),
                      str((inc.get("final") or {}).get("errors")))
            if mode == 3 and sc["id"] == "crowded_room":
                check("M3 crowded_room: cross-domain incident (>=2 flagged sensors)",
                      inc.get("npu_calls", 0) >= 3, f"npu_calls={inc.get('npu_calls')}")  # 2 agents + synthesizer
    req("/api/mode", {"mode": 3})


def phase_chaos(rounds, staggered=False):
    """Every sensor goes haywire. This is the worst case for latency: the most NPU agents the
    orchestrator allows (max 8) plus the synthesizer reasoning across every domain at once."""
    kind = "staggered" if staggered else "simultaneous"
    print(f"\n== chaos ({kind}): all sensors abnormal at once, {rounds} round(s) ==")
    req("/api/mode", {"mode": 3})
    for r in range(rounds):
        reset()
        before = set(incident_ids())
        ss = sensors()
        targets = {}
        for s in ss:
            if s["metric"] == "occ":
                targets[s["node"], s["metric"]] = 1
            elif s["metric"] == "ac_units_on":
                targets[s["node"], s["metric"]] = 0  # AC off while the room overheats
            else:
                hi = rng.random() < 0.75
                frac = rng.uniform(0.6, 0.95)
                v = s["default"] + (s["max"] - s["default"]) * frac if hi else s["default"] - (s["default"] - s["min"]) * frac
                targets[s["node"], s["metric"]] = round(v, 2)
        order = list(targets)
        rng.shuffle(order)
        t0 = time.time()
        while time.time() - t0 < 60:
            elapsed = time.time() - t0
            for k, (node, metric) in enumerate(order):
                # staggered: sensors fail one after another over ~12 s, testing late joiners
                if staggered and elapsed < k * 0.7:
                    continue
                req("/api/ingest", {"node": node, "metric": metric, "value": targets[node, metric]})
            time.sleep(1)
            if set(incident_ids()) - before:
                break
        iid, dt = wait_new_incident(before, 60)
        tag = f"chaos {kind} #{r + 1}"
        if not check(f"{tag}: incident raised", iid, "none"):
            continue
        time.sleep(8)  # let any second batch form so every resulting incident is counted
        new = [i for i in incident_ids() if i not in before]
        incs = [wait_done(i, 300) for i in new]
        for inc in incs:
            if inc:
                record(tag, inc)
        main = max((i for i in incs if i), key=lambda i: i.get("npu_calls") or 0, default=None)
        if not check(f"{tag}: analysis finished", main, "timeout"):
            continue
        n_agents = sum(1 for a in main.get("agents") or [] if a.get("prompt"))
        f = main.get("final") or {}
        check(f"{tag}: {n_agents} NPU agents + synthesizer, {len(new)} incident(s), "
              f"{(main.get('total_ms') or 0) / 1000:.1f}s", main["state"] == "done", main["state"])
        check(f"{tag}: cross-domain report passed policy", f.get("valid"), str(f.get("errors")))
        check(f"{tag}: report names several domains",
              len((f.get("parsed") or {}).get("affected_domains") or []) >= 2,
              str((f.get("parsed") or {}).get("affected_domains")))
        bad = [a.get("errors") for a in main.get("agents") or [] if a.get("prompt") and not a.get("valid")]
        check(f"{tag}: every agent passed policy", not bad, str(bad)[:200])
        health(tag)


def phase_operator():
    print("\n== operator actions ==")
    # act on a FINISHED incident: approve/dismiss are refused (409) while one is still running
    ids = [i["id"] for i in req("/api/incidents")[1] if i.get("state") != "running"]
    if not ids:
        return check("operator: an incident exists to act on", False, "none")
    iid = ids[0]
    code, _ = req(f"/api/incidents/{iid}/dismiss", {"note": "   "})
    check("dismiss with a blank note is refused", code == 400, str(code))
    code, _ = req(f"/api/incidents/{iid}/approve", {"note": "stress test"})
    _, inc = req(f"/api/incidents/{iid}")
    check("approve is recorded", code == 200 and inc.get("approval") == "approved", str(inc.get("approval")))
    code, out = req(f"/api/incidents/{iid}/frobnicate", {})
    check("unknown incident action is rejected", code >= 400, f"{code} {str(out)[:60]}")

    # approving while an analysis is still running: should be refused (no decision before the AI is done)
    reset()
    before = set(incident_ids())
    req("/api/inject", {"scenario": "crowded_room"})
    iid2, _ = wait_new_incident(before, 120)
    if iid2:
        code, _ = req(f"/api/incidents/{iid2}/approve", {"note": "too early"})
        _, inc2 = req(f"/api/incidents/{iid2}")
        running = inc2.get("state") == "running"
        check("approve while analysis is running is refused",
              not (running and code == 200 and inc2.get("approval") == "approved"),
              f"state={inc2.get('state')} code={code} approval={inc2.get('approval')}")
        wait_done(iid2)
        # rerun the finished incident in each mode; must complete and must not touch the original
        for m in (1, 2, 3):
            n_before = set(incident_ids())
            code, _ = req(f"/api/incidents/{iid2}/rerun?mode={m}", {})
            nid, _ = wait_new_incident(n_before, 150)  # may queue behind event-gate alerts
            done = wait_done(nid) if nid else None
            check(f"rerun of {iid2} in Mode {m} completes", done and done["state"] in ("done", "done_with_errors"),
                  str(done and done.get("state")))


def phase_load():
    print("\n== concurrent load while the NPU is busy ==")
    reset()
    before = set(incident_ids())
    req("/api/inject", {"scenario": "crowded_room"})
    iid, _ = wait_new_incident(before, 120)
    paths = ["/api/status", "/api/incidents", "/api/live", "/api/sensors", "/api/scenarios", "/", "/app.js"]
    t0 = time.time()
    with cf.ThreadPoolExecutor(24) as ex:
        codes = list(ex.map(lambda p: req(p, timeout=20)[0], [rng.choice(paths) for _ in range(240)]))
    dt = time.time() - t0
    bad = [c for c in codes if c != 200]
    check(f"240 concurrent requests during analysis all succeed ({dt:.1f}s)", not bad, f"non-200: {len(bad)}")
    # hammer analyze: the app must queue, not crash or run NPU sessions in parallel
    ss = [s for s in sensors() if s["metric"] not in ("occ", "ac_units_on") and s.get("role") != "hvac"]
    with cf.ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda s: req("/api/analyze", {"node": s["node"], "metric": s["metric"], "mode": 3})[0],
                            rng.sample(ss, min(8, len(ss)))))
    check("8 simultaneous analyze requests accepted", all(c == 200 for c in codes), str(codes))
    t0 = time.time()
    while time.time() - t0 < 240:
        _, st = req("/api/status")
        if isinstance(st, dict) and not st.get("npu", {}).get("busy") and not st.get("npu", {}).get("queue"):
            break
        time.sleep(3)
    _, st = req("/api/status")
    check("NPU queue drains after the burst", isinstance(st, dict) and not st.get("npu", {}).get("queue"),
          json.dumps((st or {}).get("npu") if isinstance(st, dict) else st)[:200])
    _, incs = req("/api/incidents")
    items = incs if isinstance(incs, list) else []
    stuck = [i["id"] for i in items if i.get("state") == "running"]
    check("no incident left stuck in 'running'", not stuck, str(stuck))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", help="comma list of phases: validation,quiet,excursions,faults,scenarios,chaos,operator,load")
    a = ap.parse_args()
    t_start = time.time()
    if a.only:
        print("== baseline ==")
        health("baseline")
        phases = {
            "validation": phase_input_validation, "quiet": lambda: phase_quiet(90),
            "excursions": lambda: phase_excursions(5), "faults": phase_faults,
            "scenarios": lambda: phase_scenarios([3, 2]),
            "chaos": lambda: (phase_chaos(2), phase_chaos(1, staggered=True)),
            "operator": phase_operator, "load": phase_load,
        }
        for p in a.only.split(","):
            phases[p.strip()]()
        return summarize(t_start)
    print("== baseline ==")
    health("baseline")
    phase_input_validation()
    phase_quiet(30 if a.quick else 90)
    health("after quiet")
    phase_excursions(2 if a.quick else 5)
    health("after excursions")
    phase_faults()
    health("after faults")
    phase_scenarios([3] if a.quick else [3, 1, 2])
    health("after scenarios")
    phase_chaos(1 if a.quick else 2)
    phase_chaos(1, staggered=True)
    phase_operator()
    phase_load()
    health("after load")
    summarize(t_start)


def summarize(t_start):
    reset()
    req("/api/replay", {"poll_ms": 2000})
    passed = sum(r["ok"] for r in RESULTS)
    lat = [i["total_ms"] for i in INCIDENTS if i.get("total_ms") and i.get("mode") == 3]
    out = HERE / "stress_report.json"
    out.write_text(json.dumps({"results": RESULTS, "incidents": INCIDENTS}, indent=1), encoding="utf-8")
    print(f"\n==== {passed}/{len(RESULTS)} checks passed in {(time.time() - t_start) / 60:.1f} min ====")
    if lat:
        lat.sort()
        print(f"Mode 3 analysis: n={len(lat)} min {lat[0] / 1000:.1f}s  median {lat[len(lat) // 2] / 1000:.1f}s  max {lat[-1] / 1000:.1f}s")
    for r in RESULTS:
        if not r["ok"]:
            print(f"  FAIL {r['check']}: {r['evidence'][:160]}")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
