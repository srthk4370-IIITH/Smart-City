"""Latency datasets: Genie profile, every optimisation step (kept and rejected), htpd A/B, chaos."""
from _lib import *

S = __file__
T = "latency"
AB = PROOFS / "2026-10-16_htpd_ab"


def m3(xs):
    return round(mean(xs), 1), t_ci(xs)


def profile():
    i, ip = m3([687, 700, 697]); pf, pp = m3([395, 401, 395]); d, dp = m3([2613, 2664, 2662])
    write(T, "lat_call_breakdown", "Where one agent call goes (Genie profiler, live fine-tuned bundle, ctx 4096)", "ms",
          [ser("548-token prompt, 59 tokens out (3 runs, 2026-10-14)",
               [pt("model init", i, lo=ip[0], hi=ip[1], n=3, ci_method="t95"), pt("prefill", pf, lo=pp[0], hi=pp[1], n=3, ci_method="t95"),
                pt("decode", d, lo=dp[0], hi=dp[1], n=3, ci_method="t95")], "ours"),
           ser("800-token prompt, 109 tokens out (2026-10-13)",
               [pt("model init", 635), pt("prefill", 541), pt("decode", 4678), pt("dialog free", 89)], "alt")],
          [hb_section("2.8"), hb_section("2.13")], S, n=3, chart={"type": "stackedBar"},
          claim="Decode is 70-78% of a call: the target is fewer tokens and fewer weight sweeps",
          why="Knowing where time goes stopped us tuning knobs that cannot matter.",
          notes="Prefill ~1380-1481 tok/s, decode ~22-23 tok/s. Measured with Genie --profile; shell `date` arithmetic was wrong (1.67 s vs 5.97 s).")
    write(T, "lat_bandwidth_roof", "Decode is at the memory-bandwidth roof", "GB/s",
          [ser("measured NPU read bandwidth during decode", [pt("ours", 49.3)], "ours"),
           ser("published ceilings", [pt("NPU DMA (DDR->VTCM), V75", 59), pt("whole-device practical peak, 8 Gen 3", 68)], "ref")],
          [hb_section("2.15")], S, chart={"type": "bar"},
          claim="~84% of the measured NPU DMA ceiling: config knobs can save ~440 ms at most",
          notes="2.20 GB of weights stream from DDR per decode token (part 2 901 MB + part 3 1301 MB; part 1 is the embedding "
                "table, one 6 KB row per token). 2.20 GB x 22.4 tok/s = 49.3 GB/s. lm_head (788 MB at 16 bit) is ~36% of traffic.",
          table={"columns": ["part", "size MB", "content"], "rows": [["part_1_of_3", 788, "embedding table (Gather)"],
                                                                      ["part_2_of_3", 901, "transformer layers"],
                                                                      ["part_3_of_3", 1301, "transformer layers + lm_head"]]})


