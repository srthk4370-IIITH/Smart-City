# Long-range detectors (12 h CPU checks): what they add to the 4 h agent (2026-10-16)

## Why
The window study (`../2026-10-16_window_study`) showed:
- The 4 h agent is the most accurate, but it misses changes that started hours ago or build slowly.
- A 12 h agent catches those, but it misnames events and raises more false alarms.
- Team decision: keep the 4 h agent, and add cheap CPU checks over 12 h whose findings go to the reasoner
  as evidence.

## Protocol
- **Tuning** uses only dev-month windows (Sep–Oct): `training/window_study/longrange.py`,
  `daily_baseline.py`.
- **Evaluation** runs once, on test-month windows (Nov–Dec). The agent's answers there are the real NPU
  outputs from the window study (4 h prompts).
- **Calm reference.** A window counts as calm only if each of its three 4 h slices passes the training
  generator's calm test (`piecewise_calm`). The first calm filter was too loose: real tank refills and
  load steps slipped through.

## What was tried
| variant | dev result | kept? |
|---|---|---|
| raw 12 h: level shift + slow drift + recurring excursions | best case: 15% false alarms on calm while catching 15–30% | no |
| plus each sensor's own spread as scale (`kQ`) | min false alarms 13–15%; recurring excursions ≈ chance | partly |
| **daily baseline** (today minus the same hours yesterday) | worse: dev min FP 15% with 19–23% caught; test FP 29% | **no** |
| **raw 12 h level shift + slow drift**, recurring excursions removed | dev FP 2%, old steps 64%, drifts 57% | **yes** |

The daily baseline failed because yesterday has its own events and noise: differencing adds them in
instead of cancelling routine. Detecting recurring sub-threshold excursions failed in every variant,
because real sensors have those all the time.

Final parameters: `params_final.json`. Level shift ≥ 4× scale and steep; drift ≥ 4× scale with r² ≥ 0.8.
Scale = max(robust 5-minute noise, ½ the metric's floor, 1 × the IQR of the first 3 h).

## Test-month results (window-study cases, real NPU agent answers)
| | agent 4 h | detectors only | **agent 4 h + detectors** | agent 12 h |
|---|---|---|---|---|
| all injected events detected (n=364) | 78% | 35% | **83%** | 82% |
| false alarms, piecewise-calm (n=39) | 31% | 3% | **31%** (no new ones) | 33% |
| old step, 2.5–8 h ago (n=60) | 73% | 68% | **93%** | 100% |
| slow drift, 6–12 h (n=60) | 83% | 40% | **95%** | 93% |
| recurring small spikes (n=75) | 32% | 5% | 32% | 52%* |
| pattern accuracy | 64% | – | 64% (agent unchanged) | 42% |

\* Mostly "flatline" misreads (window study).

- **Paired tests, combined vs agent alone:**
  - Old steps: +12 caught, 0 lost, p = 0.0005.
  - Drifts: +7 caught, 0 lost, p = 0.016.
  - Clean windows: no change.
  - Files: `paired_combined.txt`, `evaluate_test.md`.
- **How often the detectors fire on random real windows:** 10% (16/160). That is real traffic for the
  reasoner, not necessarily false.
- **Daily baseline and ablation tables:** `../2026-10-16_daily_baseline/evaluate_test.md`,
  `ablation_no_excursions.txt`.

## Conclusion
1. **Ship level shift + slow drift as reasoner evidence.** They catch most of what the 4 h agent misses,
   add no false alarms on calm windows, and leave the agent's accuracy untouched.
2. **Recurring sub-threshold spikes remain unsolved** by both the agent and the detectors. Options are a
   per-sensor learned baseline over several days, or labelled real examples.

## Limits
- The test months have no water windows with 36 h of contiguous calm data (daily-baseline test), and
  weather has no 12 h windows at all.
- n = 39–75 per family.
