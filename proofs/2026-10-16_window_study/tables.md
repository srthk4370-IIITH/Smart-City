# Window-length study - results
## Headline (AI agents, QIDK NPU via htpd)
| | 24 pts (2 h) | 48 pts (4 h) | 96 pts (8 h) | 144 pts (12 h) |
|---|---|---|---|---|
| detection, all injected events | 66% (242/364) | 78% (282/364) | 80% (291/364) | 82% (299/364) |
| false alarms, clean windows (truth normal) | 35% (27/77) | 27% (21/77) | 38% (29/77) | 46% (35/77) |
| false alarms, strict clean (rules quiet at every length) | 5% (1/19) | 5% (1/19) | 0% (0/19) | 0% (0/19) |
| pattern accuracy (labelled families) | 46% (169/369) | 64% (235/369) | 56% (206/369) | 42% (157/369) |
| status accuracy | 58% (216/369) | 70% (258/369) | 64% (236/369) | 53% (197/369) |
| cause accuracy | 54% (199/369) | 68% (249/369) | 58% (213/369) | 50% (184/369) |
| valid JSON | 100% (602/604) | 99% (599/604) | 98% (594/604) | 98% (595/604) |
| rules (Mode 1) detection | 62% (227/364) | 78% (284/364) | 85% (309/364) | 88% (321/364) |
| rules (Mode 1) false alarms | 46% (35/77) | 43% (33/77) | 64% (49/77) | 70% (54/77) |

## Detection (any flag) per family
| | 24 pts (2 h) | 48 pts (4 h) | 96 pts (8 h) | 144 pts (12 h) |
|---|---|---|---|---|
| clean | 45% (26/58) | 34% (20/58) | 50% (29/58) | 60% (35/58) |
| clean_above_limit | 100% (3/3) | 100% (3/3) | 100% (3/3) | 100% (3/3) |
| clean_strict | 5% (1/19) | 5% (1/19) | 0% (0/19) | 0% (0/19) |
| classic_dip | 62% (8/13) | 92% (12/13) | 85% (11/13) | 92% (12/13) |
| classic_erratic | 75% (9/12) | 100% (12/12) | 100% (12/12) | 92% (11/12) |
| classic_exponential_increase | 100% (18/18) | 100% (18/18) | 94% (17/18) | 94% (17/18) |
| classic_flatline | 100% (18/18) | 100% (18/18) | 100% (18/18) | 83% (15/18) |
| classic_gradual_decrease | 100% (12/12) | 100% (12/12) | 83% (10/12) | 58% (7/12) |
| classic_gradual_increase | 78% (14/18) | 100% (18/18) | 100% (18/18) | 100% (18/18) |
| classic_oscillation | 100% (12/12) | 100% (12/12) | 58% (7/12) | 58% (7/12) |
| classic_spike | 50% (9/18) | 83% (15/18) | 67% (12/18) | 89% (16/18) |
| classic_step_decrease | 58% (7/12) | 92% (11/12) | 83% (10/12) | 67% (8/12) |
| classic_step_increase | 50% (9/18) | 100% (18/18) | 94% (17/18) | 94% (17/18) |
| classic_throttling | 72% (13/18) | 100% (18/18) | 100% (18/18) | 89% (16/18) |
| drift_long | 73% (44/60) | 83% (50/60) | 90% (54/60) | 93% (56/60) |
| step_old | 60% (36/60) | 73% (44/60) | 87% (52/60) | 100% (60/60) |
| subthr_spikes | 44% (33/75) | 32% (24/75) | 47% (35/75) | 52% (39/75) |

## Pattern accuracy per family
| | 24 pts (2 h) | 48 pts (4 h) | 96 pts (8 h) | 144 pts (12 h) |
|---|---|---|---|---|
| clean | 55% (32/58) | 66% (38/58) | 50% (29/58) | 40% (23/58) |
| clean_above_limit | 67% (2/3) | 67% (2/3) | 67% (2/3) | 0% (0/3) |
| clean_strict | 84% (16/19) | 95% (18/19) | 100% (19/19) | 79% (15/19) |
| classic_dip | 54% (7/13) | 85% (11/13) | 69% (9/13) | 85% (11/13) |
| classic_erratic | 42% (5/12) | 92% (11/12) | 58% (7/12) | 17% (2/12) |
| classic_exponential_increase | 56% (10/18) | 94% (17/18) | 67% (12/18) | 61% (11/18) |
| classic_flatline | 100% (18/18) | 100% (18/18) | 94% (17/18) | 78% (14/18) |
| classic_gradual_decrease | 100% (12/12) | 100% (12/12) | 67% (8/12) | 50% (6/12) |
| classic_gradual_increase | 67% (12/18) | 83% (15/18) | 50% (9/18) | 6% (1/18) |
| classic_oscillation | 100% (12/12) | 100% (12/12) | 42% (5/12) | 25% (3/12) |
| classic_spike | 33% (6/18) | 61% (11/18) | 56% (10/18) | 56% (10/18) |
| classic_step_decrease | 33% (4/12) | 92% (11/12) | 58% (7/12) | 8% (1/12) |
| classic_step_increase | 28% (5/18) | 94% (17/18) | 67% (12/18) | 33% (6/18) |
| classic_throttling | 61% (11/18) | 100% (18/18) | 89% (16/18) | 56% (10/18) |
| drift_long | 22% (13/60) | 27% (16/60) | 37% (22/60) | 35% (21/60) |
| step_old | 7% (4/60) | 13% (8/60) | 37% (22/60) | 38% (23/60) |

## What the agent called the sub-threshold recurring spikes
- 24 pts: [('stable', 42), ('spike', 10), ('erratic', 8), ('dip', 6), ('step_increase', 6)]
- 48 pts: [('stable', 51), ('spike', 10), ('erratic', 8), ('dip', 4), ('oscillation', 1)]
- 96 pts: [('stable', 39), ('flatline', 11), ('spike', 9), ('dip', 8), ('erratic', 6)]
- 144 pts: [('stable', 33), ('flatline', 25), ('spike', 8), ('dip', 5), ('INVALID', 3)]

## Variety on real (uninjected) test windows
| | 24 pts (2 h) | 48 pts (4 h) | 96 pts (8 h) | 144 pts (12 h) |
|---|---|---|---|---|
| share flagged | 55% (88/160) | 67% (104/155) | 73% (115/157) | 71% (113/160) |
| distinct patterns | 9 | 13 | 15 | 12 |
| distinct (pattern, status, cause) | 18 | 22 | 26 | 23 |
| distinct flagged outcomes | 14 | 19 | 23 | 19 |

## Cost
| | 24 pts (2 h) | 48 pts (4 h) | 96 pts (8 h) | 144 pts (12 h) |
|---|---|---|---|---|
| prompt tokens (mean) | 539.2 | 583.5 | 672.0 | 760.5 |
| output tokens (mean) | 69.3 | 71.5 | 74.1 | 72.3 |
| batch time, s | 8.73 | 9.25 | 10.93 | 12.22 |
| batch prefill, s | 3.81 | 4.29 | 5.23 | 6.49 |
| s per agent inside a batch | 1.091 | 1.164 | 1.374 | 1.536 |