def kept_steps():
    write(T, "lat_async_init", "allow-async-init: true (A/B/A, Genie profiler)", "ms",
          [ser("init (mean of 3)", [pt("false @49 C", 703), pt("false @48 C (control)", 711), pt("true @68 C", 640)], "ours"),
           ser("decode tok/s", [pt("false @49 C", 23.11), pt("false @48 C (control)", 22.78), pt("true @68 C", 22.45)], "alt", unit="tok/s")],
          [hb_section("2.10")], S, n=3, chart={"type": "bar"}, claim="-65 ms per call, init only, no accuracy risk")
    write(T, "lat_ctx2048", "Context 4096 -> 2048: same weights, re-exported (mean of 14 role/pattern prompts)", "ms",
          [ser("ctx 4096", [pt("init", 761.4), pt("prefill (ttft)", 386.6), pt("decode", 3736.8)], "alt"),
           ser("ctx 2048", [pt("init", 768.4), pt("prefill (ttft)", 302.0), pt("decode", 3100.1)], "ours")],
          [hb_section("2.22")], S, n=14, chart={"type": "stackedBar"},
          claim="-721 ms per call, 20.7 -> 25.0 tok/s, 14/14 byte-identical",
          why="The KV buffer is part of every decode step's memory traffic; we used ~610 of 4096 slots.",
          notes="KV cache 469 MB at 4096 vs 235 MB at 2048. End to end on a real 3-call crowded_room incident: 18691 -> 14727 ms. "
                "ctx 1024 rejected: generation reaches ~1120 tokens and synthesizer prompts are longer.",
          extra={"identity": {"identical": 14, "n": 14}, "rate_tok_s": {"ctx4096": 20.7, "ctx2048": 25.0}})
    write(T, "lat_action_trim", "Stop generating the 'action' field that policy derives anyway", "ms",
          [ser("baseline", [pt("agent call", 3838.9, chunks=58)], "alt"), ser("trim", [pt("agent call", 3640.1, chunks=55)], "ours")],
          [hb_section("2.18"), hb_section("2.21"), hb_section("2.10")], S, chart={"type": "bar"},
          claim="-199 ms per agent call; 14 findings checked, 0 problems",
          notes="First attempt (2.10) was rejected: a comma straddling a read boundary produced invalid JSON. Fixed with a []byte "
                "buffer and 16-byte holdback. Must apply to agent calls only (2.21: trimming the synthesizer broke its report).")
    write(T, "lat_genied", "genied: one persistent Genie dialog instead of a process per call", "ms",
          [ser("per-call CLI", [pt("single agent call", 3640), pt("time to first token", 1200)], "alt"),
           ser("genied daemon", [pt("single agent call", 2543), pt("time to first token", 312)], "ours")],
          [hb_section("2.24"), hb_section("2.19")], S, chart={"type": "bar"},
          claim="3640 -> 2543 ms per call; first token 1.2 s -> 0.31 s; 28/28 identical",
          notes="Gate: verify_daemon.py, 14 prompts forward then reverse = 28/28 byte-identical. poll must be off in a daemon: "
                "with poll on genied idled at 359% CPU and drove the board to 94 C; poll off: 0% idle, same speed (3670 vs 3686 ms).",
          extra={"identity": {"identical": 28, "n": 28}, "idle_cpu_pct": {"poll on": 359, "poll off": 0}})
    write(T, "lat_gap_sweep", "Inter-call gap re-measured: decode rate of the second call (tok/s)", "tok/s",
          [ser("ascending", [pt("0.0 s", 22.53), pt("0.2 s", 22.20), pt("0.3 s", 21.94), pt("0.4 s", 22.31), pt("0.6 s", 22.31), pt("1.0 s", 22.29)], "ours"),
           ser("descending", [pt("0.0 s", 22.43), pt("0.3 s", 22.42), pt("0.6 s", 22.44), pt("1.0 s", 22.10)], "alt")],
          [hb_section("2.20"), hb_section("5")], S, chart={"type": "line"},
          claim="No cliff any more: gap 600 -> 250 ms (CLI), 0 ms with genied",
          notes="2026-10-07 (base model, before async init) a back-to-back session decoded at ~9 instead of ~19 tok/s. "
                "Real 3-call incident: 17726 -> 17393 ms. The 2500 ms bundle-change gap was kept.")
    write(T, "lat_genieapp_batch", "genie-app: N queries in one process (init paid once)", "s",
          [ser("total wall time", [pt("1", 3.920), pt("2", 7.022), pt("3", 10.120), pt("5", 16.537)], "ours")],
          [hb_section("2.13"), hb_section("2.14")], S, chart={"type": "line", "x": "queries in one process"},
          claim="3.15 s per extra query vs 3.74 s per CLI call; 16/16 byte-identical",
          notes="Through the Go code: 3 prompts per-call 16.41 s vs batched 13.748 s (1331 ms per extra prompt incl. the 600 ms gap). "
                "On a real multi-agent incident batch OFF 18691 ms vs ON 17726 ms. Batching was turned off while genied is up "
                "(a second model copy hits the DSP SMMU limit).")
    write(T, "lat_phase_trace", "Inside one 3-call incident (genied, SCE_GENIE_TRACE=1)", "ms",
          [ser("phase", [pt("agents (2617 + 4488)", 7112), pt("synthesizer", 4457), pt("non-model time", 11)], "ours")],
          [hb_section("2.29")], S, chart={"type": "stackedBar"},
          claim="11.57 s total, of which ~11 ms is app overhead")
    write(T, "lat_batch_window", "Event-gate batch window: closes early when no other sensor is waking up", "s",
          [ser("before", [pt("power_throttling (isolated)", 6.0), pt("ventilation_failure (isolated)", 6.0), pt("crowded_room (2 sensors)", 6.0)], "alt"),
           ser("after", [pt("power_throttling (isolated)", 2.0), pt("ventilation_failure (isolated)", 2.0), pt("crowded_room (2 sensors)", 4.0)], "ours")],
          [hb_section("2.29")], S, chart={"type": "bar"}, claim="-4 s on every isolated incident, cross-domain batching intact",
          notes="crowded_room 'before' was >= 6.0 s. Measured from the gate's own trace.")
    write(T, "lat_word_limits", "Word limits on free-text fields (synthesizer)", "tokens",
          [ser("before", [pt("synthesizer output", 187)], "alt"), ser("after", [pt("synthesizer output", 111)], "ours")],
          [hb_section("5")], S, chart={"type": "bar"},
          notes="184-190 -> 102-120 tokens (midpoints shown), ~11 s -> 7-8 s per synthesizer call. Label, evidence, action unchanged.")
    write(T, "lat_genie_settings", "Genie runtime settings (base model, 200-token generations)", "s",
          [ser("wall for 200 tokens", [pt("3 threads, mask 0xe0 (old)", 11.9), pt("4 threads, mask 0xf0 (used)", 11.7),
                                         pt("use-mmap false", 14.4), pt("poll false", 12.4)], "ours")],
          [hb_section("5"), hb_section("2.8")], S, chart={"type": "bar"},
          notes="Init 0.67/0.65/3.0/0.68 s; decode 18.9/19.2/18.9/18.2 tok/s. poll=false A/B/A on the fine-tune: 21.0 vs 22.6-22.9 tok/s (7-8% slower).",
          table={"columns": ["config", "decode tok/s run1", "run2", "run3", "temp C"],
                 "rows": [["poll=true", 22.9, 22.4, 22.6, 46], ["poll=false", 21.0, 21.0, 20.8, 54], ["poll=true (control)", 22.6, 22.4, 23.0, 57]]})


