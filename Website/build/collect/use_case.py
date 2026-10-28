"""Use-case datasets: what the system is for, in numbers. Breach statistics are aggregated from
Website/data/raw (written by rawdata.py): counts per month/domain only, no readings."""
import datetime as dt
from _lib import *

S = __file__
T = "use_case"
RAW = DATA / "raw"
WS = PROOFS / "2026-10-16_window_study"
V6 = PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json"
GATE_READINGS = 8          # event gate: abnormal for 8 consecutive readings
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def raw_index():
    return read_json(RAW / "index.json")


def breaches():
    idx = raw_index()
    dom_of = {s["id"]: s["domain"] for s in idx["sensors"]}
    lab = {d["id"]: d["label"] for d in idx["domains"]}
    mt = idx["month_t0"]
    t0 = idx["year_t0"]
    step = idx["step"]
    per_month = {}           # (domain, month) -> [all, crit]
    per_dom = {}             # domain -> counters
    for f in sorted((RAW / "s").glob("*.json")):
        d = read_json(f)
        dom = dom_of.get(d["id"], "other")
        for b in d.get("breaches", []):
            metric, s0, s1, peak, level = b[0], b[1], b[2], b[3], b[4]
            ts = t0 + s0 * step
            m = max(i for i in range(12) if mt[i] <= ts)
            a = per_month.setdefault((dom, m), [0, 0])
            a[0] += 1
            a[1] += level == "crit"
            readings = s1 - s0 + 1
            c = per_dom.setdefault(dom, {"all": 0, "crit": 0, "gated": 0, "crit_gated": 0})
            c["all"] += 1
            c["crit"] += level == "crit"
            c["gated"] += readings >= GATE_READINGS
            c["crit_gated"] += (level == "crit") and readings >= GATE_READINGS
    return idx, lab, per_month, per_dom


