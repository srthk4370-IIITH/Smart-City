# D4 confidence recalibration of the v2 agent (device, Q4_0 on htpd)

Spec D4 (RETRAIN_V2_SPEC): the backend recalibrates the agent's confidences from device results. There is no retraining.

## Method
- **What is predicted:** P(pattern correct) for one device v2 agent answer. Pattern correctness is exact match, the same scoring as common_v2.
- **Cells:** one cell per (pattern the model predicted, onset-age bucket).
  - Onset age is computed exactly as the app does it in `features_v2.go onsetAge(f.Onset, n, end)`: readings from the model's own onset HH:MM to the window end, searched inside the window's n readings; -1 when there is no onset or the onset is outside the window.
  - The Python port is `c0_rows.py onset_age`. The Go test `TestD4MatchesPythonFixtures` checks the two agree on 300 held-out answers.
  - Buckets: none, 1-6, 7-12, 13-24, 25-48, 49-96, 97-144.
- **Estimator:** binned empirical-Bayes shrinkage. Each cell is pulled toward its pattern's rate, and each pattern toward the global rate: `p = (k + A*p_parent)/(m + A)`.
  - A = 5, chosen by 5-fold event-grouped cross-validation on Brier score.
  - Each cell has a Wilson 95% interval in `table_cells.md`.
- **Fit set:** the 2026-10-20 device answers, 4,590 rows.
  - placement_v2: 3,554 answers. Its clean windows (no injected event) appear at n = 48, 96 and 144. Truth there is "stable", so any other pattern counts as a miss for its cell.
  - host400 and test_all, deduplicated. Their negative rows are scored against the teacher label.
- **Clean weight 2:** each clean fit row counts twice. Clean rows are 588 of the 4,590, so with weight 1 the event rows dominate every cell. See "Clean windows" below.
- **Held out:** placement_s24 from 2026-10-21 (seed 24, 182 events + 100 clean windows, 3,538 usable answers). It was not used to fit any number in the table.
- **Dropped:** 95 answers with no parseable confidence or a pattern outside the enum. The policy gate rejects these, so they are never shown with a confidence.

The model's own confidence barely ranks right answers above wrong ones (held-out AUC 0.585). Its trained targets were constants per pattern. So the table **replaces** the confidence rather than remapping it. Isotonic regression on the raw value makes calibration worse (ECE 0.178). Splitting cells further by raw confidence, window length, or the model's own status did not help on held-out data.

## Results (held out: placement_s24)
| subset | metric | model confidence | first table (clean weight 1) | **shipped table (clean weight 2)** |
|---|---|---|---|---|
| all (n=3,538) | ECE / Brier / AUC | 0.152 / 0.234 / 0.585 | 0.050 / 0.149 / 0.798 | **0.051 / 0.150 / 0.792** |
| events only (n=3,240) | ECE / Brier / AUC | 0.167 / 0.235 / 0.584 | 0.062 / 0.135 / 0.842 | 0.067 / 0.145 / 0.811 |
| clean only (n=298) | ECE / Brier / AUC | 0.207 / 0.214 / 0.662 | 0.441 / 0.299 / 0.377 | **0.345 / 0.196 / 0.678** |
| events, d <= 8 (early) | ECE / Brier | 0.318 / 0.328 | 0.113 / 0.195 | 0.112 / 0.207 |
| events, d >= 18 (refinements) | ECE / Brier | 0.090 / 0.168 | 0.056 / 0.100 | 0.060 / 0.110 |
| clean false-alarm calls (non-stable, n=107) | mean shown / share >= 0.8 | 0.64 / 25% | 0.54 / 23% | 0.50 / 23% |

Bootstrap 95% intervals, grouped by event:
- Shipped table minus model confidence, all held-out rows: ECE -0.140 to -0.062, Brier -0.101 to -0.066.
- Shipped minus first table, events only: Brier +0.007 to +0.015; ECE -0.007 to +0.024, which is not significant.

Cross-validation on the fit set: ECE 0.126 -> 0.056, Brier 0.209 -> 0.150.

The reliability diagram is in `reliability.svg` (left: cross-validation on the fit set; right: held-out placement_s24).

## Clean windows (follow-up; see c3_clean.py and clean_study.md)
- **Clean rows were already in the fit set.** They are about 13% of it, so in a cell shared by clean and event rows the event rows set the rate.
- **The first table's clean regression came mostly from `stable`, not from confident false alarms.** On a clean window `stable` is always right, yet it was shown as about 0.49. Non-stable calls on clean windows were already shown lower than the model's own number (mean 0.54 vs 0.64).
- **I checked other ways to separate clean windows from events, and none work.** Within a cell, the model's status, event_active and onset age do not tell clean windows from events. event_active is constant per pattern.
- **Clean weight is a trade-off, and 2 is the stopping point.**
  - Raising it improves clean-window scores and worsens event scores.
  - At weight 2, clean-window Brier and AUC beat the model's own confidence. Overall scores are unchanged (ECE +0.001, Brier +0.001). Event-only Brier rises 0.010 (7%), though it stays 38% below the raw confidence.
  - At weight 4, event-only Brier rises 0.025, so I stopped at 2. To restore the first table, run `c1_fit.py --clean-weight 1 --apply`.
- **Still open:** 23% of false alarms on calm data still show >= 0.8. These are mostly flatline/sensor_fault calls: power-factor sensors pinned at 0.999, long zero-flow runs, and a few erratic/critical power calls. A cell-level table cannot separate them from real flatlines. That would need the rule decisions listed in `analytics.md`.

## Table highlights (shipped)
- **Young onsets (1-6 readings):** dip 0.6, erratic 0.5, flatline 0.5, gradual_increase 0.6, exponential_increase 0.7.
- **Onsets 13-24 readings old:** most patterns 0.85-0.99.
- **Onset dated far back (49+ readings):** spike 0.13, oscillation 0.2-0.3, exponential_increase 0.4-0.6.
- **stable:** about 0.65-0.77 across ages.
- **HVAC and occupancy patterns:** fitted only on teacher test rows (5-15 rows per pattern), giving 0.89-0.99. placement_s24 has no HVAC or occupancy cases, so these have **no held-out check**.

## In the app
- **`features_v2.go`:**
  - `ConfRecalRow` and `ConfidenceRecalV2`, a generated block between the `// BEGIN/END generated D4 table` markers.
  - `RecalibrateConfidence` now uses the no-onset row, normalises the pattern enum, and falls back to the `"*"` row.
  - `applyConfidenceRecal` takes the window length from the prompt's `WINDOW: ... N x 5 min` line.
- **`reason.go`:** runAgent calls `applyConfidenceRecal(&call, s.End, ai.Prompt)` right after the policy gate. It applies to valid v2 answers only; the model's own number stays in `call.Raw`.
- **What reads the calibrated value:** the dashboard (agent cards, report confidence bar), the isolated report, the fallback report (which takes the lowest confidence among contributing findings), and the synthesizer prompt's `confidence=` line.
- **No confidence threshold gates alerting** anywhere in the backend or web UI. Two things do change, reported but not altered:
  - Fallback reports break severity ties by confidence, so ordering can change.
  - The synthesizer now sees calibrated numbers.

## Rerun
```
py -3 c0_rows.py --placement ..\..\2026-10-21_v2_confirm\placement_s24    # rows.json
py -3 c1_fit.py --apply      # metrics, table_cells.md, reliability.svg, Go table + testdata/d4_calib_fixtures.json
py -3 c3_clean.py            # clean-weight / status-split study (clean_study.md)
py -3 c2_analytics.py        # analytics.md / analytics.json
```
