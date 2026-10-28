"""data/route.json: chronological journey + dedicated latency route + accuracy route."""
from _lib import *

S = __file__


def E(date, phase, what, outcome, before, after, ev, section=None):
    return {"date": date, "phase": phase, "what": what, "outcome": outcome, "metric_before": before, "metric_after": after,
            "evidence_id": ev, "handbook_section": section}


JOURNEY = [
    E("2026-09-17", "0 Spec", "PRD v2.0: rules -> LLM domain agents -> cross-domain reasoner -> policy gate -> human", "kept", None, None, "tl_milestones", "PRD.md"),
    E("2026-10-01", "0 Plan", "Laptop first, then port; one Llama 3.2 3B in many roles; Go backend over adb", "kept", None, None, "tl_milestones", "plan.md"),
    E("2026-10-02", "1 Bring-up", "Runtime search on the board: llama.cpp CPU/QNN, SNPE, QNN SDK -> AI Hub Genie bundle", "kept", "no LLM on the NPU", "Genie bundle running", "hw_platform_paths", "problems_setup.md"),
    E("2026-10-06", "2 Data", "6,480 training examples: patterns injected into real calm windows, temporal split", "kept", None, "5 roles x 1,296", "ds_v1_dataset", "2.7"),
    E("2026-10-07", "3 Fine-tune v1", "QLoRA overnight on the laptop GPU (after 21 thermal hibernations were fixed)", "kept", "base pattern 20%", "fine-tuned 94% (host)", "acc_v1_host_eval", "2.7"),
    E("2026-10-07", "4 Onto the NPU", "Quantisation journey: GPTQ, published ranges, double-BOS fix", "kept", "54.3% first export", "82.6-85.2% on device", "acc_quant_waterfall", "2.7"),
    E("2026-10-08", "5 Native app", "APK + local adbd loopback; event gate; retries; self-heal", "kept", "laptop needed", "standalone board", "hw_platform_paths", "4.1"),
    E("2026-10-13", "6 Accuracy fix", "Action derived by policy from (cause, status)", "kept", "action 0.778", "0.815", "acc_action_derived", "2.8"),
    E("2026-10-14", "7 Latency day", "ctx 2048, async init, trim, genied, zero gap, batch window; LADE/grammar/continuous batching rejected", "kept", "18.7 s (3-call incident)", "11.6 s", "lat_route_incident", "2.10-2.29"),
    E("2026-10-15", "8 Hardening", "Stress testing through the app; fault injection; night-run fixes; two context windows", "kept", "-", "238/240 checks", "ux_stress_runs", "2.31-2.35"),
    E("2026-10-15", "9 Mid-evaluation", "Evaluators ask: accuracy vs what, GPU study, test data", "pending", None, None, "tl_milestones", "2.36"),
    E("2026-10-16", "10 GPU study", "GPU-only, NPU-only, hybrid on the same incidents", "dropped", "NPU (Genie)", "GPU slower at every size", "hw_grid", "2.37"),
    E("2026-10-16", "11 htpd", "Batched NPU daemon on llama.cpp Hexagon: FA streams, HMX pipe, drafting, prefix cache, NEON argmax", "kept", "12-agent chaos ~47 s", "20.7 s", "lat_chaos_genie_vs_htpd", "2.37"),
    E("2026-10-16", "12 Window study", "2/4/8/12 h windows, 2416 NPU calls", "kept", None, "4 h best (pattern 64%)", "ad_window_headline", "2.38"),
    E("2026-10-16", "13 Severity + report page", "Severity from the reasoner; report page redesign", "kept", "rules severity at creation", "follows the AI", "ux_severity_from_reasoner", "2.38"),
    E("2026-10-16", "14 Placement study", "Same 208 events at 6 onsets, 1248 NPU calls", "kept", "42% at 40 min", "88% at 3 h", "ad_placement_curve", "2.39"),
    E("2026-10-16", "15 Refinements", "Re-analyse at 1.5 h and 3 h; keep early spikes", "kept", "early read only", "3/3 incidents reach 3 h on device", "ref_device_runs", "2.39"),
    E("2026-10-16", "16 12 h checks", "Level shift + slow drift as evidence (daily baseline and excursion detector dropped)", "kept", "old steps 73%", "93%", "ad_longrange_arms", "2.39"),
    E("2026-10-16", "17 Daily baseline", "'Same hours yesterday' detector", "dropped", "raw 12 h: FP 20%", "daily: FP 29%", "ad_daily_baseline_rejected", "2.39"),
    E("2026-10-17", "18 v2 data", "35,946 rows, 6 roles incl. HVAC, 2-12 h windows, hard negatives, held-out sensors", "kept", "6,480 rows, 4 h only", "35,946 rows, 21 lengths", "ds_roles", "2.40"),
    E("2026-10-17", "19 v2 training", "QLoRA r=32, 4,494 steps in resumable sessions", "pending", "dev loss 0.1311 (step 300)", "0.0660 (step 2400)", "tv2_loss_curve", "2.40"),
    E("2026-10-19", "20 Evidence site", "Static encrypted site answering the evaluators with charts", "pending", None, None, "tl_milestones", "SPEC"),
]

