# Why the v2 top-ups do not beat v2, and what to do instead (2026-10-23)

Laptop CPU only, no GPU, no adb. The numbers come from `analyze_topup.py`, with output in `analysis.json`. That script reads the existing
board and host evaluations: `2026-10-23_app_ab_v2_vs_3d/*/host400`, `2026-10-23_3d_quant_fix/post_diag/eval`, and the test gold in
`data/sft_v2/test.jsonl`. The papers are cited from memory. I ran no new web searches, because the owner asked to save tokens.

## For the 3e model agent

1. **Do not continue v2 with another small SFT top-up.** 3d at step 50 had seen about 800 rows, of which only ~80 were targeted, and it was still in LR warm-up.
   - Its median weight change was 0.13%.
   - It changed only 2.5% of decisions (5 of 208 rows). On host400 it scored 2 wins and 4 losses (p = 0.69).
   - Its dev "gains" were 2–3 rows on dev slices of 68–77 rows, where the 95% CI is ±9–10 pt. That is noise.
2. **Pattern is the lever.** On host400:
   - When the pattern is right, status is 93% correct and cause 97%.
   - When the pattern is wrong, status falls to 41% and cause to 18%.
   - 64% of the pattern errors are on held-out (unseen) sensors, which make up 42% of the rows.
   - Status errors made with the right pattern are mostly missed alarms (warning→normal 8, critical→normal 5).
3. **Recipe: on-policy preference fine-tuning on v2's own mistakes** (DPO with an NLL term, i.e. RPO). Details are in §3.
   - **Mine.** Generate a fresh pool of 20–30k Jan–Aug windows with `generate_v2` and `teacher_v2`, including node augmentation (§3.1). Run v2 teacher-forced on the pattern; that is exactly greedy, because the pattern is the first decision after the prefill.
   - **Pairs.** Chosen = the gold completion. Rejected = v2's own greedy completion, generated only for the rows it gets wrong.
   - **Drop unreliable rows:** gold not visible yet (A2 rule) and boundary sizes (2.5–4.5× noise).
   - **Train.** TRL `DPOTrainer` on the v2 adapter (nf4 base), `beta=0.1`, `rpo_alpha=1.0`, `precompute_ref_log_probs=True` (reference = v2; no second model on 6 GB), LR 5e-6, cosine, warm-up 10%, 1 epoch over ~2–3k pairs plus 1:1 gold replay (SFT on correct rows), batch 1 × accumulation 16, max_len 1280.
4. **Gate on enough rows.** Use teacher-forced pattern accuracy, which equals greedy and is the same at Q4_0 and Q8_0.
   - Data: the full original dev (1,947 rows), the Sep–Oct stage dev (325), and a **node-held-out dev**: 20% of the train nodes, kept out of mining.
   - Require a paired McNemar test with p < 0.05 on the combined set, and no slice down by more than 1 pt.
   - Then run the host GGUF greedy on host400, paired against v2. Use board time only if it wins.
   - A net +2 pt needs about 600–1,200 rows to show (§1c), so a gate on 68-row slices cannot work.
5. **Fallback if (3) fails the gate:** train a **fresh** r=32 adapter from the base on v2 data plus the augmented and targeted data. Do not continue v2. This takes 1 epoch, about 25 h of GPU time. Details in §3.2.

## 1. Diagnosis

### (a) Teacher-forced scores vs greedy decoding: partly exposure bias, but the real issue is that the gate measured the wrong thing
- **Pattern is the first key after the `{"pattern": "` prefill**, so teacher-forced pattern equals greedy pattern. The measured gap is one row (0.915 vs 0.910).
- **Teacher-forced status and cause were inflated.**
  - Status was scored given the gold pattern. Cause was scored given the gold observations, which gave 1.000 everywhere, so the gate could not see cause at all.
  - Greedy decoding on the same original dev for phase 1 gave status .93 (teacher-forced .965) and cause .92 (teacher-forced 1.0).
- **Error chain under greedy decoding** (host400 board v2, n = 399):

| field | given own pattern right | given own pattern wrong |
|---|---|---|
| status correct | 0.931 | 0.408 |
| cause correct (given pattern and status right) | 0.966 | 0.184 (given pattern wrong) |

  - All three fields are right on 0.789 of the rows. The 208-row weak set shows the same chain: 0.907 / 0.269.
  - So status and cause errors mostly follow a wrong pattern. That is not classic exposure bias in the free text: the observations barely matter, given a right pattern.
  - Implication: optimise pattern under the model's own distribution, and score status and cause on the model's own prefix, never on gold.