def rejected_summary():
    ideas = [  # (idea, time change % vs the shipped config, identical answers k/n or None, why rejected)
        ("LADE lookahead decoding", round((1846 - 2733.5) / 2733.5 * 100, 1), (1, 14), "answers changed; stuck sensor -> 'normal'"),
        ("continuous batching (shared engine)", -76.0, (1, 12), "'speedup' was truncated answers"),
        ("grammar-constrained decoding", round(((1163 + 2765.5) - (713 + 2613)) / (713 + 2613) * 100, 1), None, "+440 ms init, 0 tokens saved"),
        ("3-graph bundle", round((4291 - 3738) / 3738 * 100, 1), (12, 12), "slower on every call"),
        ("DSP RPC knobs", round((2681 - 2638.5) / 2638.5 * 100, 1), None, "within noise"),
        ("two NPU sessions in parallel", round((76.5 - 23.6) / 23.6 * 100, 1), None, "3x slower; crashed the board once"),
        ("GPU instead of NPU (1 agent)", round((10.01 - 3.93) / 3.93 * 100, 1), None, "slower at every size; no valid JSON at ctx 4096"),
    ]
    write(T, "lat_rejected_ideas", "Tried and rejected: speed-ups that were slower or changed the answers", "% time change",
          [ser("time change vs shipped (negative = faster)", [pt(i, d, why=w) for i, d, _, w in ideas], "alt"),
           ser("identical answers", [pt(i, **rate(*k)) for i, _, k, _ in ideas if k], "ref", unit="fraction")],
          [hb_section("2.12"), hb_section("2.13"), hb_section("2.14"), hb_section("2.16"), hb_section("2.25"), hb_section("5"),
           PROOFS / "2026-10-16_hw_grid/samples.jsonl"], S, chart={"type": "bar"},
          claim="The two fastest ideas were wrong: 1 in 14 and 1 in 12 answers identical",
          why="A fast wrong answer is worse than a slow right one; every change is gated on output identity.",
          notes="LADE: decode time on one prompt, FWD_LEVEL vs basic (-32.5%); over all 14 prompts it was about -20% decode (lat_rejected_lade). Continuous batching: apparent 76% speed-up from truncation. Grammar/3-graph: "
                "init+decode or total per call. Parallel: 2 x 200-token calls. GPU: grid INC-0407 vs Genie. Pre-warming the CLI was "
                "impossible (Genie reads the prompt to EOF first).")


