# 3f research: keeping c49's wins without its status losses (2026-10-23)

Scope: improve v2 by continuing from v2 only (no fresh retrain). Accuracy first. Every candidate is scored on host
Q4_0 GGUFs built exactly like v2 (`post_3f.sh` = `post_3e.sh` with a weight-mix merge), CUDA llama-server b11815.

## 1. What c49 actually changed (per-row diff, `diff_rows.py v2cuda run2c49`, 1,148-row 3e set)

- Status losses (25) are almost all **over-alarms on power**:
  - routine power step_increase / step_decrease, gold `normal`: c49 says `critical`/`warning` (6 of 48 routine rows);
  - power gradual_increase (gold `warning`) read as exponential_increase -> `critical` (4 rows);
  - stable power read as exponential -> `critical` (1 row).
- c49's status training pairs were dominated by "gold alarm, v2 said normal": warning->normal 40, critical->normal 10,
  sensor_fault->normal 13 (against normal->warning 27, normal->critical 7). The pattern pairs were dominated by
  exponential_increase->gradual_increase (19).
- So the losses are exactly the labels that c49's pairs **rejected** (`normal`, `gradual_increase`), and the mass
  went to their neighbours (`critical`/`warning`, `exponential_increase`), on rows where the rejected label was correct.

## 2. Findings from the literature (with how each maps onto this problem)

