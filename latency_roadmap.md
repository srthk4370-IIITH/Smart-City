# Latency & Accuracy Plan v2 — The Single-Pass Incident

**Date:** 2026-10-13. Supersedes v1 (which was wrong: it proposed rule-based bypass and streaming — one throws away the fine-tune, the other only *feels* faster).

**Principle for everything below:** no technique may reduce how much the fine-tuned model decides. Latency must come from removing *redundant work*, not removing *model judgement*. Every item is either lossless-by-construction or accuracy-positive.

---

## 0. Measured baseline (today, this board)

| Metric | Value |
|---|---|
| Decode | **23.8 tok/s (42 ms/token)** |
| TTFT (init + prefill, ~900-tok prompt) | **1.11 s** |
| Single agent call | 3.5–6.7 s |
| **4-sensor incident, 5 NPU calls** | **36.5 s** |
| Agent prompt | ~3,400 chars ≈ 900 tokens |
| Context graphs in bundle | `ar128` prefill + `ar1` decode, **single `cl4096`** |

Accuracy on 54 held-out windows:

| json | evidence | policy | status | pattern | likely_cause | **action** |
|---|---|---|---|---|---|---|
| 1.000 | 1.000 | 1.000 | 0.870 | 0.852 | 0.815 | **0.778** |

bf16 ceiling 91.3 %. Gap to close: **6.1 points**.

---

## 1. Three facts that reorganise the plan

