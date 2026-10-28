"""data/decisions.json (round 2): ~30 ranked decision GROUPS. Each group holds the merged sub-decisions
(decisions.DEC, ids D001..D125) as children so old deep links resolve via meta 'alias'."""
from _lib import *
from decisions import DEC, R

S = __file__
TOPICS = ("use_case", "latency", "hardware", "accuracy", "agent_design", "refinement", "training_v2", "dataset_v2", "app_ux", "ops", "timeline")


def G(gid, rank, title, claim, chosen, rejected, ev, children, sec, topic):
    return {"id": gid, "rank": rank, "title": title, "claim": claim, "chosen": chosen, "rejected": rejected,
            "evidence_ids": ev, "children": children, "handbook_section": sec, "topic": topic}


GROUPS = [
    G("G01", 1, "Everything runs on the board's NPU, not in the cloud", "Sensor data, AI inference, safety checks and storage stay on one QIDK",
      "Fine-tuned 3B on the Hexagon NPU, started through the board's own adbd; Go backend as the shell user",
      [R("Cloud LLM", "every incident would ship campus data off-site and stop when the link drops", "uc_edge_offline"),
       R("Laptop driving the board over adb", "unplug the laptop and the system dies", "uc_edge_offline")],
      ["uc_edge_offline", "uc_coverage"], ["D005", "D006", "D007", "D019"], "4.1; problems_setup.md", "use_case"),
    G("G02", 2, "Fine-tune one Llama 3.2 3B for every domain role", "Pattern accuracy 20% -> 94% (laptop), evidence valid 35% -> 100%",
      "One QLoRA multi-role adapter on Llama 3.2 3B, trained on the laptop GPU",
      [R("Prompt the base model", "4 in 5 patterns wrong (20%), 65% of answers cite invalid evidence", "acc_v1_host_eval"),
       R("A second resident model / separate adapters", "two 3B models rebooted the board", "hw_board_thermal")],
      ["acc_v1_host_eval", "acc_v1_output_tokens"], ["D002", "D003", "D004", "D009", "D013"], "2.7", "accuracy"),
    G("G03", 3, "Multi-agent incidents (Mode 3) with rules and single-call baselines", "One specialist agent per abnormal sensor + a synthesizer across domains",
      "Mode 3: every alarming sensor gets an NPU agent, a synthesizer names one root cause; Mode 1/2 kept as baselines",
      [R("One call over all sensors (Mode 2)", "no per-sensor evidence to check; not faster on the final build (median 4.2 vs 3.4 s)", "ux_mode2_vs_mode3_latency"),
       R("Cap the number of agents", "alarms beyond the cap were silently dropped", "ux_stress_runs")],
      ["uc_cross_domain", "ux_mode2_vs_mode3_latency"], ["D008", "D046", "D053"], "1; 2.31", "agent_design"),
    G("G04", 4, "Alert only on persistent abnormal status (event gate)", "Same detection as threshold rules, false alarms 43% -> 27%",
      "Warning/critical/fault for 8 consecutive readings opens one incident; co-occurring alarms are batched",
      [R("Raise every threshold breach", "20,538 breaches a year; most do not even last 40 min", "uc_breaches_need_action"),
       R("Call the AI immediately", "a 20-min-old event is read right only 24% of the time", "ad_placement_curve")],
      ["uc_alert_reduction", "uc_breaches_need_action"], ["D021", "D048", "D049"], "2.29; 4.1", "use_case"),
    G("G05", 5, "Safety: a policy gate on every answer", "100% of agent answers pass the gate; 0 automatic actions",
      "Validate JSON, labels and evidence ids; transparent repairs; derive the action; fallback report; no actuation",
      [R("Trust raw model output", "invented labels and evidence ids reach the operator", "ad_policy_gate"),
       R("Use the model's own action", "0.778 vs 0.815: wrong actions from right causes", "acc_device54_engines")],
      ["uc_human_in_loop", "ad_policy_gate"], ["D020", "D030", "D056"], "2.7; 2.8; 2.33", "agent_design"),
    G("G06", 6, "Disagreements are shown, decisions stay human", "Neither AI nor rules override; recommendations need approval",
      "Report states AI-vs-rules conflicts; even switch_off_ac (v2) needs approval",
      [R("Let rules override the AI", "the AI was right in 2 of 3 disagreements", "ad_policy_gate"),
       R("Automatic actuation", "a wrong answer would act on the building", "uc_human_in_loop")],
      ["ad_policy_gate", "uc_human_in_loop"], ["D055", "D119"], "2.33; SPEC D9", "agent_design"),
    G("G07", 7, "Batched NPU daemon (htpd) for multi-agent incidents", "12-agent incident ~47 s -> 20.7 s; pattern 85.2% -> 90.7% (n.s.)",
      "llama.cpp Hexagon daemon: all agents in one weight sweep; FA streams, HMX pipe, verified drafting, prefix cache, NEON argmax",
      [R("Stay on Genie", "13 agents take 22-25 s; Genie drops its batching config", "lat_route_13_agents"),
       R("8-bit KV, synthesizer speculation, runtime knobs", "2x slower or changed answers", "lat_htpd_levers")],
      ["lat_route_13_agents", "lat_htpd_ab", "lat_chaos_genie_vs_htpd", "acc_device54_engines"],
      ["D074", "D075", "D076", "D077", "D078", "D079", "D080", "D081", "D082", "D083"], "2.37", "latency"),
    G("G08", 8, "Keep the model resident and stop wasted tokens", "Agent call ~3.9 s -> 2.5 s (Genie era)",
      "genied persistent dialog (poll off), async init, stop before the derived 'action', profiler-only measurement",
      [R("Process per call", "687-731 ms init paid on every call", "lat_genied"),
       R("Trim every call", "broke the synthesizer report", "lat_route_agent_call")],
      ["lat_route_agent_call", "lat_genied", "lat_call_breakdown"], ["D028", "D031", "D032", "D043", "D044"], "2.10-2.24", "latency"),
    G("G09", 9, "Smaller context, smarter scheduling", "3-call incident 18.7 s -> 11.6 s",
      "ctx 2048 (4096 only when needed), batched agents, short gaps, exact-prompt cache, word limits, sequential NPU sessions",
      [R("ctx 4096 for every call", "-721 ms per call lost", "lat_ctx2048"),
       R("Parallel NPU sessions", "3x slower and crashed the board", "lat_rejected_ideas")],
      ["lat_route_incident", "lat_ctx2048", "lat_batch_window"],
      ["D023", "D024", "D025", "D026", "D029", "D038", "D041", "D042", "D054"], "2.17-2.32; 5", "latency"),
    G("G10", 10, "Reject speed-ups that change answers or do not pay", "LADE: -32% decode but only 1 in 14 answers identical",
      "Gate every decode change on output identity across many prompts",
      [R("LADE lookahead decoding", "a stuck sensor was reported as normal", "lat_rejected_ideas"),
       R("Grammar decoding / multi-graph / RPC knobs / continuous batching", "slower, no gain, or truncated answers", "lat_rejected_ideas")],
      ["lat_rejected_ideas", "lat_call_breakdown"], ["D033", "D034", "D035", "D036", "D037", "D039", "D045"], "2.12-2.25", "latency"),
    G("G11", 11, "Close the device accuracy gap with GPTQ", "First NPU export 54.3% -> 85.2% on device",
      "GPTQ int4 weights, published activation ranges, w4a16",
      [R("Round-to-nearest int4", "costs ~15 points (73.9% vs 89.1% on host)", "acc_quant_waterfall"),
       R("Kaggle-recalibrated activations", "no gain once BOS was fixed", "acc_quant_waterfall")],
      ["acc_quant_waterfall"], ["D014", "D015", "D017"], "2.7", "accuracy"),
    G("G12", 12, "Prove the device runs exactly what was trained", "Double-BOS fix: 67% -> 83%; byte-identity gates on every change",
      "Strip our BOS, force greedy decoding, validate on the device before switching models",
      [R("Trust host accuracy", "the first export lost 40 points on the device", "acc_quant_waterfall"),
       R("Sampling decoder (bundle default)", "no reproducibility, no cache, no identity gates", "acc_pipeline_parity")],
      ["acc_pipeline_parity", "acc_quant_waterfall"], ["D016", "D018", "D022"], "2.7", "accuracy"),
    G("G13", 13, "Honest ground truth and statistics", "Lead with pattern accuracy: 92.5% vs 60.0% on the non-circular roles",
      "Known faults injected into real calm windows; temporal split; n, Wilson CIs and paired tests on every claim",
      [R("Claim cause accuracy as independent", "cause labels come from the same rules as Mode 1", "acc_v1_rules_vs_llm_fair"),
       R("All-role averages", "occupancy labels are the rules' own logic (rules 100% by construction)", "acc_v1_host_per_role")],
      ["acc_v1_rules_vs_llm_fair", "acc_v1_host_per_role", "acc_device54_engines"], ["D010", "D011", "D066", "D067", "D068"], "2.36", "accuracy"),
    G("G14", 14, "Keep the 4 h window for the domain agent", "Pattern 64% at 4 h vs 46 / 56 / 42% at 2 / 8 / 12 h (p < 0.0001)",
      "48 x 5-min readings",
      [R("12 h window", "pattern 42%, false alarms 27% -> 46%, +32% cost", "ad_window_headline"),
       R("2 h window", "worst on almost everything", "ad_window_headline")],
      ["ad_window_headline", "ad_window_cost"], ["D084"], "2.38", "agent_design"),
    G("G15", 15, "Early alert, then refined re-reads at 1.5 h and 3 h", "Pattern accuracy 42% at 40 min -> 88% at 3 h on the same events",
      "Alert stays fast; re-analyse every Mode-3 incident at +18 and +36 readings; keep early spikes; keep worst severity",
      [R("Only the early read", "about 6 in 10 young events misnamed", "ad_placement_curve"),
       R("Wait 3 h before the first analysis", "alerts hours late", "ad_placement_curve")],
      ["ad_placement_curve", "ad_placement_heatmap", "ref_device_runs"], ["D087", "D088", "D089", "D094"], "2.39", "refinement"),
    G("G16", 16, "12 h CPU checks feed the reasoner", "Old steps 73% -> 93%, drifts 83% -> 95%, no new false alarms",
      "Level shift + slow drift over 12 h, tuned on dev months, tested once",
      [R("Daily 'same hours yesterday' baseline", "false alarms 20% -> 29%, old steps 86% -> 48%", "ad_daily_baseline_rejected"),
       R("Recurring-excursion detector", "dev false alarms 2% -> 15%", "ad_longrange_ablation")],
      ["ad_longrange_arms", "ad_daily_baseline_rejected", "ad_detector_tuning_frontier"], ["D090", "D091", "D092", "D093"], "2.39", "agent_design"),
    G("G17", 17, "Severity, titles and the report follow the AI", "No more 'critical' incidents the agents called normal",
      "severity.go / title.go from the analysis; report page with chips and a sensor sheet; live token streaming",
      [R("Rule severity fixed at creation", "list colours contradicted the analysis", "ux_screenshots")],
      ["ux_screenshots"], ["D050", "D051", "D085", "D086", "D095"], "2.23; 2.30; 2.38; 2.39", "app_ux"),
    G("G18", 18, "Test through the app, the way an operator uses it", "Final build 132/135 checks; every failure is heat",
      "stress_app.py: random sliders, faults, chaos, operator actions; one FIFO queue",
      [R("Offline benchmarks only", "missed un-injectable scenarios, dropped alerts and stale aborts", "ux_stress_runs")],
      ["ux_stress_runs", "ux_chaos_incidents"], ["D040", "D052", "D065"], "2.31", "app_ux"),
    G("G19", 19, "Recover from faults; exactly one model on the NPU", "Backend back in 8 s, daemon in <= 15 s, no lost incidents",
      "Crash-safe store, incidents persisted at creation, NPU retries, port lock, API token, plausibility rules",
      [R("Treat EOF as a normal end", "truncated answers were 'answered'", "ux_fault_injection"),
       R("CLI fallback beside a live daemon", "second model -> reboot", "ops_incidents")],
      ["ux_fault_injection", "ops_incidents"], ["D027", "D059", "D060", "D061", "D063", "D064"], "2.35; 4.1", "app_ux"),
    G("G20", 20, "Keep the board cool and powered", "UI 220% -> 5-11% CPU (75 -> 43 C idle); chaos paced to ~90 C",
      "Thermal pacing per NPU call, a UI that does not heat the board, DC power",
      [R("Animated blurred UI", "hotter than a 13-agent incident", "hw_board_thermal"),
       R("USB power", "a brownout rebooted the board at peak load", "ops_incidents")],
      ["hw_board_thermal", "ops_incidents"], ["D057", "D058", "D062"], "2.34; 2.35", "hardware"),
    G("G21", 21, "GPU study: decided by data", "GPU-only and hybrid are slower than the NPU at every incident size",
      "Full matrix on the device's own weights; safe memory ladder; NPU in production",
      [R("Agents on the Adreno GPU", "10.0 s vs 3.9 s for one agent; no valid JSON at ctx 4096", "hw_grid"),
       R("Batch agents on the GPU", "8 streams together only 12.4 tok/s", "hw_gpu_batched")],
      ["hw_grid", "hw_gpu_batched", "hw_grid_agreement"], ["D070", "D071", "D072", "D073"], "2.36; 2.37", "hardware"),
    G("G22", 22, "Retrain the domain agents (v2) instead of patching", "Accept only on the NPU: >= 65% at 40 min and >= 88% at 3 h",
      "Final v2 retrain, deployed as GGUF on htpd; accuracy first, then latency back to today's numbers",
      [R("Keep v1 and add more CPU checks", "v1 reads 40-min-old events right only 42% of the time", "ad_placement_curve"),
       R("Accept on dev loss", "dev loss is not accuracy", "tv2_loss_curve")],
      ["ad_placement_curve", "tv2_loss_curve"], ["D096", "D098", "D112", "D114"], "2.40; RETRAIN_V2_SPEC", "training_v2"),
    G("G23", 23, "v2 data: events of every age, every window length, 12 h history", "21 window lengths (2-12 h), onsets from 15 min",
      "Onset anywhere (extra weight 20-60 min), 1.5-12x noise, E9/E10 history lines, window length shown",
      [R("v1 data (4 h only, events 1-3 h old)", "the agent misreads what the app actually asks about", "ds_event_age")],
      ["ds_event_age", "ds_window_lengths"], ["D099", "D101", "D102", "D103", "D106"], "SPEC #3-#11", "dataset_v2"),
    G("G24", 24, "v2 data: teach what v1 missed and what is normal", "Missed patterns, 7 fault kinds and routine hard negatives",
      "Recurring spikes, old shifts, long drifts, compound shapes, faults, routines labelled normal",
      [R("v1 pattern set", "recurring small spikes caught 32%; ~27-31% false alarms on calm data", "ad_window_old_events")],
      ["ds_families", "ds_routine", "ds_fault_kind"], ["D104", "D105", "D116", "D117", "D118", "D121"], "SPEC #9/#10; D2-D7", "dataset_v2"),
    G("G25", 25, "v2 output: short, frozen schema", "~76 generated tokens despite three new fields",
      "Max 2 observations, event_active/onset/fault_kind, calibrated confidence",
      [R("v1 free-length output", "more tokens = more decode time", "ds_tokens")],
      ["ds_tokens", "ds_families"], ["D108", "D109", "D110"], "SPEC #13-#15", "dataset_v2"),
    G("G26", 26, "Add an HVAC agent", "87 indoor units; 98.45% of real windows are normal, faults taught by injection",
      "6th role per indoor unit; faulty units as fault examples; dense 'unit on' sampling",
      [R("HVAC only as context", "short-cycling and cooling empty rooms stay invisible", "ds_hvac_real_labels")],
      ["ds_hvac_real_labels", "ds_roles"], ["D100", "D120"], "SPEC #4/#19; D1/D11/D12", "dataset_v2"),
    G("G27", 27, "Held-out sensors and data QA before training", "25 sensors never seen; 11 checks x 40,858 rows, 0 failures",
      "Test months + ~15% held-out sensors; automatic checks + manual review; generated from existing data",
      [R("Temporal split only", "same sensors in every split", "ds_heldout"),
       R("Train first, check later", "a bad label costs 40+ GPU hours", "ds_qa_checks")],
      ["ds_heldout", "ds_qa_checks"], ["D107", "D113", "D115", "D122"], "SPEC #12/#21/#22; D8", "dataset_v2"),
    G("G28", 28, "Train v2 on the laptop in resumable sessions", "Every interruption recovered from a checkpoint",
      "QLoRA r=32, 4,494 steps; thermal guard; WSL networking off; lid open; WMI supervisor",
      [R("One uninterrupted 50 h run", "a BSOD, a thermal sleep and lid standbys would each have lost the run", "tv2_interruptions")],
      ["tv2_sessions", "tv2_interruptions", "tv2_thermal_pauses", "tv2_plan"], ["D012", "D097", "D111", "D123", "D124"], "2.1b; 2.40", "training_v2"),
    G("G29", 29, "Learn from the operator", "Every verdict is stored; policy repairs become preference pairs",
      "Persist prompt, raw, repairs and approval; export SFT positives and DPO pairs",
      [R("Collect labels later", "loses the free preference pairs", "uc_human_in_loop")],
      ["uc_human_in_loop"], ["D047"], "2.28", "agent_design"),
    G("G30", 30, "Private data, public evidence", "Aggregates and scores on an encrypted static site; raw data stays local",
      "Laptop-first build order; private raw data; password-only encrypted website",
      [R("Publish datasets", "room occupancy reveals people's presence", "uc_coverage"),
       R("Cloudflare Access login", "replaced by password + client-side encryption", "tl_milestones")],
      ["uc_coverage", "tl_milestones"], ["D001", "D069", "D125"], "2.36; SPEC", "timeline"),
]


