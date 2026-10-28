"""Situational use cases: one graphical story per measured situation -> data/situations/sit_*.json.

Every number comes from a real run through the app on the QIDK (NPU, fine-tuned agents):
  * refined re-analysis runs (proofs/2026-10-16_refined_reanalysis/device*/): INC-*_<stage>.json + refine_check.jsonl
    -> sensor trace (the injected demo readings, stitched from the early / 1.5 h / 3 h windows), what the agent said at
    each stage, 12 h checks, severity, title, action, approval state, timings;
  * hw_grid workload incidents (crowded room, chaos) for multi-sensor traces + timelines;
  * the final app stress report (htpd v6) for the final-app time of the same scenario.
Traces are demo readings injected into the app (not campus readings); SPEC data policy 3 allows them, encrypted.
"""
import datetime as dt
import statistics as stx
from _lib import *

S = __file__
T = "situations"
RR = PROOFS / "2026-10-16_refined_reanalysis"
HW = PROOFS / "2026-10-16_hw_grid"
V6 = PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json"
FEATURES = ROOT / "Code/smart-city-edge-agent/app/backend/features.go"
SCEN = ROOT / "Code/smart-city-edge-agent/app/backend/server.go"
STEP_H = 5 / 60          # one reading = 5 min of sensor time
GATE = 8                 # event gate: 8 consecutive abnormal readings

# limits exactly as app/backend/features.go (Metrics); None = no fixed limit for that metric
LIMITS = {("air_quality", "co2"): (1000, 1500), ("air_quality", "pm25"): (60, 120), ("air_quality", "pm10"): (100, 250),
          ("air_quality", "temp"): (30, 34), ("air_quality", "rh"): (70, 85), ("water", "tds"): (500, 1000),
          ("weather", "temp"): (38, 42), ("weather", "rh"): (90, 97), ("weather", "wind"): (10, 15)}
UNIT = {"co2": "ppm", "pm25": "ug/m3", "pm10": "ug/m3", "temp": "C", "rh": "%", "level": "level", "flow": "m3/h",
        "tds": "ppm", "ph": "pH", "power_kw": "kW", "wind": "m/s", "occ": "occupied", "ac_units_on": "AC units on", "room_temp": "C"}
NICE = {"co2": "CO2", "pm25": "PM2.5", "pm10": "PM10", "temp": "Temperature", "rh": "Humidity", "level": "Tank level",
        "flow": "Flow", "tds": "TDS", "ph": "pH", "power_kw": "Power", "wind": "Wind speed", "occ": "Occupancy",
        "ac_units_on": "AC units on", "room_temp": "Room temperature"}
DOM = {"air_quality": "air", "water": "water", "power": "power", "weather": "weather", "occupancy": "occupancy", "hvac": "hvac"}
STAGES = ["early", "1.5h", "3h"]


def hhmm(sim):
    return dt.datetime.fromtimestamp(sim, dt.timezone.utc).strftime("%H:%M")


def v6_incident(tag):
    for i in read_json(V6)["incidents"]:
        if i["tag"] == tag:
            return i
    return None


def stitch(windows, t0):
    """windows: [(window_end_sim, [48 readings])] -> sorted [(h from alert, value)], deduplicated by timestamp."""
    by = {}
    for end, w in windows:
        n = len(w)
        for i, v in enumerate(w):
            ts = end - (n - 1 - i) * 300
            by.setdefault(ts, v)
    return [(round((ts - t0) / 3600, 4), round(v, 3)) for ts, v in sorted(by.items())]


def event_start(trace, flat=False):
    """First reading that departs from the pre-event baseline (or the start of the final flat run for a stuck sensor).
    Returns (h from alert, before_view?)."""
    xs = [x for x, _ in trace]
    ys = [y for _, y in trace]
    pre = [y for x, y in trace if x <= 0]
    if flat:
        i = xs.index(0.0) if 0.0 in xs else len(pre) - 1
        while i > 0 and abs(ys[i] - ys[i - 1]) < 1e-9:
            i -= 1
        return xs[i], i == 0
    base = stx.median(pre[:12])
    diffs = [abs(b - a) for a, b in zip(pre[:24], pre[1:24])]
    noise = stx.median(diffs) if diffs else 0
    thr = max(6 * noise, 0.03 * abs(base), 1e-6)
    for x, y in trace:
        if x > 0:
            break
        if abs(y - base) > thr:
            return x, False
    return None, True