def main():
    idx, lab, per_month, per_dom = breaches()
    tot = idx["totals"]
    src_raw = [RAW / "index.json", "Website/data/raw/s/*.json (breach lists, aggregated)", WEB / "build/collect/rawdata.py"]
    # 1 coverage
    read_per_dom = {}
    for s in idx["sensors"]:
        read_per_dom[s["domain"]] = read_per_dom.get(s["domain"], 0) + sum(m.get("n", 0) for m in s.get("metrics", []))
    write(T, "uc_coverage", "What the system watches: IIIT-H campus sensors, 2025", "sensors",
          [ser("sensors", [pt(d["label"], d["n"], readings=read_per_dom.get(d["id"])) for d in idx["domains"]], "ours"),
           ser("readings (millions)", [pt(d["label"], round(read_per_dom.get(d["id"], 0) / 1e6, 2)) for d in idx["domains"]], "alt", unit="million readings")],
          src_raw, S, n=tot["sensors"], chart={"type": "bar"},
          claim=f"{tot['sensors']} sensors, {tot['readings'] / 1e6:.1f} M readings, 8 domains, 12 months",
          why="A campus produces more readings than any person can watch; the system watches them all on one board.",
          notes="A reading = one metric value at one 5-min slot after cleaning. One CSV row can hold several metrics and some rows are "
                "dropped as out-of-range, so readings (33.2 M) and raw CSV rows (~37 M) differ.",
          extra={"totals": tot})
    # 2 breaches per month
    doms = sorted({d for d, _ in per_month}, key=lambda d: -sum(v[0] for (dd, _), v in per_month.items() if dd == d))
    write(T, "uc_breaches_monthly", "Threshold breaches per month and domain (2025, real data)", "breaches",
          [ser(lab.get(d, d), [pt(MONTHS[m], per_month.get((d, m), [0, 0])[0], critical=per_month.get((d, m), [0, 0])[1]) for m in range(12)],
               "alt") for d in doms],
          src_raw, S, n=tot["breaches"], chart={"type": "stackedBar", "x": "month"},
          claim=f"{tot['breaches']:,} warning/critical breaches in a year, {tot['breaches_crit']:,} critical",
          why="This is the alert flood a threshold system hands an operator.",
          notes="A breach = one contiguous run above a warning or critical limit on one metric. Aggregated counts only.")
    # 3 how many need action
    keys = sorted(per_dom, key=lambda d: -per_dom[d]["all"])
    write(T, "uc_breaches_need_action", "How many breaches deserve attention: all vs lasting >= 8 readings (40 min) vs critical", "breaches",
          [ser("all breaches", [pt(lab.get(d, d), per_dom[d]["all"]) for d in keys], "alt"),
           ser(f"lasting >= {GATE_READINGS} readings (pass the event gate)", [pt(lab.get(d, d), per_dom[d]["gated"]) for d in keys], "ours"),
           ser("critical and lasting", [pt(lab.get(d, d), per_dom[d]["crit_gated"]) for d in keys], "ref")],
          src_raw, S, n=sum(v["all"] for v in per_dom.values()), chart={"type": "bar"},
          claim=f"{sum(v['all'] for v in per_dom.values()):,} breaches -> {sum(v['gated'] for v in per_dom.values()):,} persistent -> "
                f"{sum(v['crit_gated'] for v in per_dom.values()):,} persistent and critical",
          notes="Persistence uses the app's own gate (8 consecutive readings). On the raw 5-min data that is 40 min; in the demo clock it is ~16 s.",
          extra={"per_domain": {lab.get(d, d): v for d, v in per_dom.items()}})
    # 4 alert reduction (status quo vs ours, same windows)
    ws = read_json(WS / "summary.json")["lengths"]["48"]
    write(T, "uc_alert_reduction", "Status quo (threshold rules) vs our agents on the same real windows", "fraction",
          [ser("threshold rules (status quo)", [pt("detects injected events", **_r(ws["rules_detection_all_events"])),
                                                pt("false alarms on calm windows", **_r(ws["rules_false_alarm_clean"]))], "alt"),
           ser("event gate + fine-tuned agents", [pt("detects injected events", **_r(ws["detection_all_events"])),
                                                 pt("false alarms on calm windows", **_r(ws["false_alarm_clean"]))], "ours")],
          [WS / "summary.json", WS / "RESULTS.md", hb_section("4.1")], S, n=364, chart={"type": "bar"},
          claim="Same detection (78%), false alarms 43% -> 27%",
          why="Fewer false alarms at equal detection is what makes operators trust and act on alerts.",
          notes="4 h windows from the held-out test months, QIDK NPU. Event gate: 2,000 calm readings produced 0 incidents; a 90 s "
                "random drift in the stress test raised none.",
          extra={"event_gate_calm_readings": 2000, "event_gate_incidents": 0})
    # 5 time to insight
    write(T, "uc_time_to_insight", "Time from alert to an explained, evidence-cited report (QIDK, through the app)", "s",
          [ser("before (Genie)", [pt("12-sensor chaos incident", 47), pt("13 agents (A/B)", 23.5), pt("typical incident (median)", 3.8)], "alt"),
           ser("now (htpd v6)", [pt("12-sensor chaos incident", 20.7), pt("13 agents (A/B)", 14.7), pt("typical incident (median)", 3.8)], "ours"),
           ser("threshold rules", [pt("typical incident (median)", 0.001)], "ref")],
          [hb_section("2.37"), PROOFS / "2026-10-16_htpd_ab/RESULTS.md", PROOFS / "2026-10-16_htpd_v6_app_stress_tail.log"], S, chart={"type": "bar"},
          claim="An explained report in ~4 s typically, 21 s when 12 sensors fail at once",
          why="Rules alert instantly but explain nothing; the agents explain within seconds, on the board.",
          notes="Genie chaos value is the midpoint of 46-48 s. Refined re-reads land +1.5 h and +3 h later in sensor time (~37 s and ~74 s "
                "on the 2 s demo clock). First token in ~0.3 s with a resident model.")
    # 6 edge / offline
    write(T, "uc_edge_offline", "Runs on the edge: everything on one QIDK board, no cloud", "s",
          [ser("one agent call on the board", [pt("NPU (genied)", 2.543), pt("NPU (htpd, 13 in one batch, per agent)", round(14.7 / 13, 2)),
                                                pt("GPU (Adreno, 1 agent)", 10.01)], "ours"),
           ser("bytes leaving campus per incident", [pt("ours", 0)], "ref", unit="bytes")],
          [hb_section("2.24"), PROOFS / "2026-10-16_htpd_ab/RESULTS.md", PROOFS / "2026-10-16_hw_grid/samples.jsonl", ROOT / "problems_setup.md", hb_section("4.4")], S,
          chart={"type": "bar"}, claim="Sensor data, AI inference, safety checks and storage all stay on the board",
          why="Works with no internet; no campus data (e.g. room occupancy) leaves the site.",
          notes="The app reaches the NPU through the board's own adbd (Android apps cannot open it directly). Board idle ~43 C; chaos "
                "peaks 95-96 C (heatsink advised). Energy per incident has not been measured (no free power rail).")
    # 7 human in the loop
    v6 = read_json(V6)
    m3 = [i for i in v6["incidents"] if i["tag"].startswith(("M3", "chaos"))]
    nag = sum(len(i["agents"]) for i in m3)
    nval = sum(1 for i in m3 for a in i["agents"] if a.get("valid"))
    write(T, "uc_human_in_loop", "Safety: every answer is checked, nothing is actuated, a person decides", "fraction",
          [ser("our system", [pt("agent answers passing the policy gate (app, v6)", **rate(nval, nag)),
                              pt("evidence ids valid (host eval)", **rate_from(1.0, 150)),
                              pt("actions executed without approval", 0)], "ours"),
           ser("base model, no fine-tune", [pt("evidence ids valid (host eval)", **rate_from(0.347, 150))], "alt")],
          [V6, TRAIN / "results/agents_20261006_2101/eval.json", hb_section("2.33"), hb_section("2.28")], S, n=nag, chart={"type": "bar"},
          claim="100% of agent answers pass the gate; 0 automatic actions",
          why="Operators approve or dismiss every recommendation; their verdicts become training data (SFT/DPO).",
          notes="The policy gate checks JSON, whitelisted labels, real evidence ids and forbids actuation. A dismissal needs a note. "
                "The first approved incident produced 2 SFT positives and 1 DPO pair.")
    # 8 cross-domain
    rows = []
    for i in v6["incidents"]:
        if i["tag"].startswith(("M3 crowded", "chaos")):
            roles = sorted({a["role"] for a in i["agents"]})
            rows.append(pt(i["tag"], len(roles), agents=len(i["agents"]), npu_calls=i["npu_calls"], total_s=i["total_ms"] / 1000,
                           label=(i.get("report") or {}).get("label"), report_valid=(i.get("report") or {}).get("valid")))
    names = [r for r in v6["results"] if "names several domains" in r["check"]]
    write(T, "uc_cross_domain", "Cross-domain incidents: one report across several domains (Mode 3, QIDK)", "domains",
          [ser("domains examined by NPU agents", rows, "ours")], [V6], S, n=len(rows), chart={"type": "bar"},
          claim=f"All {len(rows)} multi-sensor incidents span 2-4 domains in one report",
          why="Real causes cross domains: a crowded room raises CO2, power and cooling together.",
          notes="Each point is one incident from the final app stress run; y = distinct domains among its NPU agents, plus a synthesizer "
                f"report with one root-cause label. App check 'names several domains' passed {sum(r['ok'] for r in names)}/{len(names)} (chaos runs only). Independent root-cause ground truth (cross-domain injections) is planned.")
    # 9 example incident walk-through
    write(T, "uc_example_incident", "One incident end to end: crowded room (CO2 + power), as measured", "s",
          [ser("phase", [pt("abnormal for 8 readings (event gate)", 16.0), pt("batch window (2 sensors)", 4.0),
                         pt("2 NPU domain agents", 7.112), pt("synthesizer root cause", 4.457), pt("app overhead", 0.011)], "ours")],
          [hb_section("2.29"), hb_section("4.1")], S, chart={"type": "waterfall"},
          claim="From first abnormal reading to an approved-ready report in ~32 s of demo time",
          notes="Genie/genied-era trace (HANDBOOK 2.29); on htpd v6 the same scenario's analysis took 7.5 s (3 NPU calls). Gate time at "
                "2 s polls. Then the operator approves or dismisses; refinements re-read at +1.5 h and +3 h.")


def _r(d):
    lo, hi = d["ci95"]
    return {"y": d["rate"], "k": d["k"], "n": d["n"], "lo": lo, "hi": hi, "ci_method": "wilson95"}


if __name__ == "__main__":
    main()