def main():
    ids = {p.stem for t in TOPICS for p in (DATA / t).glob("*.json")}
    byid = {d["id"]: d for d in DEC}
    used = [c for g in GROUPS for c in g["children"]]
    assert sorted(used) == sorted(byid), (set(byid) - set(used), [c for c in used if used.count(c) > 1])
    missing, groups = [], []
    for g in sorted(GROUPS, key=lambda g: g["rank"]):
        kids = []
        for cid in g["children"]:
            d = dict(byid[cid])
            d["evidence_ids"] = list(dict.fromkeys(canon(e) for e in d["evidence_ids"]))
            d["rejected"] = [dict(r, evidence_id=canon(r["evidence_id"])) for r in d["rejected"]]
            kids.append(d)
        st = {k["status"] for k in kids}
        g = dict(g, status="pending" if "pending" in st else "kept", date=min(k["date"] for k in kids),
                 rejected_count=len(g["rejected"]) + sum(len(k["rejected"]) for k in kids), children=kids)
        refs = g["evidence_ids"] + [r["evidence_id"] for r in g["rejected"]] + \
            [e for k in kids for e in k["evidence_ids"] + [r["evidence_id"] for r in k["rejected"]]]
        missing += [(g["id"], e) for e in refs if e not in ids]
        groups.append(g)
    assert not missing, f"decisions reference missing datasets: {missing}"
    alias = {k["id"]: g["id"] for g in groups for k in g["children"]}
    out = {"meta": {"title": "Decisions: what we chose, what we rejected, and the evidence", "n": len(groups), "n_children": len(alias),
                    "generated_at": NOW, "script": rel(S),
                    "source_files": ["HANDBOOK.md", "proofs/*/RESULTS.md", "Code/smart-city-edge-agent/training/RETRAIN_V2_SPEC.md",
                                     "problems_setup.md", "plan.md", "app.md", "training_plan.md", "ppt.md", "Website/SPEC.md"],
                    "status_counts": {s: sum(1 for g in groups if g["status"] == s) for s in ("kept", "pending")},
                    "notes": "Groups ranked by importance (rank 1 = most). Children keep their old ids (D001...); 'alias' maps each to its group."},
           "alias": alias, "decisions": groups}
    (DATA / "decisions.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print(o["meta"]["n"], o["meta"]["n_children"], o["meta"]["status_counts"])