def stage_rows(run_dir, inc):
    """Per stage: the incident JSON at that stage + the refine_check line (wall time since injection)."""
    lines = {r["stage"]: r for r in read_jsonl(RR / run_dir / "refine_check.jsonl") if r["incident"] == inc}
    out = []
    for st in STAGES:
        d = read_json(RR / run_dir / f"{inc}_{st}.json")
        rev = [r for r in d["revisions"] if r["stage"] == st][-1]
        s0 = d["sensors"][0]
        out.append({"stage": st, "inc": d, "rev": rev, "line": lines.get(st, {}),
                    "lr": [x.get("text") for x in (s0.get("long_range") or [])]})
    return out


def refine_story(key, run_dir, inc, run_label, question, claim, why, decisions, v6tag, extra_notes="", already_running=False):
    rows = stage_rows(run_dir, inc)
    first, last = rows[0]["inc"], rows[-1]["inc"]
    s0 = first["sensors"][0]
    role, metric = s0["role"], s0["metric"]
    t0 = first["created_sim"]
    trace = stitch([(r["inc"]["sensors"][0]["window_end"], r["inc"]["sensors"][0]["window"]) for r in rows], t0)
    flat = rows[0]["rev"]["sensors"][0]["pattern"] == "flatline"
    start_h, before = event_start(trace, flat)
    if already_running:      # the event was already under way at the first reading of the stitched view
        start_h, before = None, True
    lim = LIMITS.get((role, metric))
    peak = max(trace, key=lambda p: p[1]) if metric != "level" else min(trace, key=lambda p: p[1])
    early_agent = [a for a in first["agents"] if a.get("ref") == "S1"][0]
    stages = []
    if start_h is not None and not before:
        stages.append({"key": "start", "label": "Event starts", "h": start_h,
                       "when": f"{start_h * 60:+.0f} min", "said": ("value freezes" if flat else f"leaves its baseline ({dict(trace)[start_h]:g} {UNIT.get(metric, '')})")})
    else:
        stages.append({"key": "start", "label": "Event starts", "h": None, "when": "before this view",
                       "said": ("already under way when the view starts" if already_running else
                                "no visible start in the 4 h view" if not flat else "already frozen when the view starts")})
    stages.append({"key": "alert", "label": "Alert", "h": 0.0, "when": f"{hhmm(t0)} sensor time",
                   "said": f"{GATE} abnormal readings in a row", "rule_title": first.get("rule_title")})
    for r in rows:
        rv, sn = r["rev"], r["rev"]["sensors"][0]
        h = {"early": 0.0, "1.5h": 1.5, "3h": 3.0}[r["stage"]]
        stages.append({
            "key": r["stage"], "label": {"early": "Agents done", "1.5h": "Refined 1.5 h", "3h": "Refined 3 h"}[r["stage"]], "h": h,
            "when": (f"+{rv['ms'] / 1000:.1f} s" if r["stage"] == "early" else f"+{h:g} h · {rv['ms'] / 1000:.1f} s"),
            "pattern": sn["pattern"], "status": sn["status"], "severity": rv["severity"], "title": rv["title"],
            "ms": rv["ms"], "npu_calls": rv["npu_calls"], "wall_s_since_inject": r["line"].get("t_since_inject_s"),
            "long_range": r["lr"]})
    lr_first = next(((r["stage"], r["lr"][0]) for r in rows if r["lr"]), None)
    # raised = the app's severity at a stage with a 12 h finding is above what the domain agent itself said (refine_check line)
    raised = any(r["rev"]["severity"] != ((r["line"].get("sensors") or [{}])[0].get("status")) for r in rows if r["lr"])
    v6 = v6_incident(v6tag) if v6tag else None
    fin = last["final"]["parsed"]
    sit = {
        "key": key, "question": question, "run": run_label, "incident": inc, "measured": True,
        "domain": DOM.get(role, role), "metric": NICE.get(metric, metric), "unit": UNIT.get(metric, ""),
        "node": s0["location"], "alert_sensor_time": hhmm(t0),
        "limits": {"warning": lim[0], "critical": lim[1]} if lim else None,
        "start_h": start_h, "start_before_view": before, "readings_to_alert": (round(-start_h / STEP_H) if start_h is not None and not before else None),
        "peak": {"h": peak[0], "y": peak[1]},
        "stages": stages,
        "check_12h": ({"stage": lr_first[0], "finding": lr_first[1], "raised_severity": raised} if lr_first else
                      {"stage": None, "finding": "no 12 h finding fired", "raised_severity": False}),
        "outcome": {"severity": last["severity"], "title": last["title"], "early_title": first["title"],
                    "label": fin.get("label"), "action": fin.get("action"), "requires_human_approval": fin.get("requires_human_approval"),
                    "approval": last.get("approval"), "agent_model": early_agent.get("model"),
                    "ttft_ms": early_agent.get("ttft_ms"), "agent_ms": round(early_agent.get("latency_ms") or 0),
                    "early_ms": rows[0]["rev"]["ms"], "refine_ms": [r["rev"]["ms"] for r in rows[1:]],
                    "npu_calls": sum(r["rev"]["npu_calls"] for r in rows),
                    "final_app_s": (v6["total_ms"] / 1000 if v6 else None), "final_app_incident": (v6["id"] if v6 else None)},
        "decisions": decisions,
    }
    files = [RR / run_dir / f"{inc}_{st}.json" for st in STAGES] + [RR / run_dir / "refine_check.jsonl", RR / "DEVICE_RESULTS.md", FEATURES, SCEN]
    if v6:
        files.append(V6)
    series = [ser(f"{NICE.get(metric, metric)} ({UNIT.get(metric, '')})", [pt(x, y) for x, y in trace], "ours",
                  domain=DOM.get(role, role), node=s0["node"])]
    write(T, f"sit_{key}", question, UNIT.get(metric, ""), series, files, S, n=1,
          chart={"type": "trace", "x": "h from alert (sensor time)"}, claim=claim, why=why,
          notes=(f"{run_label}, incident {inc}. Trace = injected demo readings (5 min apart), stitched from the early, 1.5 h and 3 h "
                 f"4 h windows. Wall timings at 1 s demo polls. {extra_notes}").strip(),
          extra={"situation": sit})
    return sit


