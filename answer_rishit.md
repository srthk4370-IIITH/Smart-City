# Answers: Mode 2 / Mode 3 study questions (2026-11-20)

Written by Claude Opus 5. Every answer is checked against the code (B = `Code/smart-city-edge-agent/app/backend`), the stored proofs, or the live board (read today). Unknowns are marked as such. Companion files: `status.md` (project state) and `proofs/2026-11-20_reviewer_modes/ANSWER.md` (the first question set).

**One-paragraph verdict.**
- As built, Mode 2 and Mode 3 differ in far more than architecture: model, information access (tools, more-data rounds, context agents, retrieval memory), retries, guards, context budget, and refinement.
- The October numbers therefore compare **two deployed systems**, not two architectures.
- That is fine for a systems or application claim ("our deployed pipeline vs a single-call baseline"). It cannot support "decomposition alone causes X".
- If the deck makes the architecture claim, it needs either a controlled re-run (section D of `ANSWER.md`) or rewording.
- My recommendation: report the deployed-system comparison honestly now, and run a small controlled ablation for the architecture claim.

---

## A. Decisions that gate the design (owner decisions; my recommendation for each)

**A1. Architecture-controlled comparison, or deployed system?**
- **Facts:**
  - The code compares deployed systems.
  - `reason.go` case 2 calls the **agent model** on one static prompt.
  - Mode 3's final stage calls the **Qwen 4B reasoner** (`reasonV3`, profile `reasoner=v3`, verified on the board today).
  - The code comment claiming "isolates the comparison to the architecture, not the model" was true only before the reasoner existed.
- **Recommendation:** present the deployed-system comparison as the main result. Add a controlled ablation in which both arms use the same model, the same inputs (no tools or retrieval) and the same context budget, for the architecture claim.

**A2. Mode 3's `isolatedReport` short-circuit (fewer than 2 domains, so no LLM final call)?**
- **Fact:** with 1 domain, Mode 3 ends with a rules-built report after the agents. 86% of real incidents are single-domain (D-section data below). So in most real cases "Mode 3" is agents plus a template, not agents plus a reasoner.
- **Recommendation:** keep the short-circuit for the deployed comparison and report how often it fired. For the controlled ablation, force the reasoner on and restrict to N ≥ 2, so you measure the synthesis step itself.

**A3. `singlePrompt` is the old base-model prompt.**
- **Fact:** `reason.go:1204` lists the sensors and ends "Find the cross-domain root cause." No model in deployment was trained on this format. The agent was trained on per-sensor agent prompts, and the reasoner on r3/v4 incident prompts.
- **Effect:** Mode 2 is handicapped by a prompt format its model never saw. That is a real confound against Mode 2.
- **Recommendation:** for the controlled arm, give Mode 2 the **reasoner** model with the reasoner's own incident prompt (the same `buildV4Ctx`-style context the reasoner sees), but with no agent findings. That is the fairest "single call" baseline. In the deployed comparison, document the handicap.

**A4. The real distribution of N.**
- **Measured today:** archived board incidents from 2026-11-17, 433 real (not injected), live campus replay.
  - Flagged sensors per incident: 1 in 85%, 2–4 in 4%, 6 or more in 11% (mostly bursts at replay start-up and batching).
  - Flagged domains: 1 in 86%, 2–4 in 7%, 5 in 7%.
  - Sensors including context: median 4–5, with 12 in 9%.
- **Implication:**
  - N = 8/12 flagged is rare and mostly artefactual (start-up bursts). Claims at N ≥ 8 must be scoped as stress or synthetic.
  - The realistic range for a cross-domain claim is 2–4 domains.
  - **Caveat:** the replay is recorded data streamed again, and real multi-domain events are scarce in it.

**A5. Minimum difference worth detecting.**
- Not set anywhere. Suggested, from what matters to an operator:
  - **Latency:** 5 s is not worth detecting while sensor time is 20–40 min. Use about 30% of compute time (roughly 10 s at 30–45 s), and only for a systems claim.
  - **Label accuracy:** 10 percentage points. With paired binary outcomes, detecting a 10-point difference at 80% power needs roughly 150–200 paired incidents (McNemar, assuming about 20–30% discordant pairs).
- The October n = 10 cannot distinguish "no difference" from "underpowered" (labels agreed on 5 of 10).

**A6. Who scores, and is it blind to mode?**
- **Today:** nobody scores with gold labels. The policy gate checks validity only.
- **Recommendation:** score automatically against injected truth (severity, label, affected domains, evidence-id validity) with the existing v3 scorer. Use a human, or a separate LLM judge, only for root-cause text, given anonymised reports (mode field stripped, order shuffled).

## B. Confounds in the code (all verified)

