# Answers to the reviewer's Mode 2 / Mode 3 questions (proof-based, 2026-11-20)

Written by Claude Opus 5 from the repository and the stored proofs. Every answer cites its evidence; where nothing was measured it says so and names the experiment that would settle it. B = `Code/smart-city-edge-agent/app/backend`.

**Bottom line.** The Mode 2 vs Mode 3 latency comparison in the October material is **confounded**:
- Mode 2 and Mode 3 differ in model, not only in architecture: the final stage of Mode 3 is a different model.
- Mode 2 was only ever run on 1–2-domain incidents.
- No prefill token counts were recorded.
- Mode 2 output was checked by the policy gate only, never scored for accuracy.

The numbers we do have are real but cannot carry a "same model, different architecture" claim. A clean claim needs one paired experiment, specified in section D.

---

## A. Blocking

### 1. What does Mode 2 actually run?
- **Code path:** `reason.go`, `switch mode`, `case 2` (around lines 751–777).
  - It builds one prompt with `singlePrompt(inc.Sensors)` (`reason.go:1204`): all flagged and related sensors as evidence blocks, ending "Find the cross-domain root cause.", plus `ReportPrefill`.
  - That prompt goes in **one** call: `r.genie.Run(ctx, r.genie.AgentModel(), …, 120 s)`.
  - Output is the report JSON (label, action, domains, root cause, evidence ids). It passes the same policy gate as Mode 3. A rejected report is never shown, and the rules report stands instead.
- **Model:** the **resident domain-agent model**, `AgentModel()`.
  - October: the fine-tuned Llama-3.2-3B "ft_B50" bundle.
  - Today: `agt3_s0450_q4_0.gguf`, Q4_0 on the Hexagon NPU through htpd.
  - The code comment states the intent: "Mode 2 and the Mode-3 synthesizer use the same bundle as the agents … isolates the comparison to the architecture, not the model."
- **Does Mode 2 swap the reasoner in?** No. Mode 2 never loads the reasoner, so it never pays the swap.
- **Is "same model across modes" true?**
  - It was true for the **original** Mode 3, whose synthesizer used the agent bundle.
  - It is **not** true for Mode 3 as deployed since the reasoner work. With `htpd_profile reasoner=v3` (set on the board today), Mode 3's final stage is `reasonV3` (`reason.go` around line 1024), which runs the Qwen 4B reasoner (`rsn_v3_4b_p2` today; `rsn_v1` in October). That pays the swap; the October measurement was about 2.8–2.9 s.
  - With fewer than 2 domains, Mode 3 skips the final model call and builds an `isolatedReport` (no LLM).
  - So today the two modes differ by **model and architecture**. The "same model" line only holds for the agent stage.
- **Context budget:** agents use `agent_ctx=1280` and the reasoner `reason_ctx=8192` (board profile, 2026-11-20). Mode 2 uses the agent model's context; see question 3.

### 2. Prefill token counts per mode at N = 1, 4, 8, 12
**Not measured as a table.** There are only fragments:
- a 25-sensor synthesizer prompt of about 3,400 tokens;
- "550–1,600" tokens in the October handbook;
- agent data tails of 0.4–1.1 k tokens.

Per-call logs exist (htpd reports tokens per call in `inc.Final` metrics: `ttft_ms`, `gen_tokens`), but nobody exported prefill by N.

**Settles it:** tokenize `singlePrompt` and the Mode 3 agent and reasoner prompts on the host for synthetic incidents with N = 1, 4, 8, 12, using the board's tokenizer files. CPU only, about 1–2 h.