| source | finding | use here |
|---|---|---|
| Razin et al., *Unintentional Unalignment: Likelihood Displacement in DPO*, ICLR 2025 ([arXiv 2410.08847](https://arxiv.org/abs/2410.08847)) | DPO can lower the probability of the chosen answer and move mass to other, unintended outputs. Pairs whose chosen and rejected answers have very similar hidden embeddings (high CHES) drive it. Filtering those pairs fixes it. In their example, Llama-3-8B refusals fell from 74.4% to 33.4% | The 3e pairs are single-token swaps of a status/pattern value, which is the most-similar case possible. This explains the routine over-alarms. Fix: (a) balance which value gets rejected; (b) add **status-preserving pairs** on rows v2 already gets right, which push down the alarm tokens the displacement inflates; (c) keep the NLL term (RPO) |
| Pang et al. 2024, *Iterative Reasoning Preference Optimization* (DPO + NLL) | The NLL term on the chosen answer keeps chosen likelihood up | Already used (rpo_alpha 1). Kept |
| Wortsman et al., *Robust fine-tuning of zero-shot models* (WiSE-FT), CVPR 2022 ([arXiv 2109.01903](https://arxiv.org/abs/2109.01903)) | Linear interpolation (1-α)θ0 + αθ1 between the pre- and post-fine-tuning weights recovers robustness at little or no target cost, with no extra training | Idea 1: v2 + α(c49 - v2). With LoRA continued from v2, the interpolation is done in **delta space**: W0 + s[(1-α)B_v2A_v2 + αB_c49A_c49] (`merge_mix.py`). Interpolating A and B separately would not be linear in the weights |
| Lin et al., *Mitigating the Alignment Tax of RLHF* (EMNLP 2024, [arXiv 2309.06256](https://arxiv.org/abs/2309.06256)) | Model averaging of pre- and post-RLHF weights gives the best alignment/forgetting Pareto front; per-layer ratios (HMA) do better still | Same as WiSE-FT; per-layer α is a follow-up only if a global α works |
| Wortsman et al., *Model soups*, ICML 2022 ([PMLR v162](https://proceedings.mlr.press/v162/wortsman22a.html)) | Averaging fine-tuned weights often beats the best single model, with no inference cost | Idea 1b: uniform soup of c30, c45 and c49 (same trajectory, so a weak form of soup) |
| Zheng et al., *Model Extrapolation Expedites Alignment* (ExPO, ACL 2025, [arXiv 2404.16792](https://arxiv.org/abs/2404.16792)) | Extrapolating past the DPO model (α > 1) amplifies what was learned | Not tried first: c49 learned the unwanted shift together with the wanted one, so α > 1 would amplify both. Only worth trying after the displacement is fixed |
| Northcutt et al., *Confident Learning*, JAIR 2021 ([arXiv 1911.00068](https://arxiv.org/abs/1911.00068)) | Find label errors from model/label disagreement and drop the likeliest ones | Idea 3. The teacher is deterministic, so "noise" is boundary ambiguity, not random flips. 3e run2 already drops 2.5–6× noise sizes, event-vs-stable pairs and flatline-vs-decrease pairs. The anchors only use rows that v2 answers fully right (which agree with the teacher). No new label rules were added |
| Iwana & Uchida, *An empirical survey of data augmentation for time series classification*, PLOS ONE 2021 ([arXiv 2007.15951](https://arxiv.org/abs/2007.15951)); Um et al., ICMI 2017 (magnitude warping, jitter; cited from memory) | Magnitude scaling, jitter and warping help generalisation to new sensors/subjects | Idea 4 (unseen sensors, 64% of pattern errors). Here the status label depends on the **node limits** (limit crossings). A rescale or offset must therefore transform the limits too, and the teacher must relabel. That is a `generate_v2`/`teacher_v2` change plus a new mined pool: not a short continued top-up. It is deferred, with the reasoning recorded here (see §4) |

## 3. Gate noise (idea 5)
- The 1,148-row 3e set is kept untouched for the final decision. Selection uses a new paired **dev3f** set of 2,010 rows
  (`gen_dev3f.py`), disjoint from the 1,148 rows and from everything 3e trained on:
  - 1,000 unused rows of the v2 test split, not in host400 (same months and nodes as host400);
  - 719 weakness rows from the gen_3e buckets, with a new seed (4496), test months, held-out nodes included;
  - 291 real-world rows from the gen_3e REALWORLD buckets, with the new seed.
- Prompts are de-duplicated against v2 train/dev/test and every 3e file.
- With about 3,160 paired rows in total (dev + test), a net change of about 1.5–2 points becomes detectable at
  discordance rates of 3–6% (TOPUP_WHY §1c).

## 4. Ideas and what was run
See RESULTS.md for numbers.

1. **Interpolation (no training):** mixA30, mixA50 and mixA70 (= v2 + α(c49 − v2)), and soup3 (c30/c45/c49).
2. **Targeted repair against displacement:**
   - **rep:** c49 plus status-preserving anchor pairs, with gold replay (reference = c49);
   - **r3:** v2 plus the run2 data plus anchors (reference = v2).
   - Anchors: v2-correct train-month rows, not mdev and not already in run2. Mostly gold `normal`
     (routine/calm/event-shaped normal; power and water first), plus some warning/critical rows.
   - Chosen = gold. Rejected = the most likely wrong status under the starting model (`anchor_3f.py`).
3. **Label noise:** covered by the run2 filters (above), with no new rules.
4. **Augmentation:** deferred (needs limit-consistent relabelling in the generator; see the table above).
5. **Bigger paired dev set:** dev3f (§3).

## 5. REALWORLD §5 cases (owner requirement, added mid-run)
- **Generator:** `topup3f/gen_rw5.py`. It covers the §5 cases 3e did not: 5.1 gaps (calm hard negatives plus
  events), 5.2 single glitch/sentinel, 5.6 CO2 below the floor, 5.7 holiday/weekend low load (plus HVAC
  stuck_on / weekend_off), 5.9 recovery after a 2–6 h gap, 5.11 chattering at the limit (adjacent-window pairs),
  and 5.12 daily-cycle rise. 5.8 is skipped (reasoner-level).
- **Labels:**
  - The existing teacher is used wherever it already applies.
  - Section-5 labels are applied by `relabel()`, one documented call per case. Interpretations:
    - **5.2 0/rail:** the schema only allows `fault_kind` with `sensor_fault`, so these are
      `sensor_fault`/`dropout`/`check_sensor`, as in the v2 dropout rule.
    - **5.2 value-glitch size:** 15–30σ, above v2's 3–12σ event spikes, so the new "single point = normal" label
      never contradicts v2's event labels.
    - **5.6:** labelled `check_sensor`, v2's sensor action (§5 says `inspect_sensor`, which is not a v2 action).
    - **5.7 negative:** single-sensor agents cannot see HVAC state, so the HVAC teacher's `stuck_on` is used
      (warning, `schedule_or_control_fault`).
    - **5.9:** the gap is collapsed in the window, and `event_active` = beyond limits.
    - **5.11:** chatter is not generated for tds; no qualifying calm windows exist.
- **Splits:**
  - train: train months, seen nodes;
  - dev (seed 4496) and test (seed 4495): test months, held-out nodes included.
  - All three are disjoint from each other, from v2's data and from every 3e/3f file.
- **Slices:** one per case, `rw5_<case>`. v2 is scored on the rw5 dev and test sets first.
- **Training:** SFT with 1.5× gold replay, no DPO on these labels (`build_rw5sft.py`).
- **Review page:** the 60-sample review page is `rw5/review/review.html` (`review_v2.py`).
- **Continuing training from the interpolated model:** `mix_to_lora.py` writes the delta-space mix exactly as one
  rank-64 LoRA: B = [√w_i·B_i], A = [√w_i·A_i] at the same scale, so BA = Σ w_i·B_iA_i. This lets SFT continue
  from mixA50 itself.

## 6. Resource rules (owner on the laptop)
- One GPU job at a time.
- Every step waits for ≥ 3 GB of Windows free RAM (`gated.sh`, `waitfree` in `pipe_3f.sh`/`master_3f.sh`).
- Everything runs at nice 19 with idle IO.
- llama-server runs with `-ngl 99 -t 2 -tb 2` (`host_eval3e.use_cuda`); quantize uses 2 threads.
- `ramguard3f.ps1` drops the WSL cache below 2 GB free, then pauses (SIGSTOP) the 3f jobs and resumes them at
  3 GB. The 3e `ramguard.ps1` (1.5 GB) also runs.
- Building a GGUF next to an eval drove free RAM below 1.5 GB, so builds and evals are now strictly serial.
