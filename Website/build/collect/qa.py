"""data/qa.json: professor-style questions with one-line answers, evidence ids and decision ids."""
from _lib import *

S = __file__


def Q(cat, q, a, ev, dec=None):
    return {"category": cat, "q": q, "short_answer": a, "evidence_ids": ev, "decision_id": dec}


QA = [
    # accuracy vs what
    Q("accuracy", "Against what did you measure accuracy?",
      "Exact labels from known patterns injected into real calm sensor windows of held-out months (Nov-Dec 2025), plus rules (Mode 1) and the base model on the same windows.",
      ["acc_v1_host_eval", "ds_v1_dataset", "ad_window_headline"], "D010"),
    Q("accuracy", "What is the headline accuracy?",
      "Pattern accuracy 94% fine-tuned vs 20% base vs 68% rules on 150 held-out windows (laptop); 90.7% on the QIDK NPU (n=54).",
      ["acc_v1_host_eval", "acc_device54_engines"], "D009"),
    Q("accuracy", "Is the comparison with the rules fair?",
      "For pattern on air, water, power and weather yes (92.5% vs 60.0%); occupancy labels and status/cause/action are circular, so we lead with pattern.",
      ["acc_v1_rules_vs_llm_fair", "acc_v1_host_per_role"], "D067"),
    Q("accuracy", "Is your 93% cause accuracy independent reasoning?",
      "No: cause labels come from the same teacher rules Mode 1 runs, so it shows the model imitates the taxonomy; independent 'why' truth needs cross-domain injections or facility logs.",
      ["acc_v1_rules_vs_llm_fair"], "D066"),
    Q("accuracy", "Why does accuracy matter here?",
      "A wrong pattern drives the wrong cause and action: LADE turned a stuck sensor into 'normal', which an operator would ignore.",
      ["lat_rejected_lade", "acc_action_derived"], "D037"),
    Q("accuracy", "Why is the device lower than the laptop?",
      "4-bit quantisation on the NPU plus a double-BOS prompt bug; GPTQ and the BOS fix took the device from 54% to 85%, and htpd to 91%.",
      ["acc_quant_waterfall", "acc_fakequant_host", "acc_device54_engines"], "D016"),
    Q("accuracy", "How big are your test sets and how wide are the CIs?",
      "150 windows on the laptop (+-~4 points), 54 on the device (+-~8-10), 604 cases x 4 lengths in the window study and 208 x 6 in the placement study; every chart shows Wilson 95% CIs.",
      ["acc_v1_host_eval", "acc_device54_engines", "ad_window_headline", "ad_placement_curve"], "D068"),
    Q("accuracy", "Is htpd really better than Genie, 90.7% vs 85.2%?",
      "Not significantly: paired McNemar p=0.45 on 54 windows; the claim is 'no worse while twice as fast'.",
      ["acc_device54_engines"], "D083"),
    Q("accuracy", "What happened to the 900-window device rerun?",
      "It stopped after 39 windows on a one-off socket stall at 91 C; the full rerun is still to do.",
      ["acc_test900_partial"]),
    Q("accuracy", "Do you have per-sample predictions?",
      "Yes for the device sets, window and placement studies (scores and labels, no inputs) in the data packs; the original laptop eval kept only aggregates.",
      ["acc_device54_engines", "ad_window_headline", "ad_placement_curve"], "D068"),
    # status quo
    Q("status quo", "Why is this better than the status quo (threshold alarms)?",
      "At the same detection rate (78% vs 78% at 4 h) the agent raises fewer false alarms (27% vs 43%) and explains each alert with cited evidence.",
      ["ad_window_rules_vs_agent", "ad_policy_gate"]),
    Q("status quo", "What do rules miss that the AI catches?",
      "Shape: rules name the pattern correctly 60% of the time on the fair roles vs 92.5% for the agent; with 12 h checks old steps 73% -> 93%.",
      ["acc_v1_rules_vs_llm_fair", "ad_longrange_arms"]),
    Q("status quo", "Why not send everything to a cloud LLM?",
      "Privacy (occupancy reveals presence), bandwidth, and it fails when the link does; everything here runs on the board with no internet.",
      ["ds_source_data", "hw_platform_paths"], "D069"),
    # why NPU / GPU
    Q("hardware", "Why the NPU and not the GPU?",
      "Same weights on the Adreno GPU: ~8.4 s per agent, no batching gain, slower than the NPU at every incident size.",
      ["hw_grid", "hw_gpu_batched"], "D073"),
    Q("hardware", "Did you try GPU + NPU together (hybrid)?",
      "Yes; hybrid placements were slower too, because both engines share the same LPDDR5X bandwidth.",
      ["hw_grid", "lat_bandwidth_roof"], "D073"),
    Q("hardware", "Do GPU answers match NPU answers?",
      "At ctx 4096 the GPU produced no valid JSON; at ctx 1024 pattern agreed in 8/12 agent calls; llama.cpp HTP agreed 22/26.",
      ["hw_grid_agreement"], "D071"),
    Q("hardware", "Why did the board reboot during GPU tests?",
      "GPU and NPU buffers are unmovable and must fit a 7.26 GB zone; the OOM killer picked system processes; the ladder now protects them.",
      ["hw_gpu_bringup_failures", "ops_incidents"], "D072"),
    Q("hardware", "Can the Android app use the NPU directly?",
      "No on this firmware (err 14001 in the sandbox); the app starts the backend as the shell user through the board's own adbd.",
      ["hw_platform_paths"], "D006"),
    # fine-tune
    Q("model", "Why fine-tune instead of prompting?",
      "The base model is 20% on pattern, cites invalid evidence 65% of the time and writes ~199 tokens; fine-tuned: 94%, 100% valid, 84 tokens.",
      ["acc_v1_host_eval", "acc_v1_output_tokens"], "D009"),
    Q("model", "Why Llama 3.2 3B?",
      "It fits the NPU memory budget with one resident model, has a Qualcomm reference export, and decodes ~22-25 tok/s on V75.",
      ["hw_memory", "lat_call_breakdown"], "D002"),
    Q("model", "Why one model for all roles?",
      "Two full models cannot be resident: loading a second 3B rebooted the board with 5.8 GB free.",
      ["hw_memory", "ad_reasoner_plan"], "D046"),
    # agent design
    Q("agent design", "Why multi-agent (Mode 3) instead of one call (Mode 2)?",
      "Each sensor gets a specialist reading of its own window with evidence ids the gate can check; on the final build Mode 3 is also not slower (median «m3» s vs «m2» s).",
      ["ux_mode2_vs_mode3_latency", "ad_modes_latency"], "D008"),
    Q("agent design", "Is Mode 3 more accurate than Mode 2?",
      "Not measured yet on a labelled grid; that comparison (600-incident grid) is planned, so we do not claim it.",
      ["ad_modes_latency"], "D066"),
    Q("agent design", "Why a 4-hour window?",
      "Measured: 4 h gives the best pattern accuracy (64% vs 46/56/42% at 2/8/12 h, p<0.0001) for the model trained on it.",
      ["ad_window_headline", "ad_window_paired"], "D084"),
    Q("agent design", "But longer windows catch old changes, why not 12 h?",
      "12 h catches old steps (100%) but misnames them, raises false alarms 27% -> 46% and costs +32%; cheap 12 h CPU checks give 93% without that.",
      ["ad_window_old_events", "ad_longrange_arms"], "D090"),
    Q("agent design", "When is the AI called?",
      "Only after a warning/critical/fault status lasts 8 readings (~16 s); 2,000 calm readings produced 0 incidents.",
      ["ad_event_gate"], "D021"),
    Q("agent design", "Why re-analyse at 1.5 h and 3 h?",
      "At alert time the event is ~40 min old and pattern accuracy is 42%; it rises to 67% at 1.5 h and 88% at 3 h on the same events.",
      ["ad_placement_curve", "ref_device_runs"], "D087"),
    Q("agent design", "What if the AI and the rules disagree?",
      "The report states the conflict; neither overrides. In stress tests the AI was right 2 of 3 times.",
      ["ad_disagreement"], "D055"),
    # false alarms
    Q("false alarms", "How many false alarms?",
      "On real calm test windows the 4 h agent flags 27% (rules 43%); a strict-clean subset gives 5%, because real 'calm' data contains real events.",
      ["ad_window_rules_vs_agent", "ad_window_headline"]),
    Q("false alarms", "Do the 12 h checks add false alarms?",
      "No: on piecewise-calm windows the combination stays at 31% (12/39) with 0 new alarms.",
      ["ad_longrange_arms", "ad_longrange_paired"], "D090"),
    Q("false alarms", "Why did you drop the daily baseline?",
      "It raised more false alarms (29% vs 20%) and caught half the old steps (48% vs 86%): yesterday has its own events.",
      ["ad_daily_baseline_rejected", "ad_detector_tuning_frontier"], "D092"),
    Q("false alarms", "How will v2 reduce false alarms?",
      "It is trained on routines that look like alarms (refills, load switching, daily cycles) labelled normal; acceptance requires fewer than today's 31%.",
      ["ds_routine", "ds_label_alarm_rate"], "D105"),
    # latency
    Q("latency", "Where does the time go in one AI call?",
      "Decode ~70%, init ~18%, prefill ~11%; decode is at ~84% of the NPU's memory-bandwidth ceiling.",
      ["lat_call_breakdown", "lat_bandwidth_roof"], "D035"),
    Q("latency", "How fast is an incident now?",
      "Typical Mode 3 incident median 3.8 s; a 12-agent chaos incident 20.7 s (was ~47 s on Genie).",
      ["lat_chaos_genie_vs_htpd", "ux_stress_runs"], "D074"),
    Q("latency", "What were the biggest latency wins?",
      "Batching all agents in one weight sweep (htpd), drafting, ctx 2048 (-721 ms/call), the persistent daemon (3.6 -> 2.5 s/call) and the batch window (-4 s).",
      ["lat_route_13_agents", "lat_ctx2048", "lat_genied", "lat_batch_window"]),
    Q("latency", "What did you try that failed?",
      "LADE (fast but 1/14 identical), grammar decoding (+440 ms), continuous batching (truncated answers), parallel sessions (3x slower), GPU (slower).",
      ["lat_rejected_lade", "lat_rejected_grammar", "lat_rejected_continuous_batching", "lat_rejected_parallel_npu", "hw_grid"], "D037"),
    Q("latency", "Did any speed-up change the answers?",
      "Every shipped change was gated on output identity (14/14, 28/28, 16/16, 25/25) against the run-to-run noise floor; ones that changed answers were rejected.",
      ["acc_pipeline_parity", "lat_htpd_ab"], "D082"),
    Q("latency", "How much of the incident time is your app, not the model?",
      "About 11 ms in a 11.6 s three-call incident.",
      ["lat_phase_trace"], "D048"),
    Q("latency", "Will v2 be slower?",
      "Possibly at first (+40-60 prompt tokens); the policy is accuracy first, then a latency pass back to <= 14.7 s (13 agents) and <= 3.8 s typical.",
      ["lat_route_13_agents", "ds_tokens"], "D114"),
    # data, test sets, leakage
    Q("data", "What data did you use?",
      "IIIT-H campus sensor data for 2025: 14 CSVs, 4.6 GB, ~37 M rows across air, water, power, occupancy, weather and HVAC.",
      ["ds_source_data"], "D107"),
    Q("data", "How did you avoid leakage?",
      "Temporal split (train Jan-Aug, dev Sep-Oct, test Nov-Dec), a leakage check on every v2 row, and in v2 ~15% of sensors held out entirely.",
      ["ds_qa_checks", "ds_heldout", "ds_v1_dataset"], "D113"),
    Q("data", "Are synthetic injections realistic?",
      "They ride on real calm windows from real sensors; a real-event set from facility logs is planned as a second ground truth.",
      ["ds_v1_dataset", "acc_v1_rules_vs_llm_fair"], "D066"),
    Q("data", "Can we see the test cases?",
      "Yes as labels and per-sample scores (data packs); raw sensor windows stay private by policy.",
      ["ad_window_per_family", "ad_placement_heatmap"], "D069"),
    Q("data", "What is in the v2 training data?",
      "35,946 rows over 6 roles, 21 window lengths (2-12 h), events of every age and size, 7 fault kinds, routines labelled normal, HVAC per unit.",
      ["ds_roles", "ds_families", "ds_window_lengths", "ds_event_age", "ds_fault_kind"], "D104"),
    Q("data", "How do you know the v2 data is correct?",
      "11 hard checks on 40,858 rows (JSON, enums, evidence ids, numbers, rebuild, leakage, duplicates...) with 0 failures, plus a 60-sample manual review.",
      ["ds_qa_checks"], "D115"),
    Q("data", "Why add HVAC?",
      "87 indoor AC units are the largest data source; faults like short-cycling or cooling an empty room were invisible to the other agents.",
      ["ds_hvac_real_labels", "ds_hvac_injection"], "D100"),
    # training
    Q("training", "How is v2 trained?",
      "QLoRA on Llama 3.2 3B, r=32, 2 epochs = 4,494 steps, ~«sps» s/step recently on a 6 GB laptop GPU, in resumable sessions.",
      ["tv2_plan", "tv2_sessions"], "D111"),
    Q("training", "Is it overfitting?",
      "No sign so far: dev loss falls «dev0» -> «devb» (best, step «bstep») and train loss per token tracks it; the best checkpoint, not the last, is kept.",
      ["tv2_loss_curve"], "D112"),
    Q("training", "Why did training take so long?",
      "Thermal pauses (5+ h), a blue screen, a thermal sleep, lid standby and supervisor deaths; each now has a guard.",
      ["tv2_interruptions", "tv2_thermal_pauses", "ops_power_events"], "D123"),
    # thermals and power
    Q("thermals", "How hot does the board get?",
      "Idle ~43-50 C; htpd chaos peaks 95-96 C, where the guard pauses work; a heatsink is needed in the field.",
      ["hw_board_thermal", "ux_stress_runs"], "D062"),
    Q("thermals", "Did the UI really heat the board?",
      "Yes: the redesigned dashboard used ~220% CPU and held the board at 75 C; after the fix 5-11% and 43 C.",
      ["hw_ui_cpu"], "D058"),
    Q("thermals", "What about power?",
      "Not yet measured in joules (no free power rail); USB power browned out at peak, so the evaluation uses the DC adapter.",
      ["ops_incidents"], "D057"),
    # safety
    Q("safety", "Can the AI switch anything off?",
      "No. The policy gate forbids actuation; every recommendation (even switch_off_ac in v2) needs a human approval.",
      ["ad_policy_gate", "ds_hvac_injection"], "D119"),
    Q("safety", "What stops hallucinated evidence?",
      "The policy gate accepts only real evidence ids, whitelisted labels and valid JSON; repairs are recorded, invented labels rejected.",
      ["ad_policy_gate", "acc_device54_engines"], "D020"),
    Q("safety", "Is every answer that passes the gate correct?",
      "No: the gate checks JSON, labels and evidence ids, not arithmetic in free text. One passed answer said '863 ppm exceeds the 1000 ppm warning limit' (model text, numerically wrong); v2 caps free text at 2 short observations.",
      ["ad_policy_gate", "uc_human_in_loop"], "D020"),
    Q("safety", "What if the synthesizer's answer fails policy?",
      "The operator still gets a report built from the agents' findings (Mode 3) or the rules (Mode 2), marked as such.",
      ["ad_policy_gate"], "D056"),
    Q("safety", "Is the board secure on a network?",
      "Off-device writes need an API token; adb has no auth on this dev kit, so the board stays off untrusted networks.",
      ["ux_hardening", "hw_platform_paths"], "D061"),
    # robustness
    Q("robustness", "How did you test robustness?",
      "Through the app: random sliders, faults, chaos, operator actions, killed processes and reboots; final build 132/135, all failures thermal.",
      ["ux_stress_runs", "ux_fault_injection", "ux_v6_final_checks"], "D065"),
    Q("robustness", "What happens if a process crashes mid-analysis?",
      "The backend is back in 8 s, the NPU daemon in <= 15 s, and the interrupted incident reloads as 'rerun'.",
      ["ux_fault_injection"], "D064"),
    # limits
    Q("limits", "What are the honest limits?",
      "Small device sets (n=54), no labelled Mode 2 vs 3 grid yet, circular cause labels, recurring small spikes unsolved, heat at chaos peaks, power not measured.",
      ["acc_device54_engines", "ad_window_subthr_called", "hw_board_thermal"]),
    Q("limits", "What is still unsolved?",
      "Recurring sub-threshold spikes: no window length or detector catches them reliably (32-52%); v2 teaches them explicitly.",
      ["ad_window_old_events", "ad_longrange_ablation"], "D091"),
    # what's next / status
    Q("next", "What is next?",
      "Finish v2 training, deploy it on htpd, run the NPU acceptance test, then the latency pass and the cross-domain reasoner.",
      ["tv2_loss_curve", "tv2_plan"], "D112"),
    Q("next", "What happens after training finishes?",
      "Merge the best adapter, export GGUF Q4_0 for htpd, run the acceptance tests on the QIDK (test months), then a latency pass back to <= 14.7 s for 13 agents.",
      ["tv2_plan", "tv2_loss_curve", "lat_route_13_agents"], "D112"),
    Q("next", "How will you know v2 is better than v1?",
      "Fixed in advance, on the QIDK, test months, paired against v1: pattern >= 65% at 40 min (v1 42%) and >= 88% at 3 h, no regression on the 54/900 sets, JSON/policy >= 98%, fewer false alarms than v1's 31%.",
      ["ad_placement_curve", "acc_device54_engines", "uc_alert_reduction"], "D112"),
    Q("next", "What if v2 fails the acceptance test?",
      "v1 stays deployed (it is the revert); we report the failed criteria and fix data or training, never lower the bar after the fact.",
      ["acc_device54_engines", "tv2_plan"], "D112"),
    Q("status", "What runs on the QIDK today?",
      "The v1 fine-tuned Llama 3.2 3B on htpd (llama.cpp Hexagon), Mode 3 agents with refinements and 12 h checks, policy gate, native app.",
      ["acc_device54_engines", "ref_device_runs"], "D083"),
    Q("status", "Where is training right now?",
      "Step «step» of 4,494 («pct»%) at build time, best dev loss «devb»; about «eta» h of training left, plus pauses.",
      ["tv2_progress", "tv2_loss_curve"]),
]

