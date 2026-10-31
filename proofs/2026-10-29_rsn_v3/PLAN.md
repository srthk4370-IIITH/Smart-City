# rsn_v3: correct, reasoning chat + more accurate reasoner, lower latency (plan, 2026-10-29)

Owner decisions (2026-10-29): adaptive chat thinking; training answers by verified self-distillation (offline);
report accuracy must go **up** (longer/bigger training preferred over a quick one); Hexagon SDK will be
downloaded for the lossless swap speed-up.

## Why the chat answers were wrong (board chats.json, 2026-10-29)
- The rsn_v1 chat data is code-templated: 15 question kinds, 869 distinct questions, 1-3 answer templates
  (pipeline/gen_chat.py). No `<think>` in any target (train_rsn.py renders enable_thinking=False).
- So the model maps every question onto those 15 shapes: "highest spike" → latest incident; "what if occupancy
  +50%" → fog search (offline) → refusal; "which domains have open incidents" → one count of 95; "how are CO2
  levels" → incident count; "which sensors look faulty" → live status only (0) although KH03-03 had 43 sensor-fault
  incidents this week.
- The tools cannot express ranking, current levels, recent incidents or what-ifs at all.

## Method (research basis)
- **Verified self-distillation / rejection-sampling fine-tuning** (STaR, Zelikman et al. 2022; RFT, Yuan et al.
  2023; verified tool-call pipelines such as APIGen, Liu et al. 2024): the base Qwen3.5-4B with thinking on
  writes reasoning + answers for synthetic questions whose gold tool calls and results are known; only outputs
  whose tool calls, numbers and ids match the gold are kept. Variety comes from sampling (temperature) +
  paraphrased questions, correctness from the verifier.
- **Adaptive thinking** (budget-controlled reasoning, e.g. s1 budget forcing, Muennighoff et al. 2025; learning
  when to think, e.g. AdaptThink / Thinkless 2025): targets carry a short `<think>` (≤ ~80 tokens) only for hard
  kinds (what-if, why, compare, plan, multi-step); lookups keep the empty think block. htpd caps thinking tokens
  at runtime as a safety net.
- **Report accuracy up**: more and harder incident data aimed at rsn_v1's measured errors (RWH severity 91.9%,
  label 87.8%, check recall 0.90), more epochs, rank 32 (SPEC D5) instead of the r16 actually used; every
  candidate gated on RWH + dev + chat dev on the host GPU (host Q4_0 = board) before any board run.
- **Shorter report text only if free**: a variant with tighter field limits is trained/evaluated alongside;
  kept only if RWH severity/label/check recall ≥ the full-length variant.

## Steps
1. **Tools (backend + training spec):** add rank_readings, current_levels, recent_incidents, open_incidents
   (per domain, operator-pending vs AI-open), faulty_sensors (live status + AI sensor-fault diagnoses), what_if
   (data-fitted couplings from 7 days of device history: occupancy → CO2, room temp, AC, power). Same shapes in
   the synthetic training store and on the device.
2. **Router now (no retrain):** deterministic answers for those intents on the board until rsn_v3 lands.
3. **Data v3 (laptop):** ~40 chat kinds incl. multi-turn follow-ups, ellipsis ("and yesterday?"), refusals,
   what-ifs, comparisons; gold tool calls + results from the synthetic store; question paraphrases.
4. **Self-distill (Kaggle):** base model, thinking on for hard kinds, N samples per question, verifier keeps the
   correct ones; varied phrasing comes from the samples.
5. **Train rsn_v3 (Kaggle, T4×2, resumable 11 h sessions):** incidents (more + border + error-targeted) + chat v3.
6. **Gate (host GPU):** RWH 150, dev 300, chat dev v3, P0; must beat rsn_v1 on report metrics and chat.
7. **Board:** lab A/B window, then deploy with rollback snapshot.
8. **Swap speed-up:** rebuild libggml-hexagon.so with a parallel weight repack (needs Hexagon SDK headers);
   lossless (bit-identical tensors); lab A/B.