def multi_story(key, f, question, claim, why, decisions, v6tag, nodes=None, scenario=""):
    d = read_json(f)
    t0 = d["created_sim"]
    sens = [s for s in d["sensors"] if (nodes is None and not s.get("context")) or (nodes and (s["node"], s["metric"]) in nodes)]
    series, starts = [], []
    for s in sens:
        tr = stitch([(s["window_end"], s["window"])], t0)
        st, _ = event_start(tr)
        if st is not None:
            starts.append(st)
        series.append(ser(f"{NICE.get(s['metric'], s['metric'])} ({UNIT.get(s['metric'], '')})", [pt(x, y) for x, y in tr], "alt",
                          domain=DOM.get(s["role"], s["role"]), node=s["node"], status=(s.get("rule_finding") or {}).get("status")))
    start_h = min(starts) if starts else None
    # timeline from the incident's own log lines ("... done in 3.8s ...", "Finished in 14.4s")
    tl = d["timeline"]
    v6 = v6_incident(v6tag)
    agents_done = [m["msg"] for m in tl if " agent done in " in m["msg"]]
    synth = next((m["msg"] for m in tl if m["msg"].startswith("Cross-domain report")), None)
    fin_s = next((float(re.search(r"Finished in ([\d.]+)s", m["msg"]).group(1)) for m in tl if m["msg"].startswith("Finished in")), d["total_ms"] / 1000)
    stat = [(a["role"], a.get("status")) for a in v6["agents"]] if v6 else []
    sev_counts = {}
    for _, s_ in stat:
        sev_counts[s_] = sev_counts.get(s_, 0) + 1
    fin = d["final"]["parsed"]
    stages = [
        {"key": "start", "label": "Event starts", "h": start_h, "when": (f"{start_h * 60:+.0f} min" if start_h is not None else "before this view"),
         "said": f"{len(sens)} sensors jump"},
        {"key": "alert", "label": "Alert", "h": 0.0, "when": f"{hhmm(t0)} sensor time", "said": f"{GATE} abnormal readings in a row",
         "rule_title": d["title"]},
        {"key": "early", "label": "Agents done", "h": 0.0,
         "when": (f"+{v6['total_ms'] / 1000:.1f} s final app" if v6 else f"+{fin_s:.1f} s"), "trace_run_s": fin_s,
         "said": (f"{len(v6['agents'])} NPU agents + synthesizer" if v6 else f"{len(agents_done)} NPU agents" + (" + synthesizer" if synth else "")),
         "severity": d.get("severity") or "critical", "pattern": None, "status": None, "ms": d["total_ms"], "npu_calls": d["npu_calls"]},
        {"key": "1.5h", "label": "Refined 1.5 h", "h": 1.5, "when": "not measured", "said": "not measured for this scenario", "severity": None},
        {"key": "3h", "label": "Refined 3 h", "h": 3.0, "when": "not measured", "said": "not measured for this scenario", "severity": None},
    ]
    sit = {
        "key": key, "question": question, "run": f"hw_grid workload {d['id']} ({scenario}) + final app {v6['id'] if v6 else '-'}",
        "incident": d["id"], "measured": True, "multi": True, "domain": "multi", "metric": f"{len(sens)} sensors", "unit": "",
        "alert_sensor_time": hhmm(t0), "limits": None, "start_h": start_h, "start_before_view": start_h is None,
        "readings_to_alert": (round(-start_h / STEP_H) if start_h is not None else None),
        "stages": stages,
        "agents": [{"ref": a.get("ref"), "role": a.get("role"), "pattern": a["parsed"].get("pattern") if a.get("parsed") else None,
                    "status": a["parsed"].get("status") if a.get("parsed") else None, "ms": round(a.get("latency_ms") or 0)}
                   for a in d["agents"] if a.get("fine_tuned")],
        "check_12h": {"stage": None, "finding": "not measured for this scenario", "raised_severity": False},
        # outcome = the final app run (htpd v6) of the same scenario; the trace run supplies only the readings and the trace-run time
        "outcome": {"severity": d.get("severity") or "critical", "title": (v6["title"] if v6 else d["title"]),
                    "label": ((v6.get("report") or {}).get("label") if v6 else fin.get("label")),
                    "action": ((v6.get("report") or {}).get("action") if v6 else fin.get("action")),
                    "requires_human_approval": fin.get("requires_human_approval"), "approval": d.get("approval"),
                    "early_ms": d["total_ms"], "npu_calls": (v6["npu_calls"] if v6 else d["npu_calls"]), "trace_run_npu_calls": d["npu_calls"], "agents_n": len(agents_done),
                    "final_app_s": (v6["total_ms"] / 1000 if v6 else None), "final_app_incident": (v6["id"] if v6 else None),
                    "final_app_agents": (len(v6["agents"]) if v6 else None), "final_app_npu_calls": (v6["npu_calls"] if v6 else None),
                    "final_app_label": ((v6.get("report") or {}).get("label") if v6 else None),
                    "final_app_action": ((v6.get("report") or {}).get("action") if v6 else None),
                    "final_app_repairs": ((v6.get("report") or {}).get("repairs") if v6 else None),
                    "final_app_status_counts": sev_counts},
        "decisions": decisions,
    }
    write(T, f"sit_{key}", question, "", series, [f, V6, FEATURES, SCEN], S, n=1,
          chart={"type": "trace", "x": "h from alert (sensor time)", "normalize": len(series) > 1}, claim=claim, why=why,
          notes=(f"Trace and timeline: incident {d['id']} (hw_grid workload run, before htpd: {fin_s:.1f} s). Final app (htpd v6) on the same "
                 f"scenario: {v6['id']} in {v6['total_ms'] / 1000:.1f} s. Lines are each scaled to their own range; hover shows real values. "
                 "Refinements were not measured for this scenario."),
          extra={"situation": sit})
    return sit