### 3. At what N does Mode 2 hit the 2048 cap, and what happens?
- The 2048 cap belonged to the **Genie** runtime: `genieclient.go` (around lines 278–290) sets `normalWindow = 2048` and `maxAnswer = 320`.
- When a prompt would not leave room for a full answer, the call moves to the **4096-context bundle** (same weights). The code says: "Nothing is trimmed to fit; the window grows instead."
- `singlePrompt` itself never truncates and never drops sensors. Evidence lines per sensor are capped by `evidenceBudget(s)`.
- The board now runs **htpd**, not Genie. The synthesizer/agent context there is 4096 (htpd source, around line 2123).
- **Not measured:**
  - the N at which Mode 2 crosses 2048 or 4096;
  - what htpd does past 4096 (overflow behaviour).
- Nothing **upstream** pre-summarises the sensors for Mode 2: its input is the raw evidence of every sensor. So **Mode 2 is not "secretly a tree"**. The confound is the evidence cap per sensor, not a summariser.

## B. Measurement hygiene

### 4. Timer boundaries
- Both modes report the incident's `total_ms`, measured from incident start to the final report in the app (`inc.TotalMs`). It is the same field for both.
- **Mode 2:** a single call, so `total_ms` is that call plus prompt building.
- **Mode 3:** `total_ms` covers the agents, then the context agents, then the reasoner call. The reasoner swap happens **inside** the reasoner call, and htpd also reports it separately.
- The boundary is therefore the same field. But Mode 3's figure includes a model swap that Mode 2 never has, which is a direct consequence of question 1.

### 5. Paired runs, randomised order, temperature
- The October stress runs (`proofs/2026-10-16_htpd_v6_app_stress_report_final.json` and `proofs/2026-10-21_v2_app/stress/stress_report.json`) ran the **same 10 injected scenarios** in Mode 3 and in Mode 2. So the cases are **paired by scenario**, with one run per scenario per mode.
- **Order was not randomised:** the checklist runs every Mode 3 case first, then every Mode 2 case (`results[]` order).
- **Temperature:** the board temperature was recorded **once, at the start** ("baseline: board below 80 C (52 C)"), not per case. The thermal guard was checked.
- The October chaos stress reached thermal peaks of about 95–96 °C. Mode 2 ran **after** the Mode 3 chaos block, so it ran on a warmer board, which biases against neither mode in a known direction.

### 6. "12 agents → 20.7 s"
- **Source:** `proofs/2026-10-16_htpd_ab/RESULTS.md:24`, "App stress, v6 … chaos 12 agents 20.7 s". Also quoted in `proofs/2026-10-28_master/FACTS_2026-10-29.md:14` ("12-agent incident, all agents | 20.7 s", HANDBOOK 2.37).
- It is the **agent stage** of one Mode 3 chaos incident measured through the app: twelve agents on htpd's parallel streams.
- It is **not** Mode 3 end-to-end. The reasoner stage was separate (about 21.6 s), and the full AI report took 42–47 s.
- It is **not** a Mode 2 number.

### 7. Is any Mode 2 output scored?
- **Policy gate only:** in the v6 stress run, 10 of 10 Mode 2 reports were valid, with no errors. The gate checks the schema and that evidence ids exist.
- **No accuracy scoring** against gold labels.
- **Informal paired comparison** (same 10 scenarios, v6), labels Mode 2 vs Mode 3 per scenario:

| Scenario (incident) | Mode 2 label | Mode 3 label | Agree |
|---|---|---|---|
| ventilation_failure (CO2 rise, KH) | ventilation_issue | ventilation_issue | yes |
| pm_spike (PM2.5, KN outdoor) | air_pollution_event | air_pollution_event | yes |
| power_throttling (power rise, KH) | hvac_or_thermal_issue | power_load_anomaly | no |
| load_surge (power spike, KH-04) | power_load_anomaly | power_load_anomaly | yes |
| tank_leak (tank level, KH-98) | water_supply_issue | normal_operation | no |
| pump_cycling (tank level, KH) | water_leak_or_overuse | water_leak_or_overuse | yes |
| stuck_sensor (temperature flatline) | sensor_fault | sensor_fault | yes |
| heat_buildup (temperature rise, VN) | ventilation_issue | weather_driven | no |
| off_hours_presence (occupancy, KH) | ventilation_issue | occupancy_driven_load | no |
| 2-domain (power + CO2 critical) | weather_driven | power_load_anomaly | no |

