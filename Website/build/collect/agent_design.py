"""Agent-design datasets: window-length study, placement study, long-range detectors, daily baseline,
modes 1/2/3, event gate, disagreement handling."""
from _lib import *

S = __file__
T = "agent_design"
WS = PROOFS / "2026-10-16_window_study"
PS = PROOFS / "2026-10-16_placement_study"
LR = PROOFS / "2026-10-16_longrange"
DB = PROOFS / "2026-10-16_daily_baseline"
LEN = {"24": "2 h", "48": "4 h", "96": "8 h", "144": "12 h"}
DLY = {4: "20 min", 8: "40 min", 12: "1 h", 18: "1.5 h", 24: "2 h", 36: "3 h"}


def _r(d, **kw):
    lo, hi = d["ci95"]
    out = {"y": d["rate"], "k": d["k"], "n": d["n"], "lo": lo, "hi": hi, "ci_method": "wilson95"}
    out.update(kw)
    return out


def parse_pairs(path, pat):
    rows = []
    for line in text(path).splitlines():
        m = re.search(pat, line)
        if m:
            rows.append(m.groupdict())
    return rows


def window_study():
    sm = read_json(WS / "summary.json")
    L = sm["lengths"]
    src = [WS / "summary.json", WS / "RESULTS.md", WS / "tables.md", WS / "manifest.json", hb_section("2.38")]
    mets = [("pattern_acc", "pattern accuracy"), ("status_acc", "status accuracy"), ("cause_acc", "cause accuracy"),
            ("detection_all_events", "detection, injected events"), ("false_alarm_clean", "false alarms, calm windows")]
    series = [ser(lbl, [pt(LEN[n], **_r(L[n][m])) for n in LEN], "ours" if m == "pattern_acc" else "alt") for m, lbl in mets]
    write(T, "ad_window_headline", "Window length study: 2, 4, 8, 12 h windows, same model on the QIDK NPU (604 cases x 4)",
          "fraction", series, src, S, n=369, chart={"type": "line", "x": "window length", "highlight_x": "4 h"},
          claim="4 h is the best single window: pattern 64% vs 42-56% elsewhere",
          why="The window decides what the agent can see; it was trained on 4 h, so other lengths lose accuracy.",
          notes="2416 NPU calls (htpd v6, greedy). Pattern/status/cause n=369 labelled cases; detection n=364 injected events; "
                "false alarms n=77 calm windows whose truth is normal. Real calm data holds real events, so false alarms are "
                "over-counted (strict clean subset n=19: 5/5/0/0%).")
    fam = [("step_old", "old step (2.5-8 h ago)"), ("drift_long", "slow drift (6-12 h)"), ("subthr_spikes", "recurring small spikes")]
    write(T, "ad_window_old_events", "What longer windows catch: old steps, long drifts, recurring small spikes (detection)",
          "fraction", [ser(lbl, [pt(LEN[n], **_r(L[n]["per_family"][f]["flag"])) for n in LEN], "alt") for f, lbl in fam],
          src, S, n=75, chart={"type": "line", "highlight_x": "4 h"},
          claim="12 h catches every old step (73% -> 100%) but misnames them",
          notes="At 12 h, 25 of 39 sub-threshold 'detections' are the agent calling the window flatline (a misreading).")
    write(T, "ad_window_rules_vs_agent", "Agent vs rules (Mode 1) on the same windows: detection and false alarms",
          "fraction",
          [ser("agent detection", [pt(LEN[n], **_r(L[n]["detection_all_events"])) for n in LEN], "ours"),
           ser("rules detection", [pt(LEN[n], **_r(L[n]["rules_detection_all_events"])) for n in LEN]),
           ser("agent false alarms", [pt(LEN[n], **_r(L[n]["false_alarm_clean"])) for n in LEN], "ours"),
           ser("rules false alarms", [pt(LEN[n], **_r(L[n]["rules_false_alarm_clean"])) for n in LEN]),
           ser("agent false alarms, strict clean", [pt(LEN[n], **_r(L[n]["false_alarm_clean_strict"])) for n in LEN], "ref")],
          src, S, n=364, chart={"type": "line", "highlight_x": "4 h"},
          claim="At 4 h the agent matches rule detection (78%) with fewer false alarms (27% vs 43%)",
          why="Status quo = threshold rules; the agent must not miss more while alarming less.")
    fams = [f for f in L["48"]["per_family"] if f not in ("clean_above_limit",)]
    hm = []
    for f in fams:
        for n in LEN:
            d = L[n]["per_family"][f]
            hm.append(pt(LEN[n], d["flag"]["rate"], family=f, k=d["flag"]["k"], n=d["flag"]["n"],
                         lo=d["flag"]["ci95"][0], hi=d["flag"]["ci95"][1],
                         pattern=(d["pattern"]["rate"] if "pattern" in d else None)))
    write(T, "ad_window_per_family", "Detection (flag) and pattern accuracy per case family and window length",
          "fraction", [ser("per family", hm, "ours")], src, S, chart={"type": "heatmap", "x": "window length", "y": "family", "value": "y"},
          notes="y = flagged rate; 'pattern' = pattern accuracy where the family has a pattern label. n per family 12-80.")
    rows = parse_pairs(WS / "paired_tests.txt",
                       r"^(?P<family>\S+(?:\(truth normal\))?)\s+(?P<metric>flag|pat)\s+48 vs\s+(?P<other>\d+): only48=\s*(?P<a>\d+) only\d+=\s*(?P<b>\d+)\s+n=(?P<n>\d+)\s+p=(?P<p>[\d.]+)")
    tab = [{"family": r["family"], "metric": "pattern" if r["metric"] == "pat" else "flag", "vs": LEN[r["other"]],
            "only_4h": int(r["a"]), "only_other": int(r["b"]), "n": int(r["n"]), "p_mcnemar": float(r["p"]),
            "p_exact_recomputed": binom_two_sided(int(r["a"]), int(r["b"]))} for r in rows]
    write(T, "ad_window_paired", "Paired McNemar tests: 4 h vs every other length (same cases)", "p-value",
          [ser("p (McNemar)", [pt(f'{t["family"]} {t["metric"]} vs {t["vs"]}', t["p_mcnemar"], n=t["n"]) for t in tab], "ref")],
          [WS / "paired_tests.txt", WS / "paired_tests.py"], S, n=169,
          table={"columns": list(tab[0].keys()), "rows": [list(t.values()) for t in tab]},
          claim="4 h beats every other length on pattern accuracy, p < 0.0001")
    cost = [ser("s per agent in a batch of 8", [pt(LEN[n], L[n]["latency"]["mean_s_per_call_in_batch"]) for n in LEN], "ours"),
            ser("prompt tokens (mean)", [pt(LEN[n], L[n]["latency"]["mean_prompt_tokens"]) for n in LEN], "alt", unit="tokens"),
            ser("output tokens (mean)", [pt(LEN[n], L[n]["latency"]["mean_output_tokens"]) for n in LEN], "alt", unit="tokens"),
            ser("prefill s per batch", [pt(LEN[n], L[n]["latency"]["mean_prefill_s"]) for n in LEN], "alt")]
    write(T, "ad_window_cost", "Cost of a longer window (htpd, batches of 8)", "seconds", cost, src, S, n=604,
          chart={"type": "bar", "highlight_x": "4 h"}, claim="8 h costs +18% per agent, 12 h +32%")
    var = [pt(LEN[n], L[n]["variety_real"]["distinct_pattern_status_cause"], n=L[n]["variety_real"]["n"],
              flagged=L[n]["variety_real"]["flagged"]["rate"]) for n in LEN]
    write(T, "ad_window_variety", "Variety of findings on 155 random real windows: distinct (pattern, status, cause)", "count",
          [ser("distinct outcomes", var, "ours")], src, S, n=155, chart={"type": "bar", "highlight_x": "4 h"})
    called = {LEN[n]: L[n]["per_family"]["subthr_spikes"]["called"] for n in LEN}
    write(T, "ad_window_subthr_called", "What the agent called recurring sub-threshold spikes (top labels)", "count",
          [ser(lbl, [pt(c[0], c[1]) for c in called[lbl]], "alt") for lbl in called], src, S, n=75,
          chart={"type": "stackedBar"}, notes="Mostly 'stable': the v1 model was never taught this pattern (fixed in retrain v2 data).")
    # per-sample scores (no inputs) for the data pack
    cases = {}
    for c in read_jsonl(WS / "cases.jsonl"):
        cases[c["id"]] = {"family": c["family"], "role": c["role"], "truth": c.get("truth")}
    rows = []
    for s in read_jsonl(WS / "samples.jsonl"):
        c = cases[s["id"]]
        p = parse_agent_json(s.get("text")) or {}
        t = c["truth"] or {}
        pat, st = p.get("pattern"), p.get("status")
        rows.append({"id": s["id"], "len": s["n"], "family": c["family"], "role": c["role"],
                     "pred_pattern": pat or "INVALID", "pred_status": st, "pred_cause": p.get("likely_cause"),
                     "gold_pattern": t.get("pattern"), "gold_status": t.get("status"),
                     "pattern_ok": (pat == t.get("pattern")) if t and c["family"] != "subthr_spikes" else None,
                     "flag": bool(p) and (st != "normal" or pat not in ("stable", "vacant", "occupied")),
                     "rule_pattern": s.get("rule"), "out_tokens": s.get("tokens"), "batch_s": s.get("batch_s")})
    return rows