def rejected():
    rejected_summary()
    write(T, "lat_rejected_lade", "Rejected: LADE lookahead decoding is fast and wrong", "ms",
          [ser("decode, single prompt", [pt("basic", 2733.5), pt("ALWAYS_FWD_ONE", 1889), pt("FWD_MAX_HIT", 1933.5), pt("FWD_LEVEL", 1846)], "alt"),
           ser("identical answers over 14 role/pattern prompts", [pt("FWD_LEVEL vs basic", **rate(1, 14))], "ref", unit="fraction")],
          [hb_section("2.14")], S, n=14, chart={"type": "bar"},
          claim="-20% decode, but 1 in 14 answers identical; a stuck sensor became 'normal'",
          why="A fast wrong answer is worse than a slow right one.",
          notes="First A/B (one prompt, repeated) looked like a clean 14% win: 3947 -> 3380 ms. On 24 different prompts answers "
                "diverged ('flatline'/'sensor_fault' -> 'flat78'/'normal', PM10 -> PM2.5). Minimal setting window=gcap=4 ngram=3: "
                "4/13 identical and slower (18.2 vs 19.7 tok/s).")
    write(T, "lat_rejected_grammar", "Rejected: grammar-constrained decoding (xgrammar JSON schema)", "ms",
          [ser("baseline", [pt("init", 713), pt("decode", 2613)], "ours"), ser("grammar", [pt("init", 1163), pt("decode", 2765.5)], "alt")],
          [hb_section("2.16")], S, n=2, chart={"type": "bar"}, claim="+440 ms init, 0 tokens saved",
          notes="Means of 2 runs (init 695/731 vs 1130/1196; decode 2574/2652 vs 2750/2781; 59 vs 62 tokens). Jump-forward only "
                "exists in draft-engine dialogs (eaglet/spd).")
    write(T, "lat_rejected_multigraph", "Rejected: 3-graph bundle (for LADE) is slower than the live 2-graph bundle", "ms",
          [ser("live, 2 graphs", [pt("init", 695), pt("ttft", 397), pt("decode", 2646), pt("total", 3738)], "ours"),
           ser("3 graphs, basic", [pt("init", 845), pt("ttft", 597), pt("decode", 2849), pt("total", 4291)], "alt")],
          [hb_section("2.12")], S, chart={"type": "bar"},
          notes="It first failed to load with err 1002 (CDSP SMMU refusing a 112 MB mapping); enable-graph-switching: true fixed "
                "loading. A 6.4 MB larger part3 was the difference. Only add graphs if they buy > ~550 ms.")
    write(T, "lat_rejected_rpc", "Rejected: DSP RPC knobs do not touch decode", "ms",
          [ser("decode", [pt("rpc_control_latency 100 (live)", 2638.5), pt("rpc_control_latency 0", 2643),
                          pt("rpc 0 + polling 9999", 2681)], "alt")],
          [hb_section("2.13"), hb_section("2.26")], S, n=2, chart={"type": "bar"},
          notes="All within noise. mmap-budget 0 -> 25 changed init by noise only; direct-io produced no output; llm_decode_* profiles are V79+ only.")
    write(T, "lat_rejected_continuous_batching", "Rejected: Genie shared-engine continuous batching truncates answers", "fraction",
          [ser("identical answers, 3 prompts concurrently", [pt("shared-engine slots", **rate(1, 12))], "alt")],
          [hb_section("2.25")], S, n=12, claim="The 76% 'speedup' was answers stopping early",
          notes="Sequential on the same shared-engine daemon every answer was cut after 300-480 ms. -slots stays default 1 (re-verified 28/28).")
    write(T, "lat_rejected_parallel_npu", "Rejected: two Genie sessions in parallel on one NPU (2 x 200 tokens)", "s",
          [ser("wall time", [pt("sequential, back-to-back", 33.8), pt("sequential, 0.5 s gap", 23.6), pt("parallel (B starts 2 s after A)", 76.5)], "ours")],
          [hb_section("5")], S, chart={"type": "bar"},
          notes="Parallel: 4.9 / 10.0 tok/s, B waited 54 s to initialise; one Genie session uses ~3.7 GB; the first parallel attempt crashed the board.")
    write(T, "lat_rejected_prewarm", "Rejected: pre-warming genie-t2t-run / streaming a script to genie-app", "s",
          [ser("query line written -> output appeared", [pt("unpadded", 60), pt("+5 KB padding", 82)], "alt")],
          [hb_section("2.13"), hb_section("2.19")], S,
          notes="Genie reads the whole prompt (and genie-app the whole script) before touching the DSP: execution tracks EOF. "
                "mkfifo is refused by SELinux everywhere. A persistent engine needed the C API -> genied.")