LAT_STEPS = [
    E("2026-10-07", "Genie CLI", "Fine-tuned answers end cleanly and are shorter than base", "kept", "base: 17.8 s ventilation incident", "8.9 s", "ad_modes_latency", "2.7"),
    E("2026-10-07", "Genie CLI", "Synthesizer word limits", "kept", "184-190 tokens", "102-120 tokens", "lat_word_limits", "5"),
    E("2026-10-07", "Genie CLI", "4 threads / mask 0xf0, mmap on", "kept", "11.9 s / 200 tok", "11.7 s", "lat_genie_settings", "5"),
    E("2026-10-07", "Genie CLI", "Exact-prompt cache for reruns", "kept", "4 NPU calls", "0 calls, ~3 ms", "ad_modes_latency", "5"),
    E("2026-10-14", "Genie CLI", "allow-async-init: true", "kept", "init 703-711 ms", "640 ms", "lat_async_init", "2.10"),
    E("2026-10-14", "Genie CLI", "genie-app batching of an incident's agents", "kept", "18691 ms", "17726 ms", "lat_genieapp_batch", "2.17"),
    E("2026-10-14", "Genie CLI", "Inter-call gap 600 -> 250 ms", "kept", "17726 ms", "17393 ms", "lat_gap_sweep", "2.20"),
    E("2026-10-14", "Genie CLI", "Context 4096 -> 2048", "kept", "4884.8 ms/call (init+prefill+decode)", "4170.5 ms", "lat_ctx2048", "2.22"),
    E("2026-10-14", "Genie CLI", "Stop before 'action' (agents only)", "kept", "3838.9 ms", "3640.1 ms", "lat_action_trim", "2.18"),
    E("2026-10-14", "genied", "Persistent dialog (C API)", "kept", "3640 ms / TTFT ~1.2 s", "2543 ms / TTFT 0.31 s", "lat_genied", "2.24"),
    E("2026-10-14", "genied", "Zero gap inside one process; trace shows ~11 ms app overhead", "kept", "17393 ms", "11570 ms", "lat_phase_trace", "2.29"),
    E("2026-10-14", "event gate", "Batch window closes early when nothing else is waking", "kept", "6.0 s", "2.0 s (isolated)", "lat_batch_window", "2.29"),
    E("2026-10-15", "genied", "Two context windows (no evidence trimming)", "kept", "chaos prompt does not fit 2048", "ctx 4096 swap ~0.9 s", "lat_two_windows", "2.32"),
    E("2026-10-16", "htpd v1", "llama.cpp Hexagon daemon, 13 streams, FA streams patch", "kept", "Genie 13 agents 22-25 s", "28.1 s (slower at first)", "lat_htpd_ab", "2.37"),
    E("2026-10-16", "htpd v4", "HMX pipe + legacy prefill + parked streams + verified drafting", "kept", "28.1 s", "17.5 s", "lat_htpd_ab", "2.37"),
    E("2026-10-16", "htpd v5", "Prefix cache per role", "kept", "17.5 s", "15.5 s", "lat_htpd_ab", "2.37"),
    E("2026-10-16", "htpd v6", "NEON argmax (same tie-break)", "kept", "A/B total 30.3 s", "27.7 s (13 agents 14.7 s)", "lat_htpd_ab", "2.37"),
    E("2026-10-16", "htpd v6, app", "Chaos through the app", "kept", "12 agents ~47 s (Genie)", "20.7 s", "lat_chaos_genie_vs_htpd", "2.37"),
]
LAT_REJECTED = [
    E("2026-10-07", "Genie CLI", "Parallel NPU sessions", "dropped", "23.6 s sequential", "76.5 s parallel", "lat_rejected_parallel_npu", "5"),
    E("2026-10-13", "Genie CLI", "poll=false", "dropped", "22.4-22.9 tok/s", "20.8-21.0 tok/s", "lat_genie_settings", "2.8"),
    E("2026-10-14", "Genie CLI", "First action-trim (string builder)", "dropped", "-", "invalid JSON at chunk boundaries", "lat_action_trim", "2.10"),
    E("2026-10-14", "Genie CLI", "Multi-graph bundle (3 graphs)", "dropped", "3738 ms", "4291 ms", "lat_rejected_multigraph", "2.12"),
    E("2026-10-14", "Genie CLI", "RPC / DCVS / mmap-budget / direct-io knobs", "dropped", "2613-2664 ms decode", "2641-2682 ms", "lat_rejected_rpc", "2.13"),
    E("2026-10-14", "Genie CLI", "Pre-warming / streaming scripts", "dropped", "-", "Genie waits for EOF", "lat_rejected_prewarm", "2.13"),
    E("2026-10-14", "Genie CLI", "LADE lookahead decoding", "dropped", "1/1 identical (one prompt)", "1/14 identical; stuck sensor -> normal", "lat_rejected_lade", "2.14"),
    E("2026-10-14", "Genie CLI", "Grammar-constrained decoding", "dropped", "init ~713 ms", "~1163 ms, no tokens saved", "lat_rejected_grammar", "2.16"),
    E("2026-10-14", "genied", "Continuous batching (shared engine)", "dropped", "28/28 identical", "1/12 identical (truncated)", "lat_rejected_continuous_batching", "2.25"),
    E("2026-10-14", "genied", "Batching while genied is up", "dropped", "one model", "second copy hits the SMMU limit", "hw_memory", "2.24"),
    E("2026-10-16", "GPU", "Agents on the Adreno GPU (OpenCL)", "dropped", "NPU", "~8.4 s per agent; no batching gain", "hw_grid", "2.37"),
    E("2026-10-16", "htpd", "Speculation on the synthesizer; 8-bit KV; thread/ubatch/power knobs; equal-ubatch prefill", "dropped", "-", "changed outputs / 2x slower / no gain", "lat_htpd_levers", "2.37"),
    E("2026-10-16", "agent", "Longer windows for speed of detection (8/12 h)", "dropped", "4 h", "+18% / +32% per agent, less accurate", "ad_window_cost", "2.38"),
]
ACC_STEPS = [
    E("2026-10-07", "host", "Base Llama 3.2 3B, prompt only", "dropped", None, "pattern 20%", "acc_v1_host_eval", "2.7"),
    E("2026-10-07", "host", "Fine-tuned (QLoRA, NF4)", "kept", "20%", "94%", "acc_v1_host_eval", "2.7"),
    E("2026-10-07", "QIDK", "First w4a16 export", "dropped", "94% host", "54.3%", "acc_quant_waterfall", "2.7"),
    E("2026-10-07", "QIDK", "MSE-clipped scales", "dropped", "54.3%", "39.1%", "acc_quant_waterfall", "2.7"),
    E("2026-10-07", "host", "GPTQ int4 (fp activations)", "kept", "73.9% (RTN int4)", "89.1%", "acc_fakequant_host", "2.7"),
    E("2026-10-07", "QIDK", "GPTQ + base activation ranges", "kept", "54.3%", "67.4%", "acc_quant_waterfall", "2.7"),
    E("2026-10-07", "QIDK", "Kaggle-recalibrated activations", "dropped", "67.4%", "60.9% (82.6% after BOS fix, no gain)", "acc_quant_waterfall", "2.7"),
    E("2026-10-07", "QIDK", "Double-BOS fixed", "kept", "67.4%", "82.6%", "acc_quant_waterfall", "2.7"),
    E("2026-10-07", "QIDK", "Live model on 54 windows", "kept", None, "85.2% (JSON/evidence/policy 100%)", "acc_device54_engines", "2.7"),
    E("2026-10-13", "QIDK", "Action derived by policy", "kept", "0.778", "0.815", "acc_action_derived", "2.8"),
    E("2026-10-16", "QIDK", "htpd final runtime (same weights)", "kept", "85.2% (Genie)", "90.7% (n.s., p=0.45)", "acc_device54_engines", "2.37"),
    E("2026-10-16", "QIDK", "4 h window kept (vs 2/8/12 h)", "kept", "42-56% other lengths", "64% pattern (604 cases)", "ad_window_headline", "2.38"),
    E("2026-10-16", "QIDK", "Refinement at 1.5 h / 3 h", "kept", "42% at 40 min", "67% / 88%", "ad_placement_curve", "2.39"),
    E("2026-10-16", "QIDK", "12 h checks added to the agent", "kept", "old steps 73%, drifts 83%", "93%, 95%", "ad_longrange_arms", "2.39"),
    E("2026-10-16", "QIDK", "900-window rerun", "pending", None, "stopped at 39 windows (91 C)", "acc_test900_partial", "2.37"),
    E("2026-10-19", "laptop", "Retrain v2 (in progress)", "pending", "dev loss 0.1311", "0.0660 at step 2400", "tv2_loss_curve", "2.40"),
]


