# Window-length study (QIDK NPU, 2026-10-16)

**Question:** what does a domain agent see, and flag, with a 2, 4, 8 or 12 hour window?

## Method
- **Model and runtime.** The same fine-tuned Llama 3.2 3B the app uses, on the QIDK NPU, through htpd v6
  (final config, 8 streams × 1024 ctx, batches of 8). Greedy decoding.
- **What changes and what doesn't.** Every window ends at the same evaluation instant, and only the
  length changes: 24, 48, 96 or 144 points of 5-minute samples. The prompt format is the training one,
  with the window text ("N x 5 min", "a N-hour window", "mean Nh") and the 10-minute-means series line
  sized to the length. At 48 points the prompt is asserted byte-identical to the training prompt.
- **Data.** Real sensor windows from the held-out test months (Nov–Dec). Builder: `training/window_study/window_study.py build`, seed 7, `cases.jsonl` sha256/16 = see `manifest.json`.
- **Cases.** 604 cases × 4 lengths = 2416 NPU calls:

| family | n | what it is | truth |
|---|---|---|---|
| clean | 80 | real calm window untouched | stable/normal (77 normal; 3 sit above a limit → excluded) |
| classic_* | 169 | one of 11 training patterns injected in the last 4 h | training generator labels |
| step_old | 60 | step 2.5–8 h before the end | step_increase/decrease, should be flagged |
| drift_long | 60 | slow drift over the last 6–12 h | gradual_increase/decrease, should be flagged |
| subthr_spikes | 75 | 3–5 small spikes (2–3.5× noise scale, below the training spike size and below warning limits) spread over 2–12 h, the last in the final 30 min | any flag counts as detection |
| real | 160 | random real windows, no injection | none; used to count variety |

- **Roles.** Air quality, water and power. Weather had no continuous 12 h windows and is excluded.
  Water had only 20 calm 12 h bases, so its cases reuse them. Occupancy appears only in the variety probe.
- **Scoring.**
  - Flag = status ≠ normal, or pattern ≠ stable/vacant/occupied.
  - Rates carry 95% Wilson CIs. Same cases at every length, so the paired tests are McNemar (`paired_tests.txt`).
  - Rules (Mode 1) are scored on the same windows as the baseline.
- **Clean windows are not perfectly clean.** Real data holds real dips and spikes, so "false alarms on
  clean" over-counts. A strict subset (19 windows where the rule classifier is quiet at every length)
  bounds the true false-alarm rate from below.
- **Raw data** (`samples.jsonl`): exact text, tokens, batch time, prefill time and board temperature
  for every sample. All prompts are in `prompts.jsonl`.

## Results (AI agents)
| | 2 h | **4 h (trained)** | 8 h | 12 h |
|---|---|---|---|---|
| detection, all injected events (n=364) | 66% | 78% | 80% | 82% |
| false alarms, clean (truth normal, n=77) | 35% | **27%** | 38% | 46% |
| false alarms, strict clean (n=19) | 5% | 5% | 0% | 0% |
| pattern accuracy (n=369) | 46% | **64%** | 56% | 42% |
| status accuracy | 58% | **70%** | 64% | 53% |
| cause accuracy | 54% | **68%** | 58% | 50% |
| old step (2.5–8 h ago) detected | 60% | 73% | 87% | **100%** |
| slow drift (6–12 h) detected | 73% | 83% | 90% | **93%** |
| recurring sub-threshold spikes flagged | 44% | 32% | 47% | 52%* |
| variety: distinct (pattern, status, cause) on 160 real windows | 18 | 22 | **26** | 23 |
| s per agent in a batch of 8 | 1.09 | 1.16 | 1.37 | 1.54 |
| prompt tokens | 539 | 584 | 672 | 761 |

\* At 12 h, 25 of the 39 sub-threshold "detections" are the agent calling the window **flatline**. That is
a misreading: its flat-run statistics are tuned for 4 h. Only about 8 are actually called spikes.

**Paired tests vs 4 h (McNemar):**
- Pattern accuracy on classic events: 4 h is better than every other length, p < 0.0001.
- Old steps: 12 h catches 16 that 4 h misses and misses none, p < 0.0001.
- Clean false alarms: 12 h raises 20 that 4 h doesn't (6 the other way), p = 0.009.
- 8 h vs 4 h is not significant for drift, old steps or false alarms (p = 0.11–0.34).

**Rules (Mode 1) on the same windows:** detection 62 / 78 / 85 / 88%, but false alarms on clean
46 / 43 / 64 / 70%. The rule thresholds are tuned to 4 h too, and at 12 h they flag 93% of the
non-strict clean windows.

## What this means
1. **4 h is the best single window for this model.** Accuracy peaks there: pattern 64%, status 70%,
   cause 68%. The model was trained on that length, and every other length significantly lowers
   pattern accuracy.
2. **Longer windows do catch slow and old changes.** An old step goes from 73% to 100% detected, a long
   drift from 83% to 93%. But the agent often names them wrongly, and false alarms on real calm data go
   up (27% → 46% at 12 h). Some of that "false alarm" increase is real older history in the window, not
   the model's error.
3. **Recurring small spikes are not caught by a longer window.** No length recognises them reliably
   (32–52%), and the apparent 12 h gain is mostly "flatline" misreads. Your hypothesis ("more such spikes
   → the AI would do better") is **not supported with the current model**. The model was never taught
   that pattern, and its statistics (max, largest 5-min change) don't count repeated excursions.
4. **2 h is worst on almost everything.**
5. **Cost:** 8 h adds about 18% per agent and 12 h about 32% (longer series line, about +90/+180 tokens).

## Limits
- Out-of-distribution lengths: this measures the current model, not what a model trained at 8 or 12 h
  could do.
- n per family is 12–75, so per-family differences under ~15 points are within noise (see the CIs).
- Weather is excluded; water has few distinct bases.
- Only one evaluation instant per case. A deployed agent re-evaluates every 5 minutes, which helps short
  windows catch short events at the time they happen.

## Files
`cases.jsonl` · `prompts.jsonl` · `samples.jsonl` · `manifest.json` · `summary.json` · `tables.md`
(full per-family tables) · `paired_tests.txt` · `headline.svg` · `per_family_flag.svg` · `variety_cost.svg`.