| # | Confound | Mode 2 | Mode 3 | Evidence | Direction |
|---|---|---|---|---|---|
| B1 | Tool access / more data | none: one static prompt | agents may call tools (`agent_tools=1`, up to 2 calls) and request more data (`agent_more.go`) | board profile; `agent_tools.go` | favours Mode 3 (more information) |
| B2 | CPU context agents | raw evidence blocks only (the context sensors' lines are capped by `evidenceBudget`) | linked sensors judged by rule-based context agents, whose findings feed the reasoner | `reason.go` case 3 | favours Mode 3 |
| B3 | Retrieval memory | no retrieved cases in `singlePrompt` | the reasoner prompt includes retrieved past incidents (memory M# lines) | `retrieval.go`, reasoner v3 prompt | favours Mode 3; may be measuring retrieval, not decomposition |
| B4 | Retry on failure | none: a policy-rejected answer falls straight back to `fallbackReport` (rules) | coverage check plus one retry, severity guard and fault guard | `reason.go:762-772`, `coverage.go`, `reasoner_v3.go` | favours Mode 3 in quality, costs it latency |
| B5 | Draft-based decoding (speculative) | "synth" call on the agent model; whether the agent n-gram corpus drafts help here is **not verified** | reasoner uses verified drafts from `reason_corpus_v2.jsonl` (the 23.3 → 9.1 s win) | profile env `HTPD_REASON_CORPUS`, `HTPD_AGENT_CORPUS` | likely favours Mode 3 in latency; measure it |
| B6 | Refinement at 1.5 h / 3 h | none | yes (`refine.go:78`: `inc.Mode == 3` only) | code | out of scope for a single-report comparison; say so |
| B7 | Decoding | greedy (temperature 0, top-k 1, `genie.go:75`) | greedy (`reasoner_v3.go:792`) | code | same; no seed issue |
| B8 | Context budget | synth context 4096 (`--synth-ctx 4096`) | agents 1280 each; reasoner 8192 (`--reason-ctx 8192`) | live htpd args (read today) | at large N, Mode 2 can run out of window and Mode 3 can't: a quality gap with no architectural cause |
| B9 | `evidenceBudget(s)` | used by `sensorBlock` → `singlePrompt` (flagged: all evidence lines; context: 3 if informative, else 1) | agents get the full per-sensor window; the reasoner gets its own v3/v4 context builder (different budget) | `reason.go:1180` | not identical; Mode 3 sees more per-sensor detail |
| B10 | Concurrent agent streams | n/a | htpd `--agents 10`: N = 12 flagged sensors run as 10 parallel plus 2 queued | live args | N = 12 exceeds the cap: expect a step in latency at N > 10 |

The confounds I would add:
- **B11, model size and family:** Llama 3B for Mode 2 vs Qwen 4B (edited and fine-tuned) for Mode 3's final call.
- **B12, guards:** the severity guard and sensor_fault guard rewrite Mode 3's final severity, and Mode 2 has neither.
- **B13, early AI and promotion:** Mode 3 incidents can be re-run (escalation, promotion, early AI on history), and Mode 2 runs once.

## C. Data, cheapest first (my plan and cost)
1. **Prefill token table, N = 1/2/4/8/12:** host-only, using the board tokenizers and the real prompt builders. 1–2 h. Do first.
2. **Gold file for the 10 injected scenarios:** write the expected severity, label and domains for each scenario (by construction). 30 min.
3. **Mode 2 on the 150-row held-out set (laptop Q4_0, v3 scorer):**
   - The scorer and the held-out set exist. Note: the "RWH 150" naming refers to the earlier real-window held-out set; its exact path needs a check before the run.
   - Arms: Mode 2 as built (agent model plus singlePrompt), and Mode 2-fair (reasoner model, reasoner prompt, no agent findings).
   - About half a day, no board needed. This is the biggest missing comparison.
4. **Per-stage timers on the board:**
   - Mode 3 already logs per-call TTFT and decode, and htpd reports the swap separately.
   - Add the start temperature, a warm or cold flag, and a timer per stage.
   - Small code change, about 1 h.
5. **Policy rejection and fallback rate per mode per N:** comes free with run 3 and the board runs. Mode 2 was 10 of 10 valid at N = 1–2 in October; N = 8 is unknown.
6. **Overflow past 4096:** **unknown.** htpd's behaviour when a synth prompt exceeds `--synth-ctx` (truncate, error or silent drop) is not documented. Test it with a synthetic N = 12 prompt; 30 min.
7. **Evidence coverage by N** (share of the flagged sensors that the report cites): computable from saved reports with the coverage checker (`coverage.go`). Likely the clearest divergence.
8. **Stream occupancy:** htpd doesn't log it. Adding a per-step counter is a small C++ change but needs a rebuild of the htpd binary on the NPU toolchain, so not cheap. Skip unless it's a systems paper.
9. **Energy per report:** no proxy exists yet. ODPM power rails are unverified on this board; the battery fuel gauge plus thermals is the free fallback (HANDBOOK decision). Skip for now.

## D. Facts
- **D1. Is `reasoner=v3` set on the board?** **Yes, read today:**
  - `reasoner=v3`, `reasoner_engine=htpd`, `reasoner_split=3`, `reasoner_prompt=r3`, `reason_ctx=8192`;
  - live htpd args `--reasoner-model …/rsn_v3_4b_p2_q4_0.gguf --reason-streams 3 --reason-ctx 8192`.
- **D2. HANDBOOK ~1263, the planned Mode 1/2/3 grid of about 600 incidents:**
  - **Never run.** There's no grid or results folder for it; `proofs/2026-10-16_hw_grid` is a hardware/runtime grid, a different thing.
  - What exists instead is the October app stress run: 10 scenarios each in Mode 2 and Mode 3, run sequentially, checked by the policy gate only.
- **D3. HANDBOOK ~2512, "Mode 2 ≈ 9 s":**
  - From an early-October latency table (the Genie era, before htpd).
  - The model was the fine-tuned 3B agent bundle of that time (the B-series checkpoints).
  - Single-call incidents with 1 domain, no stated N.
  - The October htpd stress runs later measured Mode 2 at a median of 4.2 s (v6) and 2.5 s (v2 app). **Don't quote the 9 s without these caveats.**
- **D4. PRD under 15 s vs the measured 42–47 s:**
  - **Not logged as a missed target.** `PRD.md:90` and `:1266` still state "< 15 s (Mode 3)" as a target.
  - The FACTS sheet lists the measured latencies without calling them a miss.
  - Recommendation: add an explicit line, "target missed for multi-domain incidents (42–47 s); single-domain 2–8 s; sensor time dominates (20–40 min)".
- **D5. Can the October checkpoints be reproduced?**
  - **Not as GGUFs.** The October GGUFs (ft_B50, rsn_v1, qwen35_reasoner) were deleted from the laptop and the board to free space (owner-approved). Only `.md5` files remain.
  - Re-exporting needs the LoRA adapters plus the bases, which may survive on Kaggle or in run folders. Not verified.
  - So the deck's October numbers are **not currently reproducible bit-for-bit.** The current models can be measured fresh, and that is the safer basis.

## E. Logistics
- **E1. Board time:**
  - Free whenever no reasoner deploy or test runs.
  - The big-reasoner gate runs on the laptop, not the board.
  - Proposed slot: right after the gate decision (tomorrow), about half a day for the controlled set plus N sweeps.
- **E2. Is the board shared during runs?**
  - It runs the live app. Experiments need the app's demo mode on (`demo=1`) for injection, and the live incidents pause on the NPU.
  - One NPU client at a time is a hard rule (`htpd` serves everything).
- **E3. Cooldown from 95 °C to 60 °C:**
  - **Not measured** as a curve. The records show waits "to 82 C" (a ≤ 15 s guard) and evaluation runs at 80–83 °C with cool-down waits.
  - Estimate: a few minutes without a fan. Measure it at the start of the experiment: one curve, 10 minutes.
  - A fan or heatsink would raise runs per day the most (HANDBOOK item 8).
- **E4. Replay real multi-domain incidents instead of injecting?**
  - **Possible.** 40+ archived real incidents have 4–12 sensors and 5 flagged domains, and the campus API serves history.
  - Replaying them through both modes (same windows, frozen) is much stronger evidence than synthetic injections.
  - **Caveat:** many are start-up bursts, so curate them to genuine co-occurring events.
- **E5. Frozen, hashed test set:**
  - Gate sets exist with md5 files (`gate/gate_set.jsonl`, p2 dev sets). The October stress scenarios are regenerated per run (random jitter).
  - For this study, freeze the incident windows (the JSON of every sensor window) with a SHA256 manifest before any run.

## F. Scope
- **F1. Course evaluation, workshop paper or thesis chapter?** That's your decision. The current evidence suits a course evaluation or demo. A workshop paper needs sections C1–C7 plus the controlled ablation and real replays.
- **F2. One paper or two?** Two framings with different baselines:
  - **Systems:** multi-stream NPU serving, split decoding, verified drafts, thermal pacing. The baselines there are llama.cpp CPU/GPU/NPU single-stream.
  - **Application:** multi-agent diagnosis vs single-call vs rules, measured on accuracy, grounding and operator value.

  Don't share a results section. If there is only time for one, the application paper has the stronger story (cross-domain diagnosis on the device), provided the comparison is made fair.

---

## Owner answers (2026-11-20)
1. **Slide 6 deck:** unknown. The substance is answered in A1 / B11: "same model" holds only for the agent stage. Any deck line saying both modes use the same model must be corrected or scoped to "agent stage".
2. **Scope: research paper.** The rigour bar is a paper, so before any architecture claim:
   - a frozen, hashed test set;
   - the prefill table (C1);
   - a gold file (C2);
   - Mode 2-fair vs Mode 3 on held-out data (C3);
   - real multi-domain replays (E4);
   - a pre-set minimum effect and n (A5: ~150–200 paired incidents for a 10-point label difference).

   Keep the systems claim and the application claim in separate result sections (F2).
3. **Multi-domain replay: planned soon** (E4). Curate genuine co-occurring events, not start-up bursts.