Agreement is 5 of 10. Where they differ, Mode 3's label matches the injected scenario in 4 of 5 cases (power_throttling, heat_buildup, off_hours_presence, 2-domain); tank_leak is wrong in both modes. That is an informal reading: no gold file was written and n = 10.

### 8. Has Mode 2 run at N = 8 or 12?
**No.**
- Every recorded Mode 2 incident covered **1 domain**, except one with 2 (v6: reports with 1,1,1,1,1,1,1,1,1,2 domains).
- Mode 3 was the only mode run on the multi-domain chaos incidents (4–6 domains, 11–13 NPU calls).
- The reviewer is right that the interesting failure (prompt length, cross-domain dilution) would sit at N ≥ 8, and it is untested.

### 9. Does htpd log batch occupancy?
**No.**
- htpd only prints "active streams stopped" on timeout.
- There is no per-step log of how many streams are busy, so "width is cheap" is asserted, not plotted.
- **Settles it:** log `active_streams` and the per-step decode time in htpd for one chaos incident. That's a small htpd change plus a single run.

### 10. Is the "tree" depth 2?
**It is deeper than agents → reasoner.** The current pipeline (board, 2026-11-20):
1. **Rules gate**, with the fast path for criticals. The AI is called when 4 of the last 8 readings are abnormal, or right away on history for criticals.
2. **Orchestrator**: groups related sensors across domains.
3. **Domain agents** (NPU, parallel streams) for flagged sensors, plus **context agents** (CPU rules) for linked sensors. Agents may request more data or call tools.
4. **Reasoner** (Qwen 4B, NPU) when 2 or more domains are involved; otherwise `isolatedReport` (no LLM). Then the policy gate, a coverage check and retry, the severity and fault guards, and a rules fallback.
5. **Refinement** at 1.5 h and 3 h re-runs agents and reasoner on longer windows.

No level beyond the reasoner is planned.

### 11. Is latency a hard requirement?
- **In the PRD it was a target:** `PRD.md:90` says "< 15 seconds total end-to-end", and `PRD.md:1266` says "< 15 s (Mode 3)".
- **Measured:** 42–47 s for the full October report. Sensor time dominates either way: the AI waits for 4 of the last 8 readings (20–40 min), or 2 readings on the critical fast path.
- **Owner decision on record:** accuracy first, then latency; the 40–55 min sensor-time gate was accepted.
- So the 28 s vs 31 s compute difference is **not** product-relevant. It is a systems footnote unless the paper is about NPU scheduling.

---

## D. One experiment that settles the blocking questions (about half a day, board)
1. **Same model:** run Mode 2 with the **reasoner** model on `singlePrompt` (call `reasonV3`'s model, without the agents), next to Mode 3 = agents + reasoner. Both pay the same swap.
2. **N = 1, 2, 4, 8, 12** synthetic multi-domain incidents (injected), **paired**, mode order randomised per pair, 3 repeats. Log the board temperature at each start, and cool to 60 °C or below between runs.
3. Log the **prefill tokens**, the TTFT, the swap time (separately), `total_ms`, and htpd **stream occupancy**.
4. **Score** each report against the injected truth: severity, label, evidence-id validity, and grounding (cited ids support the claim).
5. Watch for **overflow** at large N: note where Mode 2 crosses the context limit and what happens.

## E. What is current vs historical
- **Every timing number above is from October:** ft_B50 agent bundle, rsn_v1 reasoner, htpd v6/v8.
- **Today's board:** agent `agt3_s0450`, reasoner `rsn_v3_4b_p2` with `reasoner=v3`, `agent_ctx` 1280, `reason_ctx` 8192, the 4-of-8 gate, and early AI for criticals.
- **Mode 2 has not been re-measured** on today's models.