### (b) Label noise and teacher consistency
- `teacher_v2` is a deterministic rule teacher: every label is a function of the evidence. "62.8% majority agreement" came from coarse groups (role, rule pattern, size bin, d//3), so it measures the grouping as much as the labels.
- Real noise does exist in two places:
  - **Unseen early shapes:** 15.3% of early rows (A2).
  - **The 3× noise boundary,** where the label depends on the injected size, which the model can only estimate.
- Pattern error rate by injected size on host400:

| size (× noise) | error rate | errors |
|---|---|---|
| < 3 | 20% | 6/30 |
| 3–4.5 | 26% | 9/35 |
| 4.5–8 | 16% | 15/94 |
| ≥ 8 | 6% | 5/85 |

  - The boundary rows are near the label ceiling and should not be trained harder.
- Top confusions are boundary or shape-adjacent: dip→stable 4, gradual↔step increase 5, step_decrease→stable 2, erratic→dip 3.

### (c) Evaluation noise: no top-up "improvement" was ever significant

| set | n | 95% CI half-width |
|---|---|---|
| stage dev | 68–77 | ±8.5–10 pt |
| weak set | 208 | ±4.5 pt |
| host400 | 400 | ±3.2 pt |

- Paired results:
  - 3d vs v2 on host400 (board, valid rows): pattern 2/4 (p = .69), status 4/5, cause 8/3 (p = .23).
  - 3d vs v2 on the 208-row set (Q8): 2/3, 4/3, 4/5.
- Rows needed to detect a net gain δ at 80% power, given the discordance rate pd between the two models:

| | pd = 0.03 | pd = 0.06 | pd = 0.10 |
|---|---|---|---|
| δ = 2 pt | 588 | 1,176 | 1,960 |
| δ = 3 pt | 262 | 523 | 872 |

- The phase 1 board rejection (.877 → .855) also fits inside this noise plus the batch-garbage artefact (HANDBOOK 2.45).

### (d) Data distribution
- **The main gap is generalisation to held-out sensors.** On host400, pattern errors are:

| sensors | errors | error rate |
|---|---|---|
| seen | 18/232 | 8% |
| unseen | 26/145 | 18% |
| unseen, Sep–Oct | 6/23 | 26% |

- Water on unseen nodes scores 52% pattern; power on unseen nodes scores 48% status.
- All top-up targeted rows came from train nodes (Jan–Aug), so they could not address this.
- The 3d mix was 396 targeted rows inside 4,000, against an eval made mostly of weak slices and unseen nodes.

### (e) Anchor and LR
- **Phase 2:** LR 2.5e-5 drifted (squared L2 distance 1.66 at 100 steps) and forgot.
- **3d:** LR 1e-5, an L2 anchor of 0.005, and a gate that picked step 50 (still in warm-up) gave an almost unchanged model.
- **The real problem:** weight-space L2 constrains every direction equally, and the gate together with the tiny dose meant the only passing step was the near-v2 one.
- **What would work better:** a KL- or reference-anchored objective, such as DPO's β. It stays close to v2 on everything except the decisions being corrected.

### (f) Capacity of 3B
- No sign that capacity is the limit:
  - train loss ≈ dev loss;
  - seen-node pattern accuracy is 92%, and HVAC and occupancy score 97–100%;
  - Q4_0 = Q8_0.
- The errors are concentrated in generalisation and boundary cases.

### (g) Train/serve skew
- None found:
  - the host tokenisation equals htpd's (checked at each run);
  - the prompt is the same string, with `add_special_tokens=False` in training;
  - the `{"pattern": "` prefill and stop at `"action"` match the completion order;
  - host and board give the same decisions on 207/208 rows;
  - the merge is bit-exact.

## 2. Alternatives considered

| option | fits the problem? | verdict |
|---|---|---|
| More SFT top-up continuing v2, with anchor or decision weights | Same objective as v2, so no new signal on the model's own errors; small doses = no change, big = forgetting | stop |
| **DPO / RPO / ORPO on v2's own wrong greedy outputs** (Rafailov 2023 DPO; Pang 2024 *Iterative Reasoning Preference Optimization* = DPO+NLL; Hong 2024 ORPO) | Optimises exactly the greedy decision. Rewards are exact (deterministic teacher). The reference KL is the right anchor. Fits 6 GB with precomputed reference log-probs | **recommend #1** |
| KTO (Ethayarajh 2024) | Works with unpaired good/bad labels; handy if generating rejected texts is too slow | backup to DPO |
| RFT / STaR (Yuan 2023; Zelikman 2022): SFT on the model's own correct samples | Gives little here: the pattern is near-deterministic under greedy decoding, and the samples add no new pattern knowledge. It does not push down the wrong mode | low |
| GRPO with a rule reward (Shao 2024, DeepSeekMath) | Correct in principle, but needs groups of 4–8 generations per prompt: too slow on an RTX 4050 at ~1k-token prompts. For a first-token class it reduces to what DPO does more cheaply | later, if DPO plateaus |
| Fresh adapter on the full augmented data | Avoids the continued-training dynamics. The only option that properly adds node diversity at scale | **#2 / fallback**, ~25 h |
| Reorder the JSON (decision fields first) | Already true: pattern comes first, status second | n/a |
| Constrained or label-log-prob pattern selection (`HTPD_PATTERN_TRIE`) | The pattern is already chosen by argmax over the first token; a full-label log-prob changes little. A trie removes invalid labels only (JSON is already 99.8–100%) | small, free; keep the trie |
| Self-consistency (Wang 2023) at the refine stages | The majority of samples ≈ greedy for a first-token class; costs N× NPU time | no |
| Relabel with a stronger LLM teacher or consensus | The labels are rule-exact by design; noise sits only at the boundary and in unseen early shapes. Better: **filter** those rows, not relabel | filter only |
| Per-stage LoRAs | Multiple adapters on the NPU = new htpd work and memory; stages share one shape vocabulary | no |
| Distillation from a 70B model through an API | Would replace rule-exact labels with noisier ones; privacy approval needed | no |
| Ensemble with rules | The rule detector disagrees with the gold label on 40–100% of early rows (A2); rules are reliable only for limit-based status (critical/warning on limit crossings). Possible: a backend post-check that a limit-crossing window is never "normal". This targets the 13 missed-alarm status errors | cheap backend option, separate from training |

Background:
- Exposure bias: Bengio 2015 (scheduled sampling); Ranzato 2016.
- LoRA forgets less but also learns less in continued training: Biderman 2024.
- L2-SP: Li 2018.

## 3. Recommended recipes

### 3.1 #1: on-policy DPO+NLL (RPO) from v2, about one night
1. **Pool.** 20–30k fresh rows from `generate_v2`/`teacher_v2` on Jan–Aug.
   - Oversample the weak families: power and water, compound, 1.5 h and 3 h, plus missed-alarm cases where the status crosses a limit.
   - **Node augmentation for the unseen-sensor gap:** per row, apply a random gain (0.7–1.4), offset, noise scale (0.7–1.5×) and diurnal phase shift, and recompute the evidence. The teacher labels after augmentation, so the labels stay exact.
   - Hold out 20% of the train nodes entirely as the node-held-out dev.
2. **Mine.** One teacher-forced forward pass per row with v2 (nf4 + adapter), taking the argmax of the pattern; this equals greedy.
   - About 0.3–0.5 s per row, so 2–3 h.
   - Expect ~10–12% errors, i.e. 2–3k rows.
   - For rows with the right pattern, also check status teacher-forced on v2's own pattern (which is now gold, so exact).
3. **Filter.** Drop rows where the gold shape is not visible (the A2 test), rows with size in 2.5–4.5× noise, and gold `small=True`.
4. **Rejected texts.** v2 greedy generation (HF, max_new 160, stop at `"action"`) for the kept error rows only: ~2–3k × ~5 s = 3–4 h.
   - Cheaper variant: KTO with the gold rows as "desirable" and the generated wrong ones as "undesirable".
5. **Train** with TRL DPOTrainer:
   - `loss_type="sigmoid"`, `beta=0.1`, `rpo_alpha=1.0`, `precompute_ref_log_probs=True`;
   - LR 5e-6, 1 epoch, accumulation 16, max_len 1280;
   - plus an equal number of correctly answered gold rows as SFT replay;
   - save every 50 steps.
6. **Gate** (teacher-forced pattern, plus status on the model's own pattern), against v2:
   - Sets: original dev (1,947), Sep–Oct stage dev (325) and the node-held-out dev.
   - Pass: paired McNemar p < 0.05 overall, no slice below v2 by more than 1 pt, and JSON validity unchanged.
   - Then merge (`merge_lowmem.py`), build Q4_0 and run host GGUF greedy on host400, paired against v2. Spend board time only if it wins.
7. **Expected effect:**
   - Recover 20–35% of v2's non-boundary pattern errors: about +2–4 pt pattern, and through the error chain about +2–3 pt on all three fields.
   - Low forgetting risk, because the KL is to v2.
   - Cost: about 8–10 h of GPU in total. Inference latency is unchanged (same model size and format).

### 3.2 #2 (fallback): a fresh adapter on the augmented data
- r=32 QLoRA from base Llama-3.2-3B.
- Data: v2's 36k rows, plus ~8k node-augmented rows, plus the 3d targeted buckets scaled to ~3k, with unreliable rows removed.
- Settings: 1 epoch, LR 2e-4 cosine (as v2), ~25 h.
- Gate as in §3.1.
- Then optionally apply #1 on top of it (SFT then DPO, the standard order).

## Files
- `analyze_topup.py`: the diagnosis script; reads only existing proofs and the test gold.
- `analysis.json`: its output, with every number in §1.