def htpd():
    rows = []
    for line in text(AB / "RESULTS.md").splitlines():
        m = re.match(r"\| (v[^|]+?) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([^|]+) \|", line)
        if m:
            rows.append([m.group(1).strip()] + [float(m.group(i)) for i in range(2, 7)] + [m.group(7).strip()])
    cols = ["config", "4 agents s", "8 agents s", "13 agents s", "total s", "prefill 13 s", "identical"]
    final = [r for r in rows if r[0].startswith("v6")][0]
    v1 = [r for r in rows if r[0].startswith("v1")][0]
    write(T, "lat_htpd_ab", "htpd A/B harness: 3 real incidents (4, 8, 13 agents), agents only", "s",
          [ser(r[0], [pt("4 agents", r[1]), pt("8 agents", r[2]), pt("13 agents", r[3])], "ours" if r[0].startswith("v6") else "alt") for r in rows],
          [AB / "RESULTS.md", AB / "ab.py", AB / "ab.sh", AB / "ab2.sh", AB / "ab3.sh"], S, chart={"type": "bar"},
          claim=f"13 agents {v1[3]} s -> {final[3]} s; identical texts 25/25 vs v5",
          notes="Board cooled below 55 C before each config; total = rep 2 of 2. Run-to-run identity noise floor (same binary twice): 21-24/25.",
          table={"columns": cols, "rows": rows})
    write(T, "lat_htpd_levers", "htpd: what each change bought (QIDK, 13-stream agent context)", "s",
          [ser("before", [pt("HMX pipe (13 agents)", 29.5), pt("drafting (13 agents)", 22.0), pt("drafting (4 agents)", 14.9),
                          pt("prefix cache prefill (13)", 8.7), pt("prefix cache prefill (4)", 3.1), pt("NEON argmax (A/B total)", 30.3)], "alt"),
           ser("after", [pt("HMX pipe (13 agents)", 24.0), pt("drafting (13 agents)", 16.4), pt("drafting (4 agents)", 5.8),
                         pt("prefix cache prefill (13)", 6.8), pt("prefix cache prefill (4)", 2.0), pt("NEON argmax (A/B total)", 27.7)], "ours")],
          [hb_section("2.37"), AB / "RESULTS.md"], S, chart={"type": "bar"},
          notes="HMX pipe 'before' is the 28-31 s range midpoint. GGML_HEXAGON_FA_STREAMS=1 (per-stream flash attention on HTP) is "
                "what made batching faster than sequential at all. Drafting is lossless: a draft is kept only when it equals greedy. "
                "NEON argmax 25/25 identical. HTPD_LEGACY_PREFILL keeps the old prefill order (equal-ubatch changed ~30% of outputs). "
                "Rejected: speculation on the synthesizer (changed outputs), 8-bit KV (2x slower), thread/ubatch/power knobs.")
    write(T, "lat_chaos_genie_vs_htpd", "Through the app: chaos incidents, Genie vs htpd (final)", "s",
          [ser("Genie (genied)", [pt("12 agents + synth", 47), pt("10 agents + synth", 43.5), pt("11 agents, staggered", 53),
                                   pt("A/B 13 agents (agents only)", 23.5), pt("A/B 4 agents", 15), pt("Mode 3 median", 3.8)], "alt"),
           ser("htpd final", [pt("12 agents + synth", 20.7), pt("10 agents + synth", 20.6), pt("11 agents, staggered", 20.8),
                              pt("A/B 13 agents (agents only)", 14.7), pt("A/B 4 agents", 4.8), pt("Mode 3 median", 3.8)], "ours")],
          [hb_section("2.37"), PROOFS / "2026-10-16_htpd_v6_app_stress_report_final.json", PROOFS / "2026-10-16_htpd_v6_app_stress_tail.log"],
          S, chart={"type": "bar"}, claim="≈ 47 s -> 20.7 s for a 12-agent incident (QIDK, through the app)",
          why="Decode is bandwidth-bound, so serving all agents in one weight sweep is the lever.",
          notes="Genie values are midpoints of the HANDBOOK ranges (46-48, 41-46, 49-57, 22-25 s). Small incidents are about equal (3.8 s median).")


