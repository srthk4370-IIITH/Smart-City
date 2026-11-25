# Reviewer questions on Modes (read-only research, 2026-11-20)
Paths relative to repo root. B = Code/smart-city-edge-agent/app/backend. Confidence: H/M/L.

## 1. What Mode 2 runs
- Code (CURRENT build): B/reason.go:752-777. Mode 2 = ONE call `r.genie.Run(ctx, r.genie.AgentModel(), singlePrompt(inc.Sensors)+ReportPrefill ...)`, i.e. the RESIDENT domain-agent model, no swap. Over htpd it goes as kind "synth" (B/htpdclient.go:245; htpd.cpp:9, n_seq=1 context). Comment reason.go:752-755: same bundle as the agents, "isolates the comparison to the architecture".
- Checkpoint: whatever agent is resident. Current board = agt3_s0450 Q4_0 (proofs/2026-11-19_deploy/go.sh:3; AGENT_REGISTRY.md:267). Historical Oct: B50 Llama-3.2-3B blend Q4_0 (proofs/2026-10-28_master/FACTS_2026-10-29.md:6); early Genie era used the GPTQ bundle (HANDBOOK.md:207). rsn_v1 / rsn_v3_4b_p2 (Qwen3.5-4B) are never used by Mode 2.
- Prompt: singlePrompt (reason.go:1202) = reasonerSystem (reason.go:1167) + SENSORS block (sensorBlock; evidence budget: flagged all, informative related 3, steady related 1) + "Find the cross-domain root cause." Llama3 chat template + ReportPrefill. This is the old base-model synthesizer prompt, not the agent-trained prompt and not the reasoner v3/v4 prompt.
- Output schema: JSON {root_cause, label (ReportLabels), affected_domains, evidence ids like S1.E2, confidence, action, explanation}; then checkReport policy gate; if rejected -> fallbackReport from rules (reason.go:765-770).
- "Same model across modes": TRUE for Mode 2 vs Mode 3 agents (both agent model). FALSE for Mode 3 final stage when profile reasoner=v3: Mode 3 hands the final report to the Qwen reasoner (reason.go:1024-1031; reasoner_v3.go:63; htpd "reason" kind unloads agents, loads reasoner: "unloaded 115 ms, loaded 2.9 s" proofs/2026-10-31_agents_latency/VERDICT.md:10; 2.8 s V3_DESIGN.md:85). Mode 2 never pays the swap. Quantisation Q4_0 for all.
- Confidence: H (code). Whether the board profile currently has reasoner=v3 on was not read from the device (L); the 11-20 state says rsn_v3_4b_p2 deployed (go_1j.sh:5).

## 2. Prefill token counts per mode at N=1,4,8,12
- NOT MEASURED as a per-mode / per-N table. Fragments only:
  - estTokens = chars*100/310+1, calibrated 548 tok / 1712 chars (reason.go:1213); ran 4% low on a 25-sensor synth prompt: 3258 est vs 3400 actual (genieclient.go ~285 comment).
  - HANDBOOK.md:2549: "prompts use 550-1,600" tokens (Oct, Mode 2/synth).
  - Agent prompt data tail 0.4-1.1k tokens (VERDICT.md:27); 10-agent batch prefill 6.4 s warm (same file). Synth ~2.5k tokens (htpd.cpp:5).
  - Qwen tool-calling variant 2,373 prefill tokens/report (proofs/2026-10-23_reasoner_research/P0/host_bench/RESULTS.md:53), old design.
- Settle: tokenizer count of singlePrompt / synthPrompt / RenderV3User / RenderV4User on synthetic 1,4,8,12-sensor incidents. Host-only Go test, ~1-2 h, no board.

## 3. Context cap for Mode 2
- Genie era: normal window 2048 (maxAnswer 320, margin 40, +8% pad). needsLargeWindow (B/genieclient.go:278-300) switches to the ctx-4096 bundle; "Nothing is trimmed to fit; the window grows instead". Threshold about 1560 estimated prompt tokens.
- htpd era (current): synth context synth_ctx default 4096 (htpd.cpp:2123); agent ctx 1280 (proofs/2026-11-17_app_test/FINDINGS.md:2). singlePrompt never truncates or pre-summarises; evidence is only budgeted per sensor (evidenceBudget). Behaviour when 4096 overflows: not tested. A 25-sensor prompt was 3400 tokens.
- N at which 2048 is hit: not measured (no N->tokens table).
- Settle: Q2 experiment plus one deliberate overflow run on board, ~2 h.

