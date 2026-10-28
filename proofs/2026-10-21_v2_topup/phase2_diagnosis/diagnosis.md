# Why phase 2 (agents_v2_topup3) failed, and the phase 2c fix

Raw data in this folder:
- `decision_metrics.jsonl`, `a1_decision_metrics.md`: A1, produced by `decision_eval.py` + `diag_phase2.py`.
- `a2_learnability.json`, `a2_rows.jsonl`: A2.
- `a3_data_mix.json`: A3.
- `drift`: the squared L2 distance of each LoRA from phase 1, from `drift.py` (numbers below).

## A1: decision-level metrics
The base is nf4, as in training. The dev sets are the original dev subset (200 rows) and the Sep–Oct stage dev
sets: early (77), 1.5 h (73), 3 h (68) and other (107).

How accuracy is measured: teacher-forced. A field counts as correct when every token of its value is the argmax
given the gold prefix.
- For `pattern`, the first key, this is exactly greedy decoding. Greedy on orig gave 0.915 against teacher-forced 0.910; the difference is one row (batch padding).
- `status` is conditioned on the gold pattern.
- `likely_cause` and `event_active` come after the observations, so they are conditioned on the gold observations. They read 1.0 / ~1.0 everywhere and do not discriminate between adapters. A greedy check on orig for phase 1 gave cause 0.92 and status 0.93 (`greedy_p1_orig_partial.jsonl`).
- Greedy decoding was dropped for the sweep: 17 min per 200 rows on this laptop.

| adapter | orig loss | orig pattern | orig status | early pattern | 1.5 h pattern | 3 h pattern | early status | 1.5 h status | 3 h status |
|---|---|---|---|---|---|---|---|---|---|
| v2 (step 4494) | 0.05431 | 0.905 | 0.970 | 0.714 | 0.740 | 0.853 | 0.896 | 0.932 | 0.926 |
| phase 1 ckpt-500 | 0.05400 | 0.910 | 0.965 | 0.714 | 0.808 | 0.868 | 0.896 | 0.932 | 0.941 |
| phase 2 ckpt-25 | 0.05398 | 0.915 | 0.965 | 0.714 | 0.795 | 0.868 | 0.883 | 0.918 | 0.926 |
| phase 2 ckpt-50 | 0.05400 | **0.920** | **0.970** | **0.740** | **0.822** | 0.868 | 0.896 | 0.932 | 0.941 |
| phase 2 ckpt-100 | 0.05455 (+1.0%) | 0.905 | 0.970 | 0.701 | 0.808 | 0.897 | 0.896 | 0.932 | 0.941 |
| phase 2 ckpt-150 | 0.05604 (+3.8%) | 0.900 | 0.965 | 0.766 | 0.808 | **0.941** | 0.870 | 0.918 | 0.956 |

**Hypothesis 1 holds in part: phase 2 did improve decisions, which the whole-text loss did not show.**
- At ckpt-50:
  - Original-dev pattern accuracy went up 1 pt and status 0.5 pt, with no change in loss.
  - Early pattern went up 2.6 pt and 1.5 h pattern 1.4 pt.
  - The stage dev loss barely moved (0.0698 to 0.0698).
- At ckpt-150:
  - 3 h pattern went up 7.4 pt (0.868 to 0.941) and early pattern 5.2 pt.
  - But original-dev pattern fell 1 pt, early status fell 2.6 pt, and the original whole-text loss rose 3.8%. That is real forgetting.

Decision-token loss tells the same story. On 3 h it went 0.0606 → 0.0473; on orig it went 0.0399 → 0.0430.

**The drift explains the forgetting.** Squared L2 distance of the LoRA weights from phase 1:

| | ckpt-25 | ckpt-50 | ckpt-100 | ckpt-150 | v2 → phase 1 (500 steps) |
|---|---|---|---|---|---|
| distance | 0.048 | 0.39 | 1.66 | 2.56 | 4.83 |

At LR 2.5e-5, 100 steps of phase 2 moved the weights a third as far as all 500 steps of phase 1. The original-dev loss starts rising past about 1.5.