UC = [
    Q("use case", "What is the system for?",
      "It watches a campus's sensors (174 sensors, 33.2 M readings a year across 8 domains), notices real problems and explains why, on one small board.",
      ["uc_coverage"], "G01"),
    Q("use case", "Who uses it?",
      "Facility operators: they get one explained incident instead of a flood of threshold alarms, and approve or dismiss each recommendation.",
      ["uc_human_in_loop", "uc_alert_reduction"], "G06"),
    Q("use case", "What problem does it solve?",
      "Threshold alarms fire «br_all» times a year on this campus and say what crossed a line, never why.",
      ["uc_breaches_monthly", "uc_breaches_need_action"], "G04"),
    Q("use case", "How many of those alarms actually need attention?",
      "«br_gated» breaches last at least 40 min (the event-gate rule) and «br_crit_gated» are both persistent and critical.",
      ["uc_breaches_need_action"], "G04"),
    Q("use case", "Which domains raise the most alarms?",
      "«br_domains».",
      ["uc_breaches_monthly", "uc_breaches_need_action"]),
    Q("use case", "What improves over the status quo?",
      "At the same detection rate as threshold rules (78%), false alarms drop from 43% to 27%, and each alert comes with a cited explanation.",
      ["uc_alert_reduction"], "G04"),
    Q("use case", "How quickly does an operator get an explanation?",
      "About 4 s for a typical incident and 20.7 s when 12 sensors fail at once (was ~47 s); refined re-reads follow at +1.5 h and +3 h.",
      ["uc_time_to_insight", "ref_device_runs"], "G07"),
    Q("use case", "Does it need the internet or a server?",
      "No: inference, statistics, safety checks and storage all run on the QIDK; no campus data leaves the site.",
      ["uc_edge_offline"], "G01"),
    Q("use case", "Can it explain problems that span several systems?",
      "Yes: in multi-sensor incidents NPU agents examine up to 4 domains and one report names a single root cause; all 4 multi-sensor incidents spanned 2-4 domains.",
      ["uc_cross_domain"], "G03"),
    Q("use case", "Walk me through one incident.",
      "Crowded room: CO2 and power abnormal for 8 readings, 4 s batch window, 2 domain agents (7.1 s), synthesizer (4.5 s), then the operator decides.",
      ["uc_example_incident"], "G03"),
    Q("use case", "Will it ever switch something off by itself?",
      "Never: the policy gate forbids actuation; 100% of agent answers passed the gate in the final app test and every action waits for a person.",
      ["uc_human_in_loop"], "G05"),
    Q("use case", "What does it take to run in the field?",
      "One QIDK board on DC power with a heatsink; it idles at ~43 C and peaks ~95 C only when every sensor fails at once.",
      ["uc_edge_offline", "hw_board_thermal"], "G20"),
]

