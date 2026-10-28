"""App/UX datasets: stress tests through the app over time, final v6 run, Mode 2 vs 3 latency per scenario,
fault injection, UI layout checks, screenshot index (before/after)."""
import datetime as dt
import os
from _lib import *

S = __file__
T = "app_ux"
UX = PROOFS / "2026-10-16_ux_report_page"
RR = PROOFS / "2026-10-16_refined_reanalysis"
SHOTS = ROOT / "_shots"


def classify(check):
    c = check.lower()
    if "npu daemon alive" in c:
        return "harness check (stale genied-alive test)"
    if "below 80 c" in c or "thermal guard" in c:
        return "thermal"
    return "functional"


def parse_log(p):
    t = text(p)
    m = re.search(r"==== (\d+)/(\d+) checks passed", t)
    md = re.search(r"Mode 3 analysis: n=(\d+) min ([\d.]+)s\s+median ([\d.]+)s\s+max ([\d.]+)s", t)
    fails = re.findall(r"^\s+FAIL (.+)$", t, re.M)
    cls = {}
    for f in fails:
        k = classify(f)
        cls[k] = cls.get(k, 0) + 1
    chaos = [(int(a), float(b)) for a, b in re.findall(r"\[PASS\] chaos \w+ #\d: (\d+) NPU agents \+ synthesizer, 1 incident\(s\), ([\d.]+)s", t)]
    return {"passed": int(m.group(1)), "total": int(m.group(2)),
            "mode3": ({"n": int(md.group(1)), "min": float(md.group(2)), "median": float(md.group(3)), "max": float(md.group(4))} if md else None),
            "fail_classes": cls, "chaos": chaos}