## 4. Timer start/stop per mode
- Mode 2 (reason.go:757-777): latency = res.LatencyMs of the single Run call (genieclient.go ttft at :142); log "Report from ... in X s (first token ..)". Resident model, so no swap to place.
- Mode 3: stages traced separately (trace "phase ... synth-start/-done", reason.go:1036); with reasoner v3 the swap is INSIDE the reasoner call wall time, reported separately by htpd (load_ms/unload_ms/reload_ms, htpdclient.go:87). Incident wall starts at t0 in analyse().
- No evidence that any published comparison used an identical boundary for both modes (L).

## 5. Paired runs, randomised order, start temperature
- No randomised paired Mode 2 vs Mode 3 experiment found. Oct stress (proofs/2026-10-21_v2_app/stress/console.txt:99, "every scenario in Mode 2") is a sequential pass/fail run, no per-case paired latency. Thermal: stress reports peaks (95-96 C, guard tripped, proofs/2026-10-16_htpd_ab/RESULTS.md:21-26), no start-temperature column. (M)
- Settle: script N cases x {M2,M3} in randomised order, log thermal zone at start; ~0.5 day board.

## 6. "12 agents -> 20.7 s"
- Source: proofs/2026-10-16_htpd_ab/RESULTS.md:24, "App stress v6 ... chaos 12 agents 20.7 s" (stress_app.py chaos scenario, through the app, htpd v6, Oct agents). It is the AGENT STAGE of a 12-agent Mode-3 incident, not whole Mode 3 and not Mode 2. FACTS_2026-10-29.md:14 labels it "12-agent incident, all agents", citing HANDBOOK 2.37. Reasoner report is separate (21.6 s, FACTS:15); full AI report 42-47 s (FACTS:16). Later 10-agent batch: prefill 6.4 s + 33 steps x ~170 ms (VERDICT.md:27-30). Historical, not current board. (H)

## 7. Is Mode 2 output scored?
- Policy gate only (label in ReportLabels, evidence-id validity, actuation); the stress marks "report passed policy". Rejection examples (invented label, prose as evidence id) at reason.go:762-764. No severity/label accuracy scoring of Mode 2 found in proofs. HANDBOOK.md:1263 describes a planned Mode 2 vs Mode 3 grid comparison (Oct Genie era); results not located. HANDBOOK.md:2512 gives Mode 2 ~9 s (Genie, base model). (M)
- Settle: Mode 2 over the RWH 150 held-out incidents on host Q4_0 proxy (207/208 board agreement) with the existing v3 scorer; ~0.5 day host.

## 8. Mode 2 at N=8 or 12?
- Not measured. Oct stress ran Mode 2 on named scenarios (few sensors each); no N=8/12 timing found. (H that no direct evidence exists)
- Settle: injected 8- and 12-sensor incidents in Mode 2 on board, 10 reps each, with Q2/Q3 token counts; ~3 h.

## 9. Does htpd log batch occupancy?
- Not as a production log. htpd.cpp:1741/1988 prints "N active streams stopped" only on timeout. "k=2 (30 rows)" figures in VERDICT.md came from lab harnesses. (M)
- Settle: add per-step n_active counter to htpd stderr/response (small C++ change + rebuild), ~0.5-1 day.

## 10. Pipeline depth (current)
Deeper than agents -> reasoner (B/engine.go, fastpath.go, earlyai.go, reason.go:777-1060, refine.go):
0. Mode-1 rules + K-of-window event gate; critical bypass = fast path, no NPU (5.6 s).
1. Orchestrator: flagged + abnormal-related non-HVAC sensors -> NPU agents; steady related -> deterministic CPU context agents.
2. Domain agents on htpd (batched streams).
3. Final: >=2 domains -> reasonV3 (Qwen rsn_v3_4b_p2, swap, v3/v4 prompt with buildV4Ctx context, retrieval preliminary, policy gate, deterministic fallback); <2 domains -> isolatedReport, no LLM.
4. Refinement at 1.5 h / 3 h windows (Mode 3 only, refine.go:30) plus chat/fog tools.
(H on structure)

## 11. Is latency a hard requirement?
- PRD.md:90 hypothesis: "acceptable latency (< 15 seconds total end-to-end)" - a stated target, not enforced in code; measured full AI report 42-47 s (FACTS:16). Owner memory: accuracy first then latency; 8-reading gate = 40-55 min sensor time accepted for the prototype, critical cases use fast path (FACTS:17). Not a hard gate. (H)

## CURRENT vs HISTORICAL
- Current (2026-11-20 board): agent agt3_s0450, reasoner rsn_v3_4b_p2, agent ctx 1280, Q4_0; 4-of-8 gate stated by caller, not re-verified here.
- Historical (Oct numbers: 20.7 s 12-agent, 21.6 s reasoner, ~9 s Mode 2): B50 agents, rsn_v1, htpd v6/v8x3, Genie bundle early.
- Mode 2 has NOT been re-measured on the current checkpoints.