def routes():
    call = [("Genie CLI, ctx 4096 (fine-tuned)", 3947, "baseline", "2.14"),
            ("allow-async-init", 3882, "-65 ms init", "2.10"),
            ("ctx 4096 -> 2048", 3161, "-721 ms", "2.22"),
            ("stop before 'action'", 2962, "-199 ms", "2.18"),
            ("genied persistent dialog", 2543, "3640 -> 2543 ms measured", "2.24")]
    write(T, "lat_route_agent_call", "Latency route, one agent call (Genie era)", "ms",
          [ser("agent call", [pt(n, v, delta=d, section=s, derived=(0 < i < len(call) - 1)) for i, (n, v, d, s) in enumerate(call)], "ours")],
          [hb_section(s) for _, _, _, s in call], S, chart={"type": "waterfall"},
          claim="~3.9 s -> 2.5 s per agent call before the move to htpd",
          notes="Each step was measured on its own (different prompts/days); intermediate bars apply the measured deltas to the "
                "first value, the last bar is the directly measured genied number. Not an additive experiment.")
    inc = [("crowded_room, batch OFF (Genie CLI)", 18691, "2.17"), ("genie-app batching ON", 17726, "2.17"),
           ("inter-call gap 600 -> 250 ms", 17393, "2.20"), ("ctx 2048 bundle", 14727, "2.22"),
           ("genied + zero gap (trace)", 11570, "2.29")]
    write(T, "lat_route_incident", "Latency route, one 3-call cross-domain incident (crowded_room)", "ms",
          [ser("incident analysis", [pt(n, v, section=s) for n, v, s in inc], "ours")],
          [hb_section(s) for _, _, s in inc], S, chart={"type": "waterfall"},
          claim="18.7 s -> 11.6 s for the same 3-call incident",
          notes="Plus the event-gate batch window: -4 s isolated, -2 s cross-domain (lat_batch_window), outside the analysis time.")
    big = [("Genie (genied), 13 agents", 23.5, "2.37"), ("htpd v1", 28.1, "AB"), ("htpd v4: HMX pipe + legacy prefill + drafting", 17.5, "AB"),
           ("htpd v5 + prefix cache", 15.5, "AB"), ("htpd v6: NEON argmax", 14.7, "AB")]
    write(T, "lat_route_13_agents", "Latency route, 13 agents in one incident (agents only, A/B harness)", "s",
          [ser("13 agents", [pt(n, v) for n, v, _ in big], "ours"),
           ser("4 agents", [pt("Genie (genied), 13 agents", 15.0), pt("htpd v1", 15.3), pt("htpd v4: HMX pipe + legacy prefill + drafting", 6.2),
                            pt("htpd v5 + prefix cache", 5.2), pt("htpd v6: NEON argmax", 4.8)], "alt")],
          [AB / "RESULTS.md", hb_section("2.37")], S, chart={"type": "waterfall"},
          claim="13 agents: 22-25 s on Genie -> 14.7 s on htpd v6",
          notes="Genie 13-agent value is the midpoint of 22-25 s. The first htpd was slower than Genie (28.1 s) until HMX pipelining and drafting.")


def main():
    profile(); kept_steps(); rejected(); htpd(); routes()


if __name__ == "__main__":
    main()
