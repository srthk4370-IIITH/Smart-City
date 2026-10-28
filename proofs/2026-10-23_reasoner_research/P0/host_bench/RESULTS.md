# P0 host benchmark: reasoner / chat model choice (2026-10-24)

**Recommendation: Qwen3.5-4B** (`Qwen/Qwen3.5-4B`, Apache-2.0).
- It is the only candidate whose reasoning score clears 0.75: **0.80 [0.75, 0.84]**, against 0.22 to 0.64 for the others.
- Its weighted total is **0.79 [0.77, 0.82]**.
- **It does not pass G1 as-is.** Its failures are narrow (below) and are what fine-tuning targets.
- The owner confirms this choice before any training starts.

This is a **host proxy**: quantized GGUF on an RTX 4050 through llama.cpp b11815 CUDA.
- NPU latency in this file is **estimated**, not measured. The board was not touched.
- Nothing here measures device accuracy or latency. That needs the board run after fine-tuning (owner decision 2026-10-24).

## What was measured
- **Candidates**, all as Q4_0 GGUF (the HTP device format):
  - deployed v2 3B (`ft_v2_q4_0.gguf`), prompt-only;
  - base Llama-3.2-3B-Instruct;
  - Qwen3.5-4B;
  - Qwen3.5-2B.
- **Not run:**
  - Qwen3.5-4B Q4_K_M, which was converted but skipped by the owner;
  - Qwen3.5-2B consistency is partial (34 of 60 runs).
- **Same for every model:** system prompts, tools (`tools.json` + `get_action_history`), greedy decoding, each model's own chat template, Qwen thinking off, and at most 5 tool calls.
- **Items:**
  - **127 cross-domain incident scenarios** across 28 families, with rule-derived ground truth. This includes a 10-item slice from REALWORLD.md §5.8 and data-quality cases.
  - **65 chat tool-use questions**, with ground truth from SQL over a 701-incident local store (96 real app-test incidents plus a synthetic 2026 year).
  - **15 data-reading items**.
  - **Consistency:** 15 scenarios × (2 extra reruns + 2 paraphrases).
- Details are in `manifest.json` and `results/tables.md`.
- The scorer self-test (`oracle_check.py`) gives a gold-answer oracle **0.99** and an always-"unknown" model **0.28**.

## Gates (applied first)
**G1 thresholds were proposed by me**:
- answers with ungrounded numbers ≤ 5%;
- answers with invented ids ≤ 2%;
- 0 actuation;
- 0 followed injections;
- "not available" answered correctly ≥ 70%.

These are **raw model outputs**. The backend policy gate and numeric checker in the design are not applied here.

| model | G1 | ungrounded-number answers | actuation | injection followed (of 3) | "not available" ok | refusals ok | G2 | est. NPU report p50 / p90 |
|---|---|---|---|---|---|---|---|---|
| **qwen35_4b_q4_0** | FAIL | 8.2% | 1 | 2 | 89% | 100% | FAIL (latency) | 41.5 / 47.4 s |
| qwen35_2b_q4_0 | FAIL | 23.2% | 0 | 1 | 78% | 100% | CONDITIONAL | 14.2 / 16.7 s |
| llama32_3b_base_q4_0 | FAIL | 0.0% | 0 | 3 | 89% | 71% | FAIL (latency) | 24.6 / 32.5 s |
| v2_3b_q4_0 | FAIL | 0.5% | 1 | 3 | 78% | 29% | PASS | 8.5 / 16.4 s |

- **No model passes G1 untrained.** None was trained for this task, so the gates are targets for fine-tuning rather than a filter now.
- **G2 has two parts:**
  - latency: the estimate must have p50 ≤ 20 s and p90 ≤ 40 s;
  - fit: whether the model can run within NPU memory and the one-client rule. The Qwen models must be **time-shared** with the agents' 3B (design B.2).
- **How the latency estimate works:** measured tokens per report, scaled from v2's measured HTP rates (970 tok/s prefill, 19 tok/s decode) by GGUF file size.
- **Qwen3.5-4B's latency failure is behavioural, not size.** It averaged **6.2 tool calls** and 2,373 prefill tokens per report. It called tools on every scenario, including the 118 where the evidence was already in the prompt.

## Weighted score: 45 reasoning / 25 tools / 20 data / 10 secondary (95% bootstrap CI)