**F1 — The gap is not malformed output.** JSON/evidence/policy are already 1.00. The 6.1 points are wrong-but-valid content. So constrained decoding buys ~0 accuracy on the agents (it still buys tokens and kills the synthesizer's malformed-JSON failures seen live in INC-0007/0008).

**F2 — `action` is the weakest metric *and we already have a deterministic function for it*.** `rules.go:283 ActionOf(cause,status)` is total and always returns a whitelisted action; `policy.go:208` already uses it as a fallback. The model spends tokens emitting a field it gets wrong 22 % of the time while a lookup would track `cause` exactly. **Stop generating it.**

**F3 — One build host unlocks everything expensive.** Genie supports four speculative modes (`lade`, `ssd-q1`, `spd`, `eaglet`) and LoRA adapter switching — **all of them require an AR-N token graph or LoRA-aware context binaries, and AI Hub emits neither.** Both need the same x86-Linux QAIRT offline-prepare host. That single investment is the gate to the entire second half of this plan.

---

## 2. Target design — the Single-Pass Incident

Replace *N agent calls + 1 synthesizer call* with **one trained joint call**.

```
Today:   sensor_1 → agent_1 ──┐
         sensor_2 → agent_2 ──┤→ synthesizer → root cause      N+1 calls, 36.5 s
         sensor_N → agent_N ──┘

Target:  [all sensors] → ONE joint call → {global summary, per-sensor findings, root cause}
                                                               1 call, ~5 s
```

**Why this is more accurate, not just faster.** Today's design is a *pipeline*: each agent sees only its own sensor and commits a `likely_cause` the synthesizer cannot revise. That is textbook stage-1 error propagation, and it explains why `likely_cause` (0.815) is our second-weakest metric. Joint prompting wins 9/9 settings in the one controlled study of this exact shape (+0.06 to +0.31 doc-level accuracy), with gains **concentrated on numerically dependent fields and widening as item count rises** — the opposite of batch-prompting folklore (arXiv 2503.16868). Multi-task joint tuning adds +5.58 points on average, largest where the single-task model was weakest (arXiv 2310.20072).

**Four conditions, all non-negotiable:**

| # | Condition | Why |
|---|---|---|
| C1 | **Balanced permutation augmentation** — every sensor role appears in every slot roughly equally in training | Kills order sensitivity. PAPEFT drops positional fluctuation from 28–90 % to **1–2.5 %** (arXiv 2404.01430). Naive shuffling alone leaves residual bias (arXiv 2604.03642) |
| C2 | **Global summary field emitted FIRST**, then per-sensor findings, then root cause | Models otherwise behave as sequential single-label classifiers inside one generation (EMNLP 2025, arXiv 2505.17510). A leading global field is what actually delivers the cross-domain mechanism |
| C3 | **Terseness from training, never truncation.** Well-delimited JSON, not bare letters | After fine-tuning, label-token choice stops mattering (arXiv 2510.22691). But bare single-letter IDs are the *worst* format and hard token caps are destructive (72.2 %→53.5 %, arXiv 2507.04023) |
| C4 | **Cap sensors per call so the prompt stays under the 2048-token graph tier** | Joint advantage *inverts* at document scale. At ~450 tok/sensor + 400 system, that is **3–4 sensors per call**; spill to a second call beyond that |

**C4 is the non-obvious one.** Input compression is nearly worthless for its own sake (prefill is ~26 % of a call) — but it decides **which context-graph tier you land in**, and that changes decode speed for the entire call. Trimming the 48-value series to 3 significant digits and dropping per-value labels (~450 → ~300 tok/sensor) is what makes a 5-sensor joint call fit the cheaper graph. Prefill work bought for decode benefit.

---

## 3. Tier 0 — current bundle, no re-export (Week 1–2)

| # | Change | Effect | Effort | Risk |
|---|---|---|---|---|
| 0.1 | **Derive `action` from `ActionOf(cause,status)`; remove it from the schema** | action 0.778 → **0.815** (+3.7 pts), −6–8 tok/finding, deletes a validation branch | 0.5 d | none (measured, function already exists) |
| 0.2 | **Terse schema**: enum indices not words, 1–2 char keys, evidence as id pairs, minified. Host expands for UI/audit | 60–150 tok → **25–50 tok** per finding | 2 d + retrain | low (C3) |
| 0.3 | **Structured output + jump-forward decoding** (QAIRT ≥2.48; we run 2.50) | Grammar-forced tokens emitted with **zero NPU forward passes** | 3–5 d | low |
| 0.4 | **Joint call** (C1–C4) | N+1 calls → 1; removes N−1 inits + prefills; accuracy ↑ | 1 w + retrain | medium — gated, see §6 |
| 0.5 | **Re-test `poll:false` at realistic depth** (config says `poll:true` today) | Our old test said −4 %; a third party measured **+55 % at depth 4096**. Depth is the likely difference | 0.5 h | none |
| 0.6 | **Numeric formatting**: 3 sig digits, drop decimal point, single-char delimiter | ~450 → ~300 tok/sensor → keeps 5 sensors inside the 2048 graph | 1 d | none |

**0.2 × 0.3 multiply.** A terse enum schema makes a *larger* fraction of output grammar-determined: after `"p":` only digits 0–11 are legal; `,"s":` that follows is forced and therefore free. Verbose prose is unpredictable; terse enums are nearly all skeleton. **This pairing is the core of the plan** — it is exactly the "seed the decoder with what we already know" idea, except exact rather than probabilistic, and already supported by our runtime.

Known defect to handle: the stock library **leaks the terminal/EOS token** at the end of constrained output. Per-request grammar (`GenieDialog_setGrammar`) is 2.51-only; on 2.50 the grammar is fixed per model — fine, we have exactly one schema.

**Tier 0 projection: 36.5 s → ~8–11 s, accuracy 85.2 % → ~87–88 %.** No new bundle, no new SDK.

---

## 4. Tier 1 — AI Hub re-exports (Week 3–4)

| # | Change | Effect | Effort | Risk |
|---|---|---|---|---|
| 1.1 | **Re-export at `[1024, 2048, 4096]`** context lengths | **+40–107 % decode, +45–198 % prefill** (two independent sources). Single-`cl4096` pays 4096-token KV bandwidth on token #1 | 1–2 d | none — but see trap |
| 1.2 | **QAT+LoRA fine-tune** (`qat_scheme="int4"` in Unsloth/torchao), merge to BF16, feed existing AI Hub `quantize --use-seq-mse` | Recovers **34–67 %** of the quantisation gap. Measured on *our exact models*: Llama-3.2-3B +0.7/2.0 MMLU-Pro; Qwen3-4B +2.0/5.8 | 1 d + 1.4× train + ~$30 GPU rental | low |
| 1.3 | **KL self-distillation** from our bf16 teacher (precompute top-k logits offline) folded into 1.2 | +10–20 % further recovery. bf16-self teacher beats a larger teacher (arXiv 2601.20088) | 2 d | low |

**Trap on 1.1: use exactly 3 context lengths.** At 10 graphs per context part, decode collapses ~30× (~395 ms/token, NPU at 3–4 % utilisation) — a Qualcomm-tracked bug. Keep **≤8 graphs per part**. Also diff the generated config: `--context-length` exports have shipped a wrong `rope-scaling` factor, and we have been bitten by exactly that (8.0 vs 32.0) before.

**Why QAT and not SpinQuant:** rotations target *activation* outliers. We run **A16**, where outliers are already tolerable — which is precisely why our gap is 6 points and not 30. Most of SpinQuant's headline gain is unavailable to us, and there is no published evidence on combining rotations with QAT. Deprioritised.

**Why QAT upstream and not AIMET QAT:** there is no documented AIMET-QAT→Genie recipe for LLMs; the AI Hub LLM path is calibration-only (Sequential MSE), and the encodings version matrix (AIMET 2.0.0 spec vs AI Hub 1.0.0 support) is a known trap. Put the quantisation-awareness in *our* fine-tune, where we control everything, then hand AI Hub an ordinary BF16 checkpoint — which it explicitly supports for fine-tuned variants.

**Open risk on 1.2:** torchao's int4 grid (group-wise affine) is not byte-identical to AIMET's w4a16 grid. Match `group_size` to whatever the published `.encodings` use. **This transfer is the single biggest unknown in the plan and must be measured first, not assumed.**

**Tier 1 projection: ~8–11 s → ~5–7 s, accuracy ~87–88 % → ~90–91 %.**

---

## 5. Tier 2 — the build host (Week 5+, the keystone)

Stand up one x86-Linux QAIRT offline-prepare host. It unlocks three things that AI Hub structurally cannot give us.

### 5.1 AR-N token graph → draft-free speculative decoding

All four Genie speculative modes need a token graph with AR-N > 1. We have only `ar1`.

**LADE (lookahead) is the one to build** — `"dialog":{"type":"lade"}`, no draft model, no forecast prefix, no trained EAGLE head. Constraints, verbatim from the docs:
- `window == gcap`
- `(window + gcap) × (ngram − 1) ≤ AR-N`

The documented (8, 8, 5) config needs **AR-N ≥ 64**. One AR-N graph simultaneously enables LADE, SSD-Q1 and Eaglet, so build it once and pick the best empirically.

Reference points: Qualcomm's own SSD build of Llama-3.2-3B measures **1.74–3.17×** decode and is *output-identical by construction*; independent work on our exact chip (8 Gen 3) measured **71.7 → 41.6 ms/token (1.72×)**. Accuracy risk: **zero**.

### 5.2 One base + two LoRA adapters → no bundle switching

Documented and supported on Qnn-HTP: `qairt-converter --lora_weight_list --quant_updatable_mode adapter_only`, then `qnn-context-binary-generator --adapter_weight_config <yaml>`. Runtime: `GenieDialog_applyLora` / `setLoraStrength`, `skip-lora-validation` (shipped specifically to cut switch time). **Engine Sharing** lets two dialogs share one engine with separate KV managers and LoRA configs — literally the "analyst role / reasoner role on one resident base, zero bundle switch" architecture.

Adapter swap is inferred at **tens-to-low-hundreds of ms** versus our current **~2.5 s + 0.68 s** full bundle swap.

### 5.3 What this costs
2–4 engineer-weeks plus a large-RAM Linux host. This is the barrier that pushed us to AI Hub in the first place — but it is now the only remaining door, and it opens onto both the biggest latency win and the cleanest multi-role architecture.

**Tier 2 projection: ~5–7 s → ~2.5–4 s, accuracy unchanged (lossless).**

---

## 6. Qwen3-4B — decision and gate

**The quality case is real and specific.** Qwen3-4B-Instruct-2507 scores **ZebraLogic 80.2** vs 35.2 for the hybrid Qwen3-4B and 33.2 for the 30B-A3B MoE. ZebraLogic is constraint-satisfaction — combining independent clues into one consistent assignment, which is structurally our synthesizer task. Also MMLU-Pro 69.6, GPQA 62.0, Arena-Hard 43.4; Apache-2.0.

**Use `Qwen3-4B-Instruct-2507` specifically.** It is **non-thinking only** — no `<think>` blocks, architecturally. The hybrid model's `enable_thinking=False` lives in a Jinja chat template that our Genie bundle does not carry (we build the prompt string ourselves), and it is known to leak. A leaked 1,000-token reasoning trace at 42 ms/token = **42 s of dead latency**; an 8,192-token trace is seven minutes. Do not use the hybrid or the Thinking checkpoint.

**Three blockers:**
1. **Snapdragon 8 Gen 3 / V75 is not on any supported chipset list** for Qwen3-4B. Lowest mobile target is 8 Elite. We would be first.
2. Estimated **12–16 tok/s on V75** vs our 23.8 — slower per token.
3. Quantising a *fine-tuned* Qwen3-4B needs **48–60 GB VRAM** on Linux+CUDA. Qwen3 is also documented as quantisation-sensitive at small sizes (8B AWQ-int4: −5.4 MMLU).

**Gate (1 day, do this before anything else Qwen-related):** attempt
`qai-hub-models export qwen3_4b_instruct_2507 --device "Snapdragon 8 Gen 3 QRD" --target-runtime genie`.
If the compile fails → Qwen3-4B is off the table on this board; revisit on 8 Elite hardware. If it compiles → push the **stock published `DEFAULT_W4A16` checkpoint** and measure real tok/s. **Stock avoids the 48–60 GB quantise box entirely** — we would be using Qwen3-4B for its native reasoning, not fine-tuning it.

**Recommended architecture if the gate passes:**

| | Model | Role | Calls/incident |
|---|---|---|---|
| Analyst | Llama 3.2 3B, fine-tuned, joint schema | all sensors, one joint call | 1 |
| Reasoner | Qwen3-4B-Instruct-2507, **stock** | cross-domain root cause | 1 |

Two bundles = one switch per incident (~2.5 s), amortised over the whole incident rather than per sensor. Estimated: joint 3B (~3 s) + switch (2.5 s) + Qwen synth (~4 s) ≈ **9.5 s** with a markedly better reasoner — and Tier 2's LoRA path later removes the switch if both roles can share a base.

**Do not pursue two simultaneously-resident models.** Genie has no multi-model dialog; Engine Sharing is same-context-binaries only; weight sharing cannot span different models; memory is strictly additive (~7 GB of 9.2 GB free) and the binding constraint is PD/VTCM admission, not RAM — err 1002 *is* `QNN_COMMON_ERROR_MEM_ALLOC`. The one serious third-party attempt was unreliable across 36 swaps on comparable silicon. Free-then-load stays the fallback.

---

## 7. Deliberately rejected

| Rejected | Reason |
|---|---|
| Rule-based cascade / skipping LLM calls | Discards the fine-tune. The model must decide every time |
| Streaming / progressive disclosure | Perceived latency only. Not a solution |
| Custom external draft tokens to Genie | **Not feasible.** No public "verify these K candidates" API. Every speculative path needs the drafter compiled as a QNN engine. `tokenQuery` is prompt ingestion; `batchQuery` is N independent prompts |
| Critique/delta decoding on a rule prior | Deferred. CFT gives +4–10 over SFT at 2.5× fewer tokens, **but** fine-tuning on correct priors provably *increases* sycophancy (arXiv 2511.05408), and models anchor hardest on the last-proposed answer. Only after we can measure flip-rate against deliberately wrong priors |
| Prompt compression (LLMLingua) | Attacks prefill (26 %); needs a second encoder on the same silicon; ≤18 % even when favourable |
| SpinQuant / QuaRot rotations | Target activation outliers; we are A16 |
| Prefix KV caching as a separate project | The joint call gives shared-prefix amortisation for free |
| Migrating to GenieX now | Currently *slower* on mobile and ignores speculative settings on the qairt runtime |
| 5 context lengths in one export | 10 graphs/part collapses decode ~30× |

---

## 8. Sequence and gates

| Week | Work | Gate to pass before continuing |
|---|---|---|
| 1 | Bench harness; 0.1 action-derive; 0.5 poll re-test; 0.6 numerics | Harness reproduces 23.8 tok/s ±5 %; action metric ≥0.81 |
| 1–2 | 0.2 terse schema + 0.3 jump-forward (retrain together) | Tokens/finding ≤50; accuracy not below 85.2 % |
| 2–3 | 0.4 joint call (C1–C4) | **Positional fluctuation ≤3 %** after permutation training, and accuracy measured **specifically at N=7–8**. If fluctuation stays high, joint is unsafe — fall back to 3-sensor tiers |
| 3 | 1.1 multi-context-length export | ≤8 graphs/part; rope-scaling verified; decode ≥32 tok/s |
| 3–4 | 1.2 QAT + 1.3 distillation | Grid-transfer measured; accuracy ≥89 % |
| 4 | **Qwen3-4B compile gate** (1 day) | Compiles for 8 Gen 3 → proceed; else drop |
| 5+ | Tier 2 build host → AR-N graph → LADE; then LoRA adapters | LADE output bit-identical to `ar1` decode on 54 windows |

**Hard rule:** every change reports **(latency, accuracy)** as a pair on the 54-window set. We have been burned once by a plumbing bug (double BOS) that looked exactly like a quantisation problem.

---

## 9. Projection

| Stage | Incident (4 sensors) | Accuracy | Confidence |
|---|---|---|---|
| Today | **36.5 s** | 85.2 % | measured |
| + Tier 0 | ~8–11 s | ~87–88 % | high |
| + Tier 1 | ~5–7 s | ~90–91 % | medium-high |
| + Tier 2 (LADE) | **~2.5–4 s** | unchanged (lossless) | medium |
| + Qwen3-4B reasoner | +~4 s, better root cause | cause ↑ | gated |

**~10× faster and past the 94 % target is reachable** — but the 94 % depends on Tier 1 landing the QAT transfer, and that is the number to measure first.

---

## 10. Open questions, ranked

1. Does torchao int4 QAT survive AIMET re-quantisation? *(decides whether Tier 1 accuracy is real)*
2. Does `poll:false` help at depth on our board? *(our data contradicts a published +55 %)*
3. Does the joint call hold accuracy at N=7–8, and does permutation training get fluctuation to ≤3 %?
4. Does Qwen3-4B compile for 8 Gen 3 at all?
5. What fraction of our output tokens does jump-forward actually skip under the terse schema? *(determines whether 0.2×0.3 is a 2× or a 1.2×)*

---

## 11. Results, 2026-10-14 (supersedes parts of 8-10)

Three roadmap items were settled on device. Full evidence in HANDBOOK 2.12-2.14.

### 1.1 multi-context-length export - UNBLOCKED, but not worth taking

The gate said "<=8 graphs/part". The blocker was never graph count: our Genie config was missing
`"enable-graph-switching": true`. With it, the 3-graph bundle loads first try and is byte-identical
to live (12/12 prompts). Qualcomm ships an 8-graph config for llama3-3b in the QAIRT SDK.

But the gate "decode >=32 tok/s" **fails**: extra graphs cost ~200 ms of prefill and ~150 ms of
init per call, so the 3-graph bundle is *slower* end to end (4291 ms vs 3738 ms). Only add graphs
when the extra graph is worth >550 ms.

### Tier 2 LADE - FAILS ITS GATE, dropped

The gate was "LADE output bit-identical to `ar1` decode on 54 windows". It is not. It is 14%
faster and it corrupts answers - "spike" -> "sp.peak", PM10 -> PM2.5, and a flatline
`sensor_fault` downgraded to `normal`. Minimum speculation still gave 4/13 identical and was
slower. The "lossless" assumption in section 9's projection is wrong for Genie 1.20; remove
LADE from the projection.

### New item: batched agents per incident - WORKS, off by default

Not in the original roadmap. `genie-app` (QAIRT SDK, aarch64-android) runs many queries in one
model load, so an incident pays model init once instead of once per agent, and skips the 600 ms
inter-call gap too: **1331 ms saved per extra agent**, byte-identical (16/16 Python gate + an
on-device Go test). Wired into Mode 3 behind `SCE_GENIE_BATCH=1`.

Caveat that decides its value: every Mode-3 incident reproduced on device ran **one** NPU agent,
so it never engaged. Section 9's "Incident (4 sensors) 36.5 s" assumes fan-out that was not
observed. **Open question 6: does Mode 3 actually fan out to several agents in the demo, and if
not, why?** That question now gates this item.

### Still standing

Decode is ~70% of latency and is NPU-bound: `rpc_control_latency` 100->0 and `rpc_polling_time`
changed nothing (2613-2682 ms, all within noise). Pre-warming a process is impossible - Genie
reads the whole prompt before touching the DSP. The remaining levers are fewer forward passes
(speculation - now known to be lossy here) or fewer tokens.