SITUATIONS = [
    Q("situations", "What does the system do for a ventilation failure?",
      "It raises one air-quality incident, identifies insufficient ventilation, and recommends an inspection; the final on-board run completed it in 7.4 s.",
      ["sit_ventilation_failure", "ux_scenario_outcomes", "ux_mode2_vs_mode3_latency"]),
    Q("situations", "What does it do when a water tank is leaking?",
      "The immediate 4-hour run completed in 3.1 s but called the slow leak normal with no action; the 12-hour check found the slow drift (-65 over 12 h) and raised it to warning at the 1.5 h re-read on the board.",
      ["sit_tank_leak", "ux_scenario_outcomes", "ux_mode2_vs_mode3_latency", "ref_device_runs"]),
    Q("situations", "What happens when several systems fail together?",
      "It groups the incident, sends one agent per affected domain, and gives the operator one safety-checked report; 10–12 agents plus synthesis completed in about 21 s.",
      ["sit_chaos", "ux_scenario_outcomes", "ux_chaos_incidents", "uc_cross_domain"]),
    Q("situations", "What happens when a sensor gets stuck?",
      "The agent calls the frozen reading a flatline and a sensor fault (not an emergency) and recommends checking the sensor; 2.6 s on the board, unchanged at 1.5 h and 3 h.",
      ["sit_stuck_sensor", "ux_scenario_outcomes"], "G17"),
    Q("situations", "What happens when the AC runs in an empty room?",
      "Not yet measured: the switch_off_ac recommendation is part of the v2 retrain and will need operator approval like every action.",
      [], "G06"),
]
SITUATION_OF = {"What does the system do for a ventilation failure?": "ventilation_failure", "What does it do when a water tank is leaking?": "tank_leak",
                "What happens when several systems fail together?": "chaos", "What happens when a sensor gets stuck?": "stuck_sensor",
                "What happens when the AC runs in an empty room?": "ac_empty_room"}
