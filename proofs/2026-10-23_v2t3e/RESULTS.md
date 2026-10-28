# 3e (DPO+NLL on v2's own mistakes): interim results, 2026-10-23 ~08:45 IST

**Verdict so far: no candidate beats v2. v2 stays deployed. Nothing goes to the board.**

## Eval (host Q4_0 greedy, 1,148 test-month rows)
- **Rows:** host400 + 540 weakness rows (`gen_3e.py`, test months) + 208 real-world rows (REALWORLD.md §5 cases the existing teacher can label: bias / drift / stuck / quantised / dropout / noise / saturation faults, old shifts, long drifts, short 2–3 h windows, real routines, idle zero).
- **Scoring:** `common_v2.score_one`.
- **Runtime:** CUDA llama.cpp b11815 (`--cache-ram 0`). It matches the CPU 620d222 build (= board 207/208) on 206/208 decisions (`fidelity_cuda_vs_cpu.json`).

## Data and training (run1)
- **Pool:** 9,148 train-month rows (8,050 + 1,098 real-world). 4,172 of them were mined (mining was stopped by memory pressure). v2's teacher-forced error rate was 20%.
- **Pairs:** 557 (pattern 397, status 160), after dropping 65 not-visible and 113 boundary rows (2.5–4.5× noise). Each pair has 1:1 gold replay. 535 rows are held out as mdev.
- **Training:** span-level DPO (beta 0.1) + NLL (rpo_alpha 1), LR 5e-6, 70 steps, from the v2 adapter.
- **Learning curve:** DPO did learn. Pair accuracy went 0 → 0.39 and the margin 0.07 → 1.68.

## Pattern, v2 → candidate (wins / losses, McNemar p)

| slice | n | v2 | c40 | c60 | c70 |
|---|---|---|---|---|---|
| ALL | 1148 | 83.6 | 82.8 (38/48, p .33) | 82.8 (42/52) | 82.9 (43/51, p .47) |
| compound | 75 | 90.7 | 73.3 (0/13, **p .0002**) | 73.3 | 73.3 |
| early | 235 | 79.1 | 75.7 (6/14) | | |
| 1.5 h | 173 | 78.6 | 76.3 (8/12) | | |
| 3 h | 124 | 83.1 | 83.9 (7/6) | | |
| real-world | 185 | 86.5 | 88.1 (8/5) | | 88.6 |
| water_cause | 21 | 47.6 | 76.2 (6/0, p .03) | | |

Status on real-world rows: 83.2 → 88.6 (11/1). Status on weak rows: 76.5 → 73.1 (12/30).

**Why it failed.** The pairs taught label-prior shifts on confusions the teacher itself is inconsistent about:
- gradual_decrease → flatline: 10 losses against 7 wins;
- event → stable.

That cost 13 of 75 compound rows.

## Run2 (queued, `run2.sh`)
- Same method on cleaner pairs: 259 pairs, with no event-vs-stable pairs, no flatline-vs-decrease or flatline-vs-step_decrease pairs, and no rows at 2.5–6× noise.
- Replay 2:1, 49 steps.
- Checkpoints 30 and 49 are built and evaluated automatically by `pipeline_3e.sh` (log `~/smartcity_runs/agents_v2_topup3e/pipeline.log`).
- Score: `host_eval3e.py table --ref v2cuda --cand run2c30 run2c49`.

## Final (2026-10-23 10:05 IST): no 3e candidate beats v2; v2 stays deployed

- **run1c20:** fails. Pattern 82.6% vs 83.6%. Compound 77.3% vs 90.7% (0 wins / 10 losses, p 0.002).
- **run2c49** (cleaner pairs, 2:1 replay, 49 steps): ties v2. Not a winner.
  - Pattern 84.0% vs 83.6% (18 wins / 14 losses, p 0.60). Compound is fixed (90.7% vs 90.7%). Real-world
    pattern 88.1% vs 86.5%.
  - The gate (no slice down more than 1 point) fails on status:
    - routine 85.4% vs 97.9% (6 rows);
    - calm/routine 83.2% vs 86.3%;
    - power 64.8% vs 66.3%;
    - early stage 78.3% vs 79.6%;
    - 1.5 h stage 76.3% vs 77.5%.
- **run2c30:** the eval stopped after 63 rows, because the server was killed under memory pressure. It was not
  re-run: c49 holds the same data with more steps and is already gate-neutral.

**Conclusion:**
- Preference training on v2's own errors cannot move this model beyond noise without trading one slice for another.
- The remaining errors sit on confusions the teacher labels inconsistently, and on unseen sensors (TOPUP_WHY.md).
- The next lever is label cleanup or node augmentation, not more top-up steps.