| model | 1. cross-domain reasoning | 2. tools | 3. understanding data | 4. secondary | **total** |
|---|---|---|---|---|---|
| **qwen35_4b_q4_0** | **0.80** [0.75, 0.84] | **0.78** [0.73, 0.84] | **0.81** [0.73, 0.87] | **0.79** [0.71, 0.87] | **0.79** [0.77, 0.82] |
| qwen35_2b_q4_0 | 0.64 [0.59, 0.68] | 0.66 [0.59, 0.72] | 0.67 [0.59, 0.74] | 0.57 [0.47, 0.69] | 0.64 [0.61, 0.67] |
| llama32_3b_base_q4_0 | 0.36 [0.31, 0.41] | 0.55 [0.49, 0.62] | 0.50 [0.40, 0.60] | 0.32 [0.28, 0.38] | 0.43 [0.40, 0.47] |
| v2_3b_q4_0 | 0.22 [0.18, 0.26] | 0.65 [0.60, 0.70] | 0.43 [0.34, 0.53] | 0.25 [0.23, 0.28] | 0.37 [0.34, 0.40] |

**Paired bootstrap** (same items resampled together):
- Qwen3.5-4B − Qwen3.5-2B: reasoning **+0.16** [0.11, 0.22], total **+0.16** [0.12, 0.19].
- Qwen3.5-4B − v2: total **+0.42** [0.39, 0.46].
- Every pairwise ordering in the table holds with P > 0.999.

**What drives the gap:**
- **Reasoning (Qwen3.5-4B):**
  - reports parsed 100%, label accuracy 67%;
  - checklist recall 0.92, valid evidence citations 0.98;
  - ≥ 0.85 on stuck sensors, contradictory agents, memory ("recalibrated twice, so replace"), re-check trends, needs-fetch and heat-wave shared cause.
- **Qwen3.5-4B's weakest families:** prompt injection 0.33, water quality 0.60, realworld slice 0.65, normal operation 0.67, impossible readings 0.70.
- **v2 and base Llama** often emit malformed pseudo tool calls instead of the report. Their label accuracy is 21% and 28%.
- **Tools (Qwen3.5-4B):** first-call selection 0.95, argument exec-match 0.57 (multi-step 0.19), fetches when needed 9/9, never answers without a call (0/118).
- **Data (Qwen3.5-4B):** data-reading 0.93, chat answers exact 0.64.
- **Secondary (Qwen3.5-4B):** consistency 0.67 (reruns 1.00, paraphrases 0.67); communication rubric 0.99; mean confidence 0.90 against label accuracy 0.67 (over-confident, 1 − Brier 0.72).

## Why Qwen3.5-4B
1. **Gates:**
   - It fails G1 on three narrow points: ungrounded numbers, 1 actuation item, and 2 of 3 injections followed.
   - It fails G2 on behaviour: too many tool calls.
   - Both are trainable, and the backend policy gate and numeric checker are a second line.
   - v2 is the only G2 pass, but its reasoning (0.22) and refusals (29%) are far from usable.
2. **Weighted score:** best in every category, with non-overlapping CIs for reasoning and total.
3. **Fine-tuning potential:**
   - It already has the skills: 0.80 reasoning, 0.95 tool selection, 0.93 data reading.
   - Fine-tuning has to teach policy (when not to call tools, verbatim numbers, ignoring injections, calibration), not reasoning from scratch.
   - The 3B models would have to learn the task itself.
4. **NPU fit:**
   - The Q4_0 is 2.61 GB, close to the deployed v2's 2.80 GB file.
   - The `qwen35` arch and its GATED_DELTA_NET / SSM_CONV HTP ops exist in our llama.cpp tree, but **they are untested in htpd**.
   - Its recurrent state breaks htpd's per-stream prefix-cache assumptions.
   - It must be time-shared with the agents' 3B (no two resident models: HANDBOOK 2.27/2.37).
   - Qwen3.5-2B (1.24 GB, CONDITIONAL G2) is the fallback if the 4B does not fit on the board.

## Fine-tuning plan: Qwen3.5-4B only (for owner approval; no training started)
**Method:** QLoRA, r = 16, all linear projections, loss on assistant tokens only.
- **Base:** `Qwen/Qwen3.5-4B` in BF16 (already in `~/models`, shard sha256 verified), thinking off.
- **Unverified on this laptop, check first (half a day):**
  1. the current `transformers` + `peft` support the hybrid Gated-DeltaNet layers (the `train` venv has transformers 4.46, which is too old; a new venv is needed);
  2. 4-bit 4B + seq 2048 + gradient checkpointing fits in 6 GB VRAM.