def stress():
    runs = [
        ("2026-10-15", "Genie (genied), final regression", None, {"passed": 238, "total": 240, "mode3": {"min": 2.4, "median": 3.5, "max": 53.0},
                                                                    "fail_classes": {"thermal": 2}}, [ROOT / "ppt.md", hb_section("2.31")]),
    ]
    logs = [("htpd first app run (chaos only)", PROOFS / "2026-10-16_htpd_app_chaos.log"),
            ("htpd full stress", PROOFS / "2026-10-16_htpd_app_stress_full.log"),
            ("htpd v3 (chaos only)", PROOFS / "2026-10-16_htpd_v3_app_chaos.log"),
            ("htpd v4", PROOFS / "2026-10-16_htpd_v4_app.log"),
            ("htpd v5 + prefix cache", PROOFS / "2026-10-16_htpd_v5pc_app_stress.log"),
            ("htpd v6 (final)", PROOFS / "2026-10-16_htpd_v6_app_stress_tail.log")]
    for name, p in logs:
        when = dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
        runs.append((when, name, p, parse_log(p), [p]))
    runs.append(("2026-10-16", "report-page build (htpd v6)", None, {"passed": 133, "total": 135, "fail_classes": {"thermal": 2}, "mode3": None},
                 [hb_section("2.38")]))
    runs.append(("2026-10-16", "refinement build (htpd v6, clock resets)", None, {"passed": 129, "total": 135, "fail_classes": {"thermal": 6}, "mode3": None},
                 [RR / "DEVICE_RESULTS.md"]))
    pts, med, rows = [], [], []
    srcs = set()
    for when, name, p, r, s in runs:
        pts.append(pt(f"{when} {name}", **rate(r["passed"], r["total"]), fail_classes=r["fail_classes"]))
        if r.get("mode3"):
            med.append(pt(f"{when} {name}", r["mode3"]["median"], min=r["mode3"]["min"], max=r["mode3"]["max"], n=r["mode3"].get("n")))
        rows.append([when, name, r["passed"], r["total"], json.dumps(r["fail_classes"]),
                     r["mode3"]["median"] if r.get("mode3") else None])
        for x in s:
            srcs.add(x if isinstance(x, str) else rel(x))
    write(T, "ux_stress_runs", "App stress tests through the real app API, every run", "fraction",
          [ser("checks passed", pts, "ours")], sorted(srcs) + [APP / "tools/stress_app.py"], S,
          chart={"type": "line", "x": "run"}, claim="132/135 on the final htpd build; every failure is heat",
          why="We test the way an operator uses it: random sliders, faults, chaos, operator actions.",
          notes="Runs with 34 checks are chaos-only. 'Harness check' failures were a stale test (it looked for genied, not htpd) and "
                "were fixed in the harness, not the app. Thermal = board above 80 C or guard tripped at chaos peaks (95-96 C).",
          table={"columns": ["when", "run", "passed", "total", "failures by class", "Mode 3 median s"], "rows": rows})
    write(T, "ux_mode3_latency_runs", "Mode 3 analysis time across stress runs (median, min-max)", "s",
          [ser("median", med, "ours")], sorted(srcs), S, chart={"type": "boxplot"},
          notes="min/max on each point. Chaos incidents (10-13 agents) set the max.")
    ch = []
    for when, name, p, r, s in runs:
        for i, (nag, sec_) in enumerate(r.get("chaos") or []):
            ch.append(pt(f"{name} #{i + 1}", sec_, agents=nag, when=when))
    ch.append(pt("Genie (2.31) chaos 13 agents", 48.9, agents=13, when="2026-10-15"))
    ch.append(pt("Genie (2.31) chaos 9 agents", 40.8, agents=9, when="2026-10-15"))
    write(T, "ux_chaos_incidents", "Chaos: every sensor failing at once, one incident, analysis time", "s",
          [ser("chaos incidents", ch, "ours")], [PROOFS / "2026-10-16_htpd_app_chaos.log", PROOFS / "2026-10-16_htpd_v4_app.log",
                                                  PROOFS / "2026-10-16_htpd_v6_app_stress_tail.log", hb_section("2.31")], S,
          chart={"type": "scatter", "x": "agents", "y": "s"}, claim="10-12 agents + synthesizer in ~21 s (Genie: 40.8-48.9 s)",
          why="A whole-campus failure still gets one explained report in about 20 s.")
    rep = read_json(PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json")
    sec = {}
    for r in rep["results"]:
        k = r["check"].split(":")[0]
        k = re.sub(r" #\d+", "", k)
        grp = "Mode 3 scenarios" if k.startswith("M3") else "Mode 2 scenarios" if k.startswith("M2") else k
        a = sec.setdefault(grp, [0, 0])
        a[1] += 1
        a[0] += bool(r["ok"])
    fails = [r["check"] for r in rep["results"] if not r["ok"]]
    write(T, "ux_v6_final_checks", "Final htpd v6 app stress run: checks per section", "fraction",
          [ser("passed", [pt(k, **rate(v[0], v[1])) for k, v in sec.items()], "ours")],
          [PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json"], S, n=len(rep["results"]),
          notes="Failed: " + "; ".join(fails))
    m2, m3 = {}, {}
    for inc in rep["incidents"]:
        tag = inc["tag"]
        if tag.startswith("M2 "):
            m2[tag[3:]] = inc
        elif tag.startswith("M3 "):
            m3[tag[3:]] = inc
    scen = [s for s in m3 if s in m2]
    import statistics
    med3 = statistics.median(m3[s]["total_ms"] for s in scen) / 1000
    med2 = statistics.median(m2[s]["total_ms"] for s in scen) / 1000
    write(T, "ux_mode2_vs_mode3_latency", "Same scenarios through the app: Mode 2 (one call) vs Mode 3 (agents) analysis time, htpd v6", "s",
          [ser("Mode 3 multi-agent", [pt(s, m3[s]["total_ms"] / 1000, npu_calls=m3[s]["npu_calls"], agents=len(m3[s]["agents"])) for s in scen], "ours"),
           ser("Mode 2 single call", [pt(s, m2[s]["total_ms"] / 1000, npu_calls=m2[s]["npu_calls"]) for s in scen], "alt")],
          [PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json"], S, n=len(scen), chart={"type": "bar"},
          claim="Mode 3 is not slower than one big call: median %.1f s vs %.1f s" % (med3, med2),
          why="Per-sensor agents give checkable evidence at no extra wait.",
          notes="One run each; latency only (no accuracy grid for Mode 2 vs 3 yet). Median of %d scenarios: Mode 3 %.2f s vs Mode 2 %.2f s." % (
              len(scen), med3, med2),
          extra={"policy_valid": {"mode3_agents_valid": sum(a["valid"] for s in scen for a in m3[s]["agents"]),
                                  "mode3_agents_total": sum(len(m3[s]["agents"]) for s in scen)}})
    labels = {"ventilation_failure": "Ventilation failure", "pm_spike": "Outdoor pollution spike",
              "power_throttling": "Power throttling", "load_surge": "Power load surge",
              "tank_leak": "Tank leak", "pump_cycling": "Pump cycling",
              "stuck_sensor": "Stuck sensor", "heat_buildup": "Heat buildup",
              "off_hours_presence": "Off-hours presence", "crowded_room": "Crowded room"}
    rows = []
    for name, incident in m3.items():
        report = incident.get("report") or {}
        agent = (incident.get("agents") or [{}])[0]
        rows.append(pt(labels.get(name, name), incident["total_ms"] / 1000,
                       pattern=agent.get("pattern"), diagnosis=report.get("label"),
                       operator_action=report.get("action"), agents=len(incident.get("agents") or []),
                       npu_calls=incident.get("npu_calls")))
    write(T, "ux_scenario_outcomes", "Measured situations through the final app: diagnosis and operator-ready action", "s",
          [ser("Mode 3 completed incident", rows, "ours")],
          [PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json"], S, n=len(rows), chart={"type": "table"},
          claim="10 measured situations: a completed, policy-checked incident for each",
          why="It shows what an operator receives for concrete campus situations, not just aggregate accuracy.",
          notes="One measured Mode 3 run per situation on the QIDK. This is scenario coverage and latency, not a statistically powered accuracy comparison.")


def faults_and_ui():
    rows = [["kill -9 genied mid-answer", "EOF read as a normal end; truncated text answered, policy rejected",
             "error detected; CLI re-runs the call with the streamed prefix held back (valid answer, 4.9 s); genied back in <= 15 s"],
            ["kill -9 edge-agent", "-", "watchdog restarts it in 8 s; incidents intact; one genied"],
            ["kill backend mid-analysis", "running incident vanished (persisted only at the end)",
             "persisted at creation; reloads as 'failed'; approve refused (409), rerun allowed"],
            ["torn last line in incidents.jsonl", "newer line glued to the torn one", "skipped, logged, store compacted on load"],
            ["cold reboot", "-", "backend and NPU daemon answering ~5 s after boot completes; incidents intact"],
            ["stale abort byte", "next query (synthesizer) returned 0 tokens", "abort tied to query id; zero-token query retried once"],
            ["garbage input (NaN, strings, absurd values)", "-", "rejected (400) or clamped, never a crash (9/9 checks)"]]
    write(T, "ux_fault_injection", "Fault injection on the device: before vs after the fixes", "s",
          [ser("recovery time", [pt("kill edge-agent -> restarted", 8), pt("kill genied -> daemon back", 15), pt("cold boot -> answering", 5),
                                 pt("NPU call completed on CLI after daemon kill", 4.9)], "ours")],
          [hb_section("2.35"), ROOT / "ppt.md", PROOFS / "2026-10-16_htpd_app_stress_full.log"], S, chart={"type": "bar"},
          table={"columns": ["injected", "before", "now"], "rows": rows})
    ch = read_json(UX / "checks.json")
    screens = [c for c in ch if isinstance(c, dict) and "scrollW" in c]
    write(T, "ux_report_page_checks", "Report page at phone width: layout and accessibility checks", "px",
          [ser("document scroll width (viewport 360)", [pt(c["what"], c["scrollW"], overflowing=len(c["overflowing"])) for c in screens], "ours")],
          [UX / "checks.json", UX / "notes.txt", hb_section("2.38")], S, n=len(screens),
          notes="Also checked: focus moves to the sheet close button and back, history.back() closes the sheet, backdrop tap closes it, "
                "no console errors. Severity colours also carry a bar, glyph and label (not colour alone).")
    before = sorted(SHOTS.glob("*.png"))
    after = sorted(UX.glob("*.png")) + sorted((UX / "device").glob("*.png"))
    refine = sorted(RR.glob("*.png"))
    write(T, "ux_screenshots", "Screenshot index: UI before (2026-10-14) and after (2026-10-16), refinement screens", "files",
          [ser("before (DeerFlow-era UI, 2026-10-14)", [pt(p.name, 1, path=rel(p)) for p in before], "alt"),
           ser("after: report page (2026-10-16)", [pt(p.name, 1, path=rel(p)) for p in after], "ours"),
           ser("refined re-analysis screens (2026-10-16)", [pt(p.name, 1, path=rel(p)) for p in refine], "ours")],
          [SHOTS, UX / "notes.txt", RR / "notes.txt"], S, n=len(before) + len(after) + len(refine),
          notes="Paths for the page agents to embed (encrypted at build). 'after' and refinement shots come from a laptop host backend "
                "with mock agents (no NPU); some are synthetic states (see notes.txt). Screens may show demo slider values, not "
                "dataset series. device/d0_current.png is a photo of the QIDK screen.",
          extra={"images": {"before": [rel(p) for p in before], "after": [rel(p) for p in after], "refine": [rel(p) for p in refine]}})
    write(T, "ux_severity_from_reasoner", "Severity follows the reasoner: list colours after the back-fill (stored incidents)", "incidents",
          [ser("list rows on the real stored incidents", [pt("Fine", sum(1 for x in ch[1] if x.endswith("Fine"))),
                                                        pt("Warning", sum(1 for x in ch[1] if x.endswith("Warning")))], "ours")],
          [UX / "checks.json", UX / "notes.txt", hb_section("2.38")], S,
          notes="Before: severity was fixed by the rules at creation, so agents saying 'normal' still left an incident 'critical' "
                "(e.g. INC-0031 critical -> normal after back-fill). Mock agents answer normal, so most rows become Fine.")


def main():
    stress(); faults_and_ui()


if __name__ == "__main__":
    main()