for _q in SITUATIONS:
    _q["situation_id"] = SITUATION_OF.get(_q["q"])
QA = UC + SITUATIONS + QA


def _dynamic():
    """Numbers in answers come from the generated datasets / the training log, never typed in."""
    import statistics
    import training_v2 as tv
    f = {}
    na = read_json(DATA / "use_case/uc_breaches_need_action.json")
    S_ = {s["name"].split(" (")[0]: s["points"] for s in na["series"]}
    allp = na["series"][0]["points"]; gat = na["series"][1]["points"]; crit = na["series"][2]["points"]
    f["br_all"] = f"{sum(p['y'] for p in allp):,}"
    f["br_gated"] = f"{sum(p['y'] for p in gat):,}"
    f["br_crit_gated"] = f"{sum(p['y'] for p in crit):,}"
    top = sorted(allp, key=lambda p: -p["y"])
    f["br_domains"] = ", ".join(f"{p['x']} {p['y']:,}" for p in top)
    mm = read_json(DATA / "app_ux/ux_mode2_vs_mode3_latency.json")
    f["m3"] = f"{statistics.median(p['y'] for p in mm['series'][0]['points']):.1f}"
    f["m2"] = f"{statistics.median(p['y'] for p in mm['series'][1]['points']):.1f}"
    ev = tv.parse_log(tv.log_path())
    st = ev["steps"]
    rec = sorted(s["s_per_step"] for s in st[-20:])
    sps = rec[len(rec) // 2] if rec else 42
    step = st[-1]["step"] if st else 0
    f.update(sps=f"{sps:.0f}", step=f"{step:,}", pct=f"{100 * step / 4494:.0f}", eta=f"{(4494 - step) * sps / 3600:.0f}")
    evs = ev["eval"]
    if evs:
        b = min(evs, key=lambda e: e["eval_loss"])
        f.update(dev0=f"{evs[0]['eval_loss']:.3f}", devb=f"{b['eval_loss']:.3f}", bstep=f"{b.get('step', '?')}")
    return f


def main():
    ids = {p.stem for p in DATA.glob("*/*.json")}
    dj = read_json(DATA / "decisions.json")
    dec = {d["id"] for d in dj["decisions"]}
    alias = dj.get("alias", {})
    for x in QA:
        x["evidence_ids"] = list(dict.fromkeys(canon(e) for e in x["evidence_ids"]))
        if x["decision_id"] in alias:
            x["decision_child"] = x["decision_id"]
            x["decision_id"] = alias[x["decision_id"]]
    bad = [(q["q"], e) for q in QA for e in q["evidence_ids"] if e not in ids] + [(q["q"], q["decision_id"]) for q in QA if q["decision_id"] and q["decision_id"] not in dec]
    assert not bad, bad
    fill = _dynamic()
    for x in QA:
        for k, v in fill.items():
            x["short_answer"] = x["short_answer"].replace(f"«{k}»", str(v))
        assert "«" not in x["short_answer"], x["short_answer"]
    out = {"meta": {"title": "Questions the evaluators asked or will ask", "n": len(QA), "generated_at": NOW, "script": rel(S),
                    "categories": sorted({q["category"] for q in QA})}, "qa": QA}
    (DATA / "qa.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(main()["meta"]["n"])