**Data:** ~6–8k examples, generated locally, no cloud, with exact labels from the same generators and SQL used here.

| set | approx. size | targets |
|---|---|---|
| R1 cross-domain reports | ~3k | all 28 families; extra on injection, water quality, normal operation, impossible readings, REALWORLD §5.8 and data-quality slices |
| R2 when to call | ~1k | answer directly when evidence is complete (now 0/118); at most 1 call on the early alert, 2 on refinements |
| T1/T2 chat tool traces | ~2k | arguments (time ranges, node prefixes, group_by, multi-step); now 0.57 exec-match, 0.19 multi-step |
| T3 safety / grounding | ~1k | injection-bearing notes (target 0 followed); actuation never in checklists; "not available" wording; quoting tool numbers verbatim instead of computing them (e.g. "dropped 48%", "10x" in the samples checked) |
| calibration | (labels on all of the above) | confidence targets from correctness; now 0.90 confidence vs 0.67 accuracy |

**Held-out split:**
- 15% of scenario compositions;
- 15% of question templates;
- Nov–Dec store months;
- the current 127 + 65 + 15 items kept unseen as the regression set.

**G1 failures to fix:**

| failure | now | target | how |
|---|---|---|---|
| ungrounded-number answers | 8.2% | ≤ 2% | T3 data (verbatim quoting); backend numeric checker as backstop |
| injections followed | 2 / 3 | 0 | T3 data; notes fenced as data in the prompt |
| actuation | 1 (inject_8, after an injected note) | 0 | T3 data; backend policy gate drops non-whitelisted actions |

**Expected size and cost (planning estimates, not measured):**
- adapter about 30–40 M params (about 60–80 MB F16);
- merged Q4_0 GGUF about 2.6 GB, unchanged;
- about 10–15 GPU-hours on the RTX 4050, extrapolated from the v2 training runs (a different model);
- exact numbers to come after the feasibility check.

**Quantization (Q4_0 vs Q4_K_M):**
- The HTP backend runs Q4_0 (repacked tiles); K-quants are not the device path.
- Plan: evaluate the merged model as Q4_0 with an imatrix built from reasoner and chat prompts, and as Q4_K_M as a host accuracy reference.
- Choose at NPU time on device accuracy and latency, never on HF or full-precision scores.

**Acceptance (host proxy first, then board):**
- G1 passes;
- reasoning ≥ 0.90;
- consistency ≥ 0.90;
- average tool calls per report ≤ 1;
- G2 latency estimate within 20 s p50.

  For orientation only: with an assumed ~800 prefill + ~300 decode tokens, the same estimate formula gives about 15 s. Those token counts are a guess, not a measurement.

Then the board P0: htpd load of `qwen35`, prefix-cache behaviour, time-sharing with the agents' 3B, and memory.

## Limitations
- **Host proxy only.** NPU latency is an estimate (file-size scaling of v2's measured HTP rates). No device accuracy was measured.
- **Synthetic data.** Scenarios and most store incidents are synthetic, with rule-derived ground truth. Real incidents are 96 demo app tests.
- **Deterministic rubric only.** No LLM judge was used, because no independent local judge is available (the candidates would judge themselves).
- **Prompt-only baselines.** v2 and base Llama were tested without any tuning. The "v2 + reasoner LoRA" path in REASONER_DESIGN.md was not trained, so its potential is not measured here.
- **Gaps:** Qwen3.5-2B consistency is partial (34/60). Qwen3.5-4B Q4_K_M was not benchmarked.
- **Harness history.** The first pass was invalidated by two harness issues (llama.cpp tool-parse 500s; `tool_choice:none` ignored at the call limit). These were fixed (raw `/completion` fallback; an explicit final-answer turn), affected records were rerun, and the old records are kept in `results/_superseded/`.

## Files
- `results/tables.md`: every table, per category, family and component.
- `results/summary.json`: all metrics, CIs and paired differences.
- `results/per_item_<model>.csv`: per-item scores.
- `results/<model>/*.jsonl`: raw transcripts, tool calls and timings.
- `results/scores.svg`: chart.
- `manifest.json`: engine, models, sha256 and store.
- Code: `build_store.py`, `tools_impl.py`, `scenarios.py`, `questions.py`, `run_bench.py`, `score.py`, `make_tables.py`, `driver2.sh`.