def placement():
    sm = read_json(PS / "summary.json")
    A = sm["ALL"]
    src = [PS / "summary.json", PS / "RESULTS.md", PS / "tables.md", PS / "manifest.json", hb_section("2.39")]
    ser_ = [ser("agent pattern accuracy", [pt(DLY[d], **_r(A[str(d)]["pattern"])) for d in DLY], "ours"),
            ser("agent status accuracy", [pt(DLY[d], **_r(A[str(d)]["status"])) for d in DLY], "alt"),
            ser("flagged at all", [pt(DLY[d], **_r(A[str(d)]["flag"])) for d in DLY], "alt"),
            ser("rules pattern accuracy", [pt(DLY[d], **_r(A[str(d)]["rules_pattern"])) for d in DLY], "ref")]
    write(T, "ad_placement_curve", "When does the 4 h agent read an event right? Accuracy vs time since onset (208 events x 6)",
          "fraction", ser_, src, S, n=208, chart={"type": "line", "x": "time since onset", "highlight_x": "40 min"},
          claim="42% at 40 min (when the app asks) -> 88% at 3 h",
          why="The early alert is fast but reads young events poorly; this is why refinements at 1.5 h and 3 h exist.",
          notes="1248 NPU calls, htpd v6, real calm test-month windows, same event placed at 6 onsets (paired).")
    pats = [p for p in sm if p != "ALL"]
    hm = [pt(DLY[d], sm[p][str(d)]["pattern"]["rate"], pattern=p, k=sm[p][str(d)]["pattern"]["k"], n=sm[p][str(d)]["pattern"]["n"],
             lo=sm[p][str(d)]["pattern"]["ci95"][0], hi=sm[p][str(d)]["pattern"]["ci95"][1]) for p in pats for d in DLY]
    write(T, "ad_placement_heatmap", "Pattern accuracy per pattern and time since onset", "fraction",
          [ser("pattern accuracy", hm, "ours")], src, S, n=21, chart={"type": "heatmap", "x": "time since onset", "y": "pattern"},
          notes="n = 19-21 per cell; differences under ~20 points are within noise.")
    called = [pt(p, None, called_at_40min=sm[p]["8"]["called"], called_at_3h=sm[p]["36"]["called"]) for p in pats]
    write(T, "ad_placement_called", "What the agent says instead, at 40 min and at 3 h (top 3 labels per pattern)", "count",
          [ser("labels", called, "ref")], src, S, n=21)
    rows = parse_pairs(PS / "paired_tests.txt", r"only d=8:\s*(?P<a>\d+)\s+only d=\s*(?P<d>\d+):\s*(?P<b>\d+)\s+McNemar p=(?P<p>[\d.]+)")
    write(T, "ad_placement_paired", "Paired McNemar: 40 min vs every other onset (same 208 events)", "events",
          [ser("right only at 40 min", [pt(DLY[int(r["d"])], int(r["a"])) for r in rows], "alt"),
           ser("right only at the other onset", [pt(DLY[int(r["d"])], int(r["b"]), p_mcnemar=float(r["p"]), p_exact_recomputed=binom_two_sided(int(r["a"]), int(r["b"]))) for r in rows], "ours")],
          [PS / "paired_tests.txt"], S, n=208, chart={"type": "bar"},
          claim="At 3 h: 105 events right that were wrong at 40 min, only 9 the other way (p < 0.0001)")
    cases = {c["id"]: {"pattern": c["pattern"], "role": c["role"]} for c in read_jsonl(PS / "cases.jsonl")}
    rows = []
    for s in read_jsonl(PS / "samples.jsonl"):
        c = cases[s["id"]]
        p = parse_agent_json(s.get("text")) or {}
        rows.append({"id": s["id"], "delay_readings": s["n"], "role": c["role"], "gold_pattern": c["pattern"],
                     "pred_pattern": p.get("pattern") or "INVALID", "pred_status": p.get("status"),
                     "pattern_ok": p.get("pattern") == c["pattern"], "rule_pattern": s.get("rule"), "out_tokens": s.get("tokens")})
    return rows