def not_measured(key, question, claim, why, decisions, detail):
    """No measured run: listed in the index only (no dataset, no invented numbers)."""
    return {"key": key, "question": question, "measured": False, "claim": claim, "why": why, "detail": detail, "decisions": decisions,
            "source_files": ["Code/smart-city-edge-agent/app/backend/policy.go", "HANDBOOK.md#2.39"]}


def main():
    out = []
    out.append(refine_story(
        "tank_leak", "device_run2", "INC-0612", "Refinement run 2 (12 h finding raises severity), QIDK NPU",
        "What happens when a tank leaks slowly?",
        "4 h view says normal; the 12 h check raises it to warning",
        "A slow leak never crosses a fixed limit; without the 12 h check it would stay 'normal'.",
        ["G16", "G17", "G15"], "M3 tank_leak",
        "Run 1 (INC-0610) found the gap: the same 12 h drift did not raise severity; run 2 is after the fix (D094).", already_running=True))
    out.append(refine_story(
        "power_throttling", "device_run3", "INC-0615", "Refinement run 3 (keep worst severity, events hold), QIDK NPU",
        "What happens when a room's power hits a cap (throttling)?",
        "Early read 'exponential increase', corrected to 'throttling' at 1.5 h",
        "The first alert stays fast; the re-read with more of the event names the real pattern.",
        ["G15", "G14", "G17"], "M3 power_throttling"))
    out.append(refine_story(
        "ventilation_failure", "device_run3", "INC-0616", "Refinement run 3 (keep worst severity, events hold), QIDK NPU",
        "What happens when the ventilation fails?",
        "CO2 alert as warning; critical at 1.5 h, kept at 3 h",
        "Severity follows what the AI sees as the event grows, and never silently drops.",
        ["G15", "G17", "G16"], "M3 ventilation_failure"))
    out.append(refine_story(
        "stuck_sensor", "device_run3", "INC-0617", "Refinement run 3 (keep worst severity, events hold), QIDK NPU",
        "What happens when a sensor gets stuck?",
        "A frozen reading is a sensor fault, not an emergency",
        "The operator sends a technician to the sensor instead of evacuating a room.",
        ["G17", "G05", "G15"], "M3 stuck_sensor"))
    out.append(refine_story(
        "pm_spike", "device", "INC-0611", "Refinement run 1, QIDK NPU",
        "What happens when outdoor PM2.5 spikes?",
        "A short PM2.5 burst: critical spike, kept as a spike after it ends",
        "A burst that is over must not be rewritten as 'stable' by the later re-reads.",
        ["G15", "G04"], "M3 pm_spike"))
    out.append(multi_story(
        "crowded_room", HW / "workload_INC-0392.json", "What happens when a room gets crowded?",
        "Occupancy, CO2 and power rise together: one cross-domain report",
        "One report names the shared cause instead of three separate alarms.",
        ["G06", "G05", "G04"], "M3 crowded_room",
        nodes={("SR-OC-GW-KH95-01", "occ"), ("SR-AQ-KH03-03", "co2"), ("SR-EM-KH04-01", "power_kw")}, scenario="crowded_room"))
    out.append(multi_story(
        "chaos", HW / "workload_INC-0401.json", "What happens when several systems fail at once?",
        "Every system fails at once: one incident, one report for a person",
        "An operator gets one prioritised, policy-checked report, not 13 alarms.",
        ["G05", "G06", "G04"], "chaos simultaneous #1", scenario="chaos, all sensors"))
    out.append(not_measured(
        "ac_empty_room", "What happens when the AC runs in an empty room?",
        "Not yet measured on the board",
        "Saving energy is the next step; it stays a human decision.",
        ["G06"],
        "The switch_off_ac recommendation (AC on, room empty) is part of the v2 retrain (D119) and needs operator approval; "
        "no measured run exists yet on the QIDK, so no trace or timing is shown."))
    idx = [{"key": x["key"], "id": (f"sit_{x['key']}" if x.get("measured") else None), "question": x["question"],
            "measured": x.get("measured", False), **({k: x[k] for k in ("claim", "why", "detail", "source_files")} if not x.get("measured") else {}),
            "decisions": x["decisions"]} for x in out]
    (DATA / "situations_index.json").write_text(json.dumps({"meta": {"title": "Situations: what happens when...", "generated_at": NOW, "script": rel(S),
        "qa_order": ["ventilation_failure", "tank_leak", "ac_empty_room", "chaos", "stuck_sensor", "power_throttling", "crowded_room", "pm_spike"],
        "decisions_order": ["tank_leak", "power_throttling", "stuck_sensor", "chaos"]}, "situations": idx}, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    for s in main():
        print(s["key"], s.get("readings_to_alert"), (s.get("outcome") or {}).get("severity"), (s.get("check_12h") or {}).get("finding"))