## A2: label learnability at early ages (d 3..9)
- **15.3%** of the targeted early event rows (45 of 295) have a gold shape that is not visible yet. "Not visible" means the post-onset part is under 3 noise units from the pre-onset median, or under 6 identical readings for a flatline.
- By pattern: step_decrease 33%, spike 32%, gradual_decrease 18%, exponential 15%, erratic 13%, dip 11%, gradual_increase 11%, step_increase 10%, flatline 0%.
- By d: d=3 31%, d=4 41%, d=5 13%, d=6 12%, d=7 21%, d=8 11%, d=9 10%.
- The pattern minimums of `generate_v2` clamp gradual/exponential/erratic to d ≥ 6, so 131 of the 295 rows sit at d = 6.
- The v1 rule detector disagrees with the gold label on most early rows (flatline/step/gradual 93–100%), so a rule reading is not a usable early-age teacher.
- Teacher consistency: among windows that look alike (same role, rule pattern, amplitude bin and d//3), only **62.8%** carry their group's majority label.
- **Conclusion: hypothesis 2 holds.** About one early row in seven asks the model for a shape it cannot see. The teacher's own rule for events below 3× noise is "stable / normal". It is not applied here because the injected size is large but the window only shows its first readings.
- **Fix:** drop those rows rather than relabel them. Relabelling them "stable" would need a teacher rule for "not visible yet" that does not exist, and I did not invent one.

## A3: data mix (`a3_data_mix.json`)
- Whole-set statistics barely moved from the original train set:
  - stable pattern 14.0% → 15.0%, normal status 55.4% → 52.9%;
  - mean completion length 276 vs 276 characters; mean prompt length 2,266 vs 2,259 characters.
- The phase-2 targeted part did differ from phase 1's targeted part:
  - stable 21% vs 12%; normal 45% vs 27%;
  - early rows (d 3–9) 24% vs 13%;
  - event_active true 56% vs 66%.
- At 20% of the mix this is a moderate shift, and it is not the main cause. The main cause is the weights drifting under a fresh optimizer at 2.5e-5 for more than 100 steps, combined with the unlearnable early rows.

## B: the phase 2c recipe (`train_topup_c.py`), and the A finding behind each choice
1. **Start from phase-1 checkpoint-500. LR 1e-5 (0.4× phase 2), 30 warmup steps, cosine, 250 steps, 90% replay.**
   - Why: forgetting tracked drift. At 0.4× the LR the expected drift after 250 steps is about the same as phase 2's ckpt-50 to ckpt-100 region, which is the good region.
2. **L2-SP anchor to phase 1: λ = 0.005 × Σ(θ − θ_phase1)².**
   - Calibration: at the drift where forgetting started (squared distance ≈ 1.5 to 2.5), the penalty is 0.008 to 0.013, which is 15–25% of the loss (~0.054). It pulls back only when the weights travel far.
3. **Decision-token weight ×4** on the values of pattern, status, likely_cause, event_active and fault_kind; ×1 on every other token.
   - Why: in A1 the gains were in decisions while the free text drifted. This puts the gradient where the stage gains came from.
4. **Drop the 45 early rows whose shape is not visible** (A2). 396 targeted rows remain, a stratified sample of phase 2's buckets.
5. **Decision-based evaluation every 50 steps**, plus step 0 (= phase 1), on the original and stage dev sets.
6. **Pass rule**, all measured against step 0:
   - Original-dev pattern, status and cause each drop by at most 0.5 pt.
   - The mean of the stage (early, 1.5 h, 3 h) × {pattern, status} changes must be > 0.
   - No stage drops more than 1 pt in either field.
   - Original whole-text loss rises by at most 3%; above that the forgetting guard stops training.
   - Among passing steps, the one with the largest stage gain is chosen.
   - Measured in this sweep: phase 2 ckpt-50 has stage pattern +2.6 / +1.4 / 0 pt and status 0 / 0 / 0 pt, so it would pass this rule. ckpt-150 fails it: early status −2.6 pt, orig pattern −1 pt, loss +3.8%.
7. **Lower-memory GGUF build for the 8 GB WSL.** `merge_lowmem.py` merges one tensor at a time and is **bit-exact** with `merge_v2.py`: compared on 5 tensors of the phase-1 merge, max abs diff 0.