def longrange():
    ev = read_json(LR / "evaluate_test.json")
    src = [LR / "evaluate_test.json", LR / "evaluate_test.md", LR / "RESULTS.md", LR / "params_final.json", hb_section("2.39")]
    arms = [("agent_4h", "agent 4 h (shipped)", "alt"), ("detectors_12h", "12 h detectors only", "ref"),
            ("agent_4h_or_detectors", "agent 4 h + 12 h detectors (shipped)", "ours"), ("agent_12h", "agent 12 h", "alt")]
    fams = [("detection_all_events", None, "all injected events"), ("false_alarm_clean", None, "false alarms, piecewise-calm"),
            (None, "step_old", "old step"), (None, "drift_long", "slow drift"), (None, "subthr_spikes", "recurring small spikes")]
    series = []
    for a, lbl, role in arms:
        pts = []
        for top, fam, xl in fams:
            d = ev[a][top] if top else ev["per_family"][fam][a]
            pts.append(pt(xl, **_r(d)))
        series.append(ser(lbl, pts, role))
    write(T, "ad_longrange_arms", "12 h CPU checks (level shift + slow drift) added to the 4 h agent: test months", "fraction",
          series, src, S, n=364, chart={"type": "bar"},
          claim="Old steps 73% -> 93%, drifts 83% -> 95%, no new false alarms",
          why="Without the 12 h check we miss about 1 in 4 old steps; with it, 1 in 14.",
          notes="Tuned on dev months (Sep-Oct) only, tested once on Nov-Dec. Agent answers are the real NPU outputs from the window study. "
                "Detectors fire on 10% (16/160) of random real windows.",
          extra={"detectors_on_real_windows": ev["detectors_on_real_windows"], "params": ev["params"]})
    hm = []
    for fam, arms_d in ev["per_family"].items():
        for a, lbl, role in arms:
            if a in arms_d:
                hm.append(pt(lbl, arms_d[a]["rate"], family=fam, k=arms_d[a]["k"], n=arms_d[a]["n"],
                             lo=arms_d[a]["ci95"][0], hi=arms_d[a]["ci95"][1]))
    write(T, "ad_longrange_per_family", "Long-range checks: detection per case family and arm", "fraction",
          [ser("detection", hm, "ours")], src, S, chart={"type": "heatmap", "x": "arm", "y": "family"})
    rows = parse_pairs(LR / "paired_combined.txt",
                       r"^(?P<f>\S+)\s+n=\s*(?P<n>\d+) agent4h-only=(?P<a>\d+) combined-only=(?P<b>\d+) McNemar p=(?P<p>[\d.]+)")
    write(T, "ad_longrange_paired", "Paired McNemar: agent alone vs agent + 12 h checks", "events",
          [ser("caught only with the 12 h checks", [pt(r["f"], int(r["b"]), n=int(r["n"]), p_mcnemar=float(r["p"]), p_exact_recomputed=binom_two_sided(int(r["a"]), int(r["b"]))) for r in rows], "ours"),
           ser("caught only by the agent alone", [pt(r["f"], int(r["a"]), n=int(r["n"])) for r in rows], "alt")],
          [LR / "paired_combined.txt"], S, n=75, chart={"type": "bar"}, claim="+12 old steps (p=0.0005), +7 drifts (p=0.016), 0 lost")
    # variants tried (dev + test, from ablation and RESULTS)
    abl = text(DB / "ablation_no_excursions.txt")
    var = []
    for line in abl.splitlines():
        m = re.match(r"(dev|test) (level\+slow_(?:\+recur)?) (\{.*\})", line)
        if m:
            d = eval(m.group(3), {"__builtins__": {}})
            for fam, v in d.items():
                mm = re.match(r"(\d+)% \((\d+)/(\d+)\)", v)
                var.append(pt(f'{m.group(1)} {fam}', **rate(int(mm.group(2)), int(mm.group(3))),
                              variant="level shift + drift + recurring excursions" if "recur" in m.group(2) else "level shift + drift (shipped)"))
    write(T, "ad_longrange_ablation", "Ablation: with vs without the recurring-excursion detector (dev and test months)", "fraction",
          [ser("level shift + drift + recurring excursions", [p for p in var if "recurring" in p["variant"]], "alt"),
           ser("level shift + drift (shipped)", [p for p in var if "shipped" in p["variant"]], "ours")],
          [DB / "ablation_no_excursions.txt", LR / "RESULTS.md"], S, n=120, chart={"type": "bar"},
          claim="Dropping the excursion check cuts dev false alarms 15% -> 2% with the same old-step catch",
          notes="Raw detectors on the 36 h daily-baseline case set. 'clean'/'real' = false-alarm/fire rates; others = detection.")
    dbt = read_json(DB / "evaluate_test.json")
    pts_raw, pts_daily = [], []
    for fam, d in dbt["per_family"].items():
        pts_raw.append(pt(fam, **_r(d["raw_12h"])))
        pts_daily.append(pt(fam, **_r(d["daily_baseline"]), kinds=d.get("daily_kinds")))
    write(T, "ad_daily_baseline_rejected", "Rejected: 'same hours yesterday' baseline vs raw 12 h detectors (test months)", "fraction",
          [ser("raw 12 h detectors", pts_raw, "ours"), ser("daily baseline (rejected)", pts_daily, "alt")],
          [DB / "evaluate_test.json", DB / "evaluate_test.md", DB / "params.json", ROOT / "proofs/2026-10-16_daily_baseline.dev.log"],
          S, n=80, chart={"type": "bar"},
          claim="Daily baseline: more false alarms (29% vs 20%), half the old steps (48% vs 86%)",
          why="Yesterday has its own events and noise; differencing adds them in instead of cancelling routine.",
          notes="Both detector sets incl. recurring excursions here; 'clean' and 'real' rows are false-alarm / fire rates.")
    # tuning grid frontiers
    fr = []
    for name, f, fpk, role in (("raw 12 h (daily_baseline set)", DB / "tune_grid_raw.jsonl", "fp", "ours"),
                               ("daily baseline", DB / "tune_grid_daily.jsonl", "fp", "alt"),
                               ("first raw grid (longrange set)", LR / "tune_grid.jsonl", "fp_clean", "ref")):
        g = read_jsonl(f)
        best = {}
        for r in g:
            fp = round(r[fpk], 2)
            v = max(r["tp_level_shift"], 0)
            if fp not in best or v > best[fp]:
                best[fp] = v
        pts, run = [], -1
        for fp in sorted(best):
            if best[fp] > run:
                run = best[fp]
                pts.append(pt(fp, run))
        fr.append(ser(name, pts, role, grid_size=len(g)))
    write(T, "ad_detector_tuning_frontier", "Detector tuning on dev months: best old-step catch for each false-alarm rate (Pareto front)",
          "fraction", fr, [DB / "tune_grid_raw.jsonl", DB / "tune_grid_daily.jsonl", LR / "tune_grid.jsonl", DB / "params.json", LR / "params.json"],
          S, chart={"type": "line", "x": "false-alarm rate on calm dev windows", "y": "level-shift true-positive rate"},
          notes="7680 parameter settings per grid. x = false-alarm rate (rounded to 0.01), y = best level-shift TP rate at that FP. "
                "The first grid found no setting under a 5% FP budget (params.json best_params null).")