def main():
    ids = {p.stem for p in DATA.glob("*/*.json")}
    allr = JOURNEY + LAT_STEPS + LAT_REJECTED + ACC_STEPS
    for x in allr:
        x["evidence_id"] = canon(x["evidence_id"])
    bad = [r["evidence_id"] for r in allr if r["evidence_id"] not in ids]
    assert not bad, bad
    out = {"meta": {"title": "Route: how we got here", "generated_at": NOW, "script": rel(S),
                    "source_files": ["HANDBOOK.md", "proofs/", "problems_setup.md", "plan.md", "PRD.md"],
                    "counts": {"journey": len(JOURNEY), "latency_steps": len(LAT_STEPS), "latency_rejected": len(LAT_REJECTED), "accuracy_steps": len(ACC_STEPS)}},
           "journey": JOURNEY,
           "latency_route": {"anchor": "12-agent chaos incident: ~47 s -> 20.7 s; 3-call incident 18.7 s -> 11.6 s; agent call ~3.9 s -> 2.5 s",
                             "steps": LAT_STEPS, "rejected": LAT_REJECTED,
                             "waterfalls": ["lat_route_agent_call", "lat_route_incident", "lat_route_13_agents"]},
           "accuracy_route": {"anchor": "pattern accuracy on the QIDK: 54% first export -> 85% (Genie) -> 91% (htpd), n=54",
                              "steps": ACC_STEPS, "waterfalls": ["acc_quant_waterfall"]}}
    (DATA / "route.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(main()["meta"]["counts"])
