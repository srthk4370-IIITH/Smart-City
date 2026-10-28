"""Refinement datasets: early alert + refined re-analysis at 1.5 h / 3 h (device runs), Go tests, UI checks."""
from _lib import *

S = __file__
T = "refinement"
RR = PROOFS / "2026-10-16_refined_reanalysis"
STAGES = ["early", "1.5h", "3h"]


def runs():
    rows = []
    for run, d in (("run 1 (before 12 h severity rule)", "device"), ("run 2 (12 h finding raises severity)", "device_run2"),
                   ("run 3 (keep worst severity, scenarios hold)", "device_run3")):
        for r in read_jsonl(RR / d / "refine_check.jsonl"):
            s = r["sensors"][0] if r["sensors"] else {}
            rows.append({"run": run, "scenario": r["scenario"], "incident": r["incident"], "stage": r["stage"],
                         "severity": r["severity"], "agent_pattern": s.get("pattern"), "agent_status": s.get("status"),
                         "long_range_fired": bool(s.get("long_range")), "t_since_inject_s": r["t_since_inject_s"],
                         "early_analysis_ms": r["total_ms"], "revisions": r["revisions"]})
    tab_cols = list(rows[0].keys())
    reached = {}
    for r in rows:
        reached.setdefault((r["run"], r["incident"]), set()).add(r["stage"])
    n_inc = len(reached)
    n_full = sum(1 for v in reached.values() if v >= set(STAGES))
    sev_rank = {"normal": 0, "sensor_fault": 1, "warning": 2, "critical": 3}
    series = []
    for run in sorted({r["run"] for r in rows}):
        pts = [pt(f'{r["scenario"]} @ {r["stage"]}', sev_rank.get(r["severity"], None), severity=r["severity"],
                  pattern=r["agent_pattern"], long_range=r["long_range_fired"]) for r in rows if r["run"] == run]
        series.append(ser(run, pts, "ours" if "run 3" in run else "alt"))
    write(T, "ref_device_runs", "Refined re-analysis through the app on the QIDK: findings per stage (3 runs, 9 incidents)",
          "severity rank (0 normal, 1 fault, 2 warning, 3 critical)", series,
          [RR / "device/refine_check.jsonl", RR / "device_run2/refine_check.jsonl", RR / "device_run3/refine_check.jsonl",
           RR / "DEVICE_RESULTS.md", hb_section("2.39")], S, n=n_inc, chart={"type": "timeline"},
          claim="power_throttling: early 'exponential increase' -> refined 'throttling' (correct)",
          why="The early alert stays fast; the refined read uses the window where the agent is accurate (placement study).",
          notes=f"{n_full}/{n_inc} incidents reached the 3 h stage. Stages ~15-18 s apart at 1 s polls. Run 1 exposed a gap: a 12 h "
                "slow drift (tank leak) did not raise severity; fixed in run 2 (longRangeRaise). 12 h checks need 8 h of history.",
          table={"columns": tab_cols, "rows": [list(r.values()) for r in rows]})
    # stage timing at 2 s polls (mock backend, laptop)
    t = []
    for line in text(RR / "inc0001_stage_poll_2s.log").splitlines():
        m = re.match(r'(\d\d:\d\d:\d\d) .*"refine_stage":"([^"]*)".*"state":"(\w+)"', line)
        if m:
            t.append((m.group(1), m.group(2), m.group(3)))
    first = {}
    for ts, st, state in t:
        if state == "done" and st and st not in first:
            first[st] = ts
    def sec(ts):
        h, m_, s_ = map(int, ts.split(":"))
        return h * 3600 + m_ * 60 + s_
    base = sec(first["early"])
    write(T, "ref_stage_timing", "Demo timing at 2 s polls: when each refined report lands after the early one", "s",
          [ser("seconds after the early report", [pt(st, sec(ts) - base) for st, ts in first.items()], "ours")],
          [RR / "inc0001_stage_poll_2s.log", RR / "notes.txt"], S, chart={"type": "bar"},
          notes="Laptop host backend with a mock LLM (no NPU). HANDBOOK: refinements land ~36 s and ~72 s after the alert at 2 s polls.")
    go = text(RR / "go_test_output.txt")
    tests = re.findall(r"--- (PASS|FAIL): (\w+) \(([\d.]+)s\)", go)
    write(T, "ref_go_tests", "Refinement unit tests (Go, -race, real engine + scripted mock agents)", "s",
          [ser("test duration", [pt(name, float(dur), status=st) for st, name, dur in tests], "ours")],
          [RR / "go_test_output.txt"], S, n=len(tests),
          notes=f"{sum(1 for x in tests if x[0] == 'PASS')}/{len(tests)} refine tests pass; full suite: " +
                ("ok" if "ok  \tedgeagent" in go else "see file") + ". Covered: due at +18/+36 readings, spike kept when event over, "
                "approval and gate untouched, never pre-empts a new incident, persistence and back-compat.")
    ch = read_json(RR / "checks.json")
    screens = [c for c in ch if isinstance(c, dict) and "scrollW" in c]
    write(T, "ref_ui_checks", "Refinement UI at phone width (360 px): no horizontal overflow on any screen", "px",
          [ser("document scroll width", [pt(c["what"], c["scrollW"], overflowing=len(c["overflowing"])) for c in screens], "ours")],
          [RR / "checks.json", RR / "notes.txt"], S, n=len(screens),
          notes="Headless Chrome over CDP at 360x780 @2x; no console errors. Badge sequence EARLY -> REFINED 1.5 h -> REFINED 3 h "
                "appeared on an open page without reload (SSE).",
          extra={"screenshots": [rel(p) for p in sorted(RR.glob("*.png"))]})


def main():
    runs()


if __name__ == "__main__":
    main()