def modes_and_gate():
    src = [hb_section("5"), hb_section("2.7")]
    write(T, "ad_modes_latency", "Mode 1 vs 2 vs 3: incident latency on the QIDK (Genie era, 2026-10-07)", "seconds",
          [ser("Mode 1 rules", [pt("any incident", 0.001)], "ref"),
           ser("Mode 2 single AI call", [pt("all sensors, 1 call", 9.0)], "alt"),
           ser("Mode 3 multi-agent, base model", [pt("tank leak (1 call)", 5.0), pt("ventilation failure (2 calls)", 18.7), pt("crowded room (4 calls)", 27.6)], "alt"),
           ser("Mode 3 multi-agent, fine-tuned", [pt("tank leak (1 call)", 5.6), pt("ventilation failure (2 calls)", 8.9), pt("crowded room (4 calls)", 23.5)], "ours"),
           ser("Compare rerun (exact-prompt cache)", [pt("rerun", 0.003)], "ref")],
          src, S, chart={"type": "bar"},
          notes="Single runs from the HANDBOOK (no CIs). Mode 1 '< 1 ms' plotted as 0.001 s. These are pre-genied/pre-htpd; "
                "current latency is in latency/*. A labelled Mode 1 vs 2 vs 3 accuracy grid (HANDBOOK 2.36 plan B) is not run yet.")
    write(T, "ad_event_gate", "Event gate: when the AI is called", "count",
          [ser("readings at rest -> incidents", [pt("2,000 calm readings", 0, n=2000)], "ours"),
           ser("stress 'quiet' phase", [pt("90 s random drift in band", 0)], "ours")],
          [hb_section("4.1"), PROOFS / "2026-10-16_htpd_app_stress_full.log"], S, n=2000,
          notes="Only warning/critical/fault status lasting 8 readings (~16 s at 2 s polls) calls the AI; everything alarming at "
                "about the same time is batched into one incident. Batch window: closes after 1 reading when no other sensor is "
                "abnormal-but-young (HANDBOOK 2.29).",
          table={"columns": ["rule", "value", "why"],
                 "rows": [["persist readings", 8, "agents were trained on events >= 7 readings old; younger windows were misread"],
                          ["poll", "2 s = 5 min sensor time", "demo clock"],
                          ["re-arm", "after return to normal", "one report per abnormal episode"],
                          ["agent cap", "none (was 3, then 8)", "every alarming sensor gets an NPU agent"]]})
    write(T, "ad_disagreement", "AI vs rules disagreement in stress tests (surfaced, not overridden)", "calls",
          [ser("agent said normal on a rule-flagged sensor", [pt("disagreements", 3, n=18)], "ours"),
           ser("who was right", [pt("rule right", 1), pt("AI right", 2)], "ref")],
          [ROOT / "ppt.md", hb_section("2.33")], S, n=18,
          notes="Rule right once (a missed pump oscillation); AI right twice (a CO2 episode already cleared). The report states the conflict.")
    write(T, "ad_review_answers", "Diagnosis matches the injected scenario (review_answers.py, Genie build)", "fraction",
          [ser("agent diagnoses", [pt("matching the injected scenario", **rate(8, 10))], "ours")],
          [ROOT / "ppt.md"], S, n=10,
          notes="Two misses were the water tank: one the scenario refilling itself (fixed), one a genuine miss (surfaced to the operator).")


def main():
    ws_rows = window_study()
    pl_rows = placement()
    longrange()
    modes_and_gate()
    return {"window_study_samples": ws_rows, "placement_samples": pl_rows}


if __name__ == "__main__":
    r = main()
    print({k: len(v) for k, v in r.items()})
