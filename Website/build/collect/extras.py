"""Smaller evidence datasets that back specific decisions (platform path, pipeline parity, policy gate,
self-learning, reasoner plan, two context windows, production hardening)."""
from _lib import *

S = __file__


def main():
    rows = [["A1", "llama.cpp on the CPU", "works, slow", "bandwidth-bound decode on CPU; never the main path"],
            ["A2", "llama.cpp + GGML_QNN fork", "abandoned", "days with no result; oscillated between Genie and GGUF"],
            ["A3", "llama.cpp + OpenCL on Adreno GPU", "tried 2026-10-16: not viable", "~8.4 s per agent, no batching gain (hw_grid)"],
            ["A4", "SNPE", "not used", "superseded by QAIRT; no LLM story"],
            ["A5", "QAIRT/QNN hand-built context binaries", "not used for the LLM", "1-3 weeks; hand-rolled LLM loop"],
            ["A6", "ONNX Runtime + QNN EP", "host-side calibration only", "same problems as A5 for a 3B LLM"],
            ["A7", "ExecuTorch / MLC-LLM / TFLite", "not tried", "MLC targets the GPU; TFLite irrelevant for a decoder LLM"],
            ["A8", "Qualcomm AI Hub -> Genie bundle", "SHIPPED (Genie era)", "1-3 days; quantises and compiles for SM8650"],
            ["A9", "laptop web app + adb shell per call", "dropped", "not edge: unplug the laptop and the demo dies"],
            ["A10", "Go binary on device (shell user) + PWA", "worked", "laptop-free; shell user can open the NPU"],
            ["A11", "APK running Genie in the app sandbox", "FAILED (14001)", "the vendor DSP service refuses apps (also in permissive mode)"],
            ["A12", "APK + local adbd loopback (127.0.0.1:5555)", "SHIPPED", "app asks the board's own adbd to start the backend as shell"],
            ["A13", "JNI against the Genie C API", "deferred", "would not help: the sandbox cannot open the NPU"],
            ["2.37", "llama.cpp Hexagon backend (htpd)", "SHIPPED (current, opt-in file switch)", "batched agents per weight sweep; patches FA_STREAMS, HMX pipe, drafting, prefix cache"]]
    write("hardware", "hw_platform_paths", "Every runtime path tried on the QIDK and where each ended", "-",
          [ser("paths", [pt(r[0], 1 if "SHIPPED" in r[2] else 0, name=r[1], result=r[2]) for r in rows], "ours")],
          [ROOT / "problems_setup.md", hb_section("4.1"), hb_section("2.37")], S, n=len(rows),
          table={"columns": ["#", "approach", "result", "why"], "rows": rows},
          notes="From problems_setup.md (2026-10-10) plus the htpd move (HANDBOOK 2.37). y=1 marks a shipped path.")
    write("accuracy", "acc_pipeline_parity", "Pipeline identity checks between training and the device", "count",
          [ser("checks", [pt("prompts byte-identical to training", 400, n=400), pt("GPTQ int4 tensors reproduced on device", 1232, n=1232),
                          pt("activation encodings matched when rebuilding w4a16", 11711, n=11711), pt("verify_batch.py identical", 16, n=16),
                          pt("verify_daemon.py identical (fwd + rev)", 28, n=28), pt("ctx 2048 vs 4096 identical", 14, n=14),
                          pt("two-window gate identical", 5, n=5)], "ours")],
          [hb_section("2.7"), hb_section("2.9"), hb_section("2.14"), hb_section("2.22"), hb_section("2.24"), hb_section("2.32"), hb_section("4.4")], S,
          notes="The double-BOS bug: Genie prepends BOS itself (606 host tokens became 607 on device); stripping ours took the same "
                "weights from 67% to 83%. Greedy decoding is forced (the exported bundle defaulted to temp 0.8).")
    write("agent_design", "ad_policy_gate", "Policy gate: transparent repairs raised the agent pass rate on demo scenarios", "fraction",
          [ser("agent pass rate", [pt("before repairs", **rate(3, 6)), pt("with repairs", **rate(5, 6))], "ours"),
           ser("v1 host: evidence valid", [pt("fine-tuned", **rate_from(1.0, 150)), pt("base", **rate_from(0.347, 150))], "alt")],
          [hb_section("2.7"), hb_section("2.33"), TRAIN / "results/agents_20261006_2101/eval.json"], S, n=6,
          notes="Repairs (each recorded in the incident's 'repairs'): action derived from the stated cause, packed evidence ids split, "
                "malformed JSON salvaged from the model's own fields, stray ']' removed. Invented labels are still rejected. A failed "
                "synthesizer answer is replaced by a report built from the agents' findings (Mode 3) or the rules (Mode 2). No actuation "
                "is ever allowed; every recommendation needs a human.")
    write("agent_design", "ad_self_learning", "Self-learning data capture: first real export", "examples",
          [ser("from one approved incident", [pt("SFT positives", 2), pt("DPO pairs (policy-corrected vs raw)", 1)], "ours")],
          [hb_section("2.28"), ROOT / "ppt.md"], S,
          notes="Every LLM call stores prompt, raw output, parsed, valid, errors, repairs; every incident the operator's approval and note. "
                "DPO pairs need no labelling.")
    write("agent_design", "ad_reasoner_plan", "Cross-domain reasoner: why it is a swap, and why it is parked", "MB/s",
          [ser("download speed", [pt("AWS S3 us-west-2 (Qualcomm pre-quantised Qwen3-1.7B, 8.28 GB)", 0.018), pt("HuggingFace (unquantised)", 1.36)], "alt")],
          [hb_section("2.27"), ROOT / "future.md"], S,
          notes="Two full models cannot be resident (the board rebooted with 5.8 GB free), so the reasoner is a per-incident swap "
                "(~+1.5 s on multi-domain incidents). future.md recommends LoRA adapters in one context binary instead of a second model. "
                "Today severity and titles come from a deterministic stub (severity.go, title.go) the reasoner will replace.")
    write("latency", "lat_two_windows", "Two context windows: ctx 2048 by default, ctx 4096 only when a prompt needs it", "s",
          [ser("window swap cost", [pt("load the ctx-4096 dialog", 0.9)], "alt"),
           ser("gate", [pt("outputs identical (normal/large alternating)", **rate(5, 5))], "ours", unit="fraction")],
          [hb_section("2.32"), ROOT / "ppt.md"], S, n=5,
          notes="Switch when estTokens*1.08 + 320 + 40 > 2048. Chaos synthesizer prompts (18+ sensors) need ~3,400 tokens. Evidence is "
                "never trimmed to fit.")
    rows = [["daemon busy-waited on the NPU (359% idle CPU, 94 C)", "poll off for the daemon: 0% idle, same speed"],
            ["thermal guard discarded incidents while hot", "queued, run when the board cools"],
            ["more than 8 alarms: the rest silently dropped", "every alarm analysed (no agent cap)"],
            ["app update left the old backend and UI running", "redeploy on any binary or web change"],
            ["4 of 10 demo scenarios targeted sensors that did not exist", "live fallbacks; Mode 3 fans out again"],
            ["dashboard ~220% CPU at idle, board 75 C", "solid bars, stepped animations: 5-11%, 43 C"],
            ["late abort killed the next NPU query", "aborts tied to query id; zero-token query retried once"],
            ["CO2 270 ppm (below outdoor air) raised nothing", "plausibility rule: sensor fault; disagreement surfaced"],
            ["genied killed mid-answer: truncated text accepted", "detected; CLI re-runs; daemon back in 15 s"],
            ["backend killed mid-analysis: alert vanished", "persisted at creation; 'interrupted - rerun'"],
            ["anyone on the Wi-Fi could approve/inject", "off-device writes need an API token"],
            ["incident log kept every version in RAM", "compaction, newest 1000 kept + archive, crash-safe IDs"],
            ["a failing daemon could load a 2nd model (reboot)", "never two models: port lock, no CLI while genied lives"],
            ["watchdog stuck in rules-only mode", "returns to the NPU backend when adbd is back"],
            ["unbounded queue / bodies", "16 queued requests (429 beyond), 1 MiB bodies, timeouts"]]
    write("app_ux", "ux_hardening", "Production hardening found by testing through the app", "fixes",
          [ser("problems fixed", [pt("hardening fixes", len(rows))], "ours")], [ROOT / "ppt.md", hb_section("2.35"), hb_section("2.31")], S,
          n=len(rows), table={"columns": ["problem found", "fix"], "rows": rows})


if __name__ == "__main__":
    main()
