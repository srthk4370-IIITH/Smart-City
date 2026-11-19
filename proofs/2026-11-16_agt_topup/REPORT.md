# agt_v3 laptop top-up on REAL windows (2026-11-16)

Laptop only (RTX 4050, WSL); real per-sample data never left the laptop. Raw: `~/smartcity_runs/agt_topup/` (data, mix, run, post, gate).
Scripts: `scripts/` (build_data.py, mix.py, chain.sh, gate_subset.py, report.py). Log: `STATUS.md`.

## Data
```
{
 "pools": {
  "sft_v2": 35946,
  "topup2": 7999,
  "rw5": 517,
  "rw5x": 30
 },
 "drop": {
  "audit_not_visible": 2828,
  "excl_overlap": 309,
  "verify:ungrounded": 125,
  "verify:warning_but_1h_avg_critical": 11,
  "verify:rerender_error": 61,
  "dup": 7059,
  "verify:noise_fault_weak": 17,
  "verify:rerender_mismatch": 2
 },
 "kept_real": 34141,
 "real_train": 30724,
 "real_val": 3417,
 "val_groups": 325,
 "hvac_rerender_unchecked": 5939,
 "real_train_by_status": {
  "normal": 17785,
  "warning": 6342,
  "critical": 3380,
  "sensor_fault": 3217
 },
 "real_train_by_role": {
  "occupancy": 4228,
  "hvac": 5330,
  "water": 5342,
  "air_quality": 5399,
  "power": 6075,
  "weather": 4350
 },
 "real_val_by_status": {
  "sensor_fault": 362,
  "warning": 753,
  "normal": 1816,
  "critical": 486
 }
}
```
## Mix
```
{
 "n_total": 6464,
 "real": 3230,
 "real_available": 30724,
 "replay": 3234,
 "replay_by_family": {
  "ex_stable": 315,
  "hole_water": 171,
  "unseen_metric": 397,
  "ex_event": 821,
  "calm_routine": 575,
  "ex_fault": 138,
  "ex_hvac": 110,
  "dq_edge": 96,
  "hole_recall": 95,
  "hole_calm_fault": 136,
  "ex_longrange": 101,
  "hole_power": 206,
  "ex_occupancy": 73
 },
 "real_by_status": {
  "critical": 355,
  "normal": 1870,
  "warning": 667,
  "sensor_fault": 338
 },
 "real_by_role": {
  "hvac": 560,
  "water": 561,
  "power": 639,
  "occupancy": 445,
  "air_quality": 568,
  "weather": 457
 },
 "val_sel": 400,
 "val_sel_by_role": {
  "power": 119,
  "occupancy": 55,
  "air_quality": 90,
  "water": 74,
  "hvac": 62
 },
 "val_sel_by_status": {
  "sensor_fault": 38,
  "warning": 95,
  "normal": 213,
  "critical": 54
 },
 "syn_slice": 120
}
```
## Pilot
```
{"tok_s": 469, "tok_per_row": 1028.3667711598746, "s_per_step": 71.08749997615814, "loss_first": 0.11992, "loss_10": 0.07323, "steps": 10}
```
## Selection curve (merged Q4_0, shared agt_v3 imatrix, host GPU, REAL VAL 400 rows + synthetic slice 120 rows)

| step | REAL VAL | synthetic slice |
|---|---|---|
| B50 (v2 prompts of the same REAL VAL windows) | score 0.9072, status 92.0, pattern 89.0, cause 90.8, dq 0.0 (n 400) | - |
| 0 = snap_1750 | score 0.6860, status 67.2, pattern 63.2, cause 64.0, dq 87.5 (n 400) | score 0.9033, status 90.8, pattern 90.0, cause 85.8, dq 94.2 (n 120) |
| 75 | score 0.7529, status 73.8, pattern 70.2, cause 71.0, dq 0.9375 (n 400) | score 0.8942, status 89.2, pattern 90.0, cause 86.7, dq 0.9167 (n 120) |
| 150 | score 0.7445, status 73.2, pattern 69.8, cause 69.2, dq 0.9225 (n 400) | score 0.8733, status 85.8, pattern 89.2, cause 84.2, dq 0.9083 (n 120) |
| 202 | score 0.7512, status 73.2, pattern 72.2, cause 69.5, dq 0.915 (n 400) | score 0.8933, status 88.3, pattern 89.2, cause 87.5, dq 0.9417 (n 120) |

Best step: **75** (REAL VAL score 0.75288; since best 2; stop True). ![curve](curve.png)

## Small re-gate (subsets: dev_paired 600 pairs, E1 184, unseen_metric 150, unseen_layout 200, campus 200, calm_fault 150, rename 100 pairs)
B50 and snap_1750 samples are the 2026-11-15 full-gate outputs sliced to the same rows (greedy, same GGUFs); only the top-up ran anew.

Verdict: top-up **FAIL**, snap_1750 on the same subsets **FAIL**

| check | agt_v3 topup snap_0075 (7fa44fd489047170eead7ec8d7e7a406) | agt_v3 snap_1750 (same subsets) |
|---|---|---|
| JSON validity 100 % (all sets) | PASS 1164/1164 | PASS 1164/1164 |
| dev: every v3 row paired with a B50 row | PASS 400/400 paired | PASS 400/400 paired |
| dev: net (pattern+status+cause wins - losses) > 0 | **FAIL** net -189 over 400 pairs | **FAIL** net -223 over 400 pairs |
| dev: severity-weighted status net >= 0 | **FAIL** -69 | **FAIL** -86 |
| dev: no Holm-worse slice (exact sign test, alpha 0.05) | **FAIL** worse: ALL.cause 84.0->67.5 (24/90), ALL.pattern 84.2->66.2 (18/90), ALL.status 84.5->71.8 (28/79), age_other. | **FAIL** worse: ALL.cause 84.0->63.5 (18/100), ALL.pattern 84.2->63.7 (12/94), ALL.status 84.5->69.8 (23/82), age_other |
| dev: calm/routine status not worse | **FAIL** B50 82.4 -> v3 74.8 (n 119) | **FAIL** B50 82.4 -> v3 72.3 (n 119) |
| dev: power status >= 78 | **FAIL** 60.4 (n 101) | **FAIL** 57.4 (n 101) |
| dev: water status >= 80 | **FAIL** 63.8 (n 94) | **FAIL** 59.6 (n 94) |
| dev: no domain status > 1 pt below B50 | **FAIL** air_quality 91.2->76.9; hvac 89.4->66.0; occupancy 100.0->95.7; power 68.3->60.4; water 83.0->63.8; weather 97 | **FAIL** air_quality 91.2->75.8; hvac 89.4->72.3; occupancy 100.0->100.0; power 68.3->57.4; water 83.0->59.6; weather 9 |
| dev: critical recall >= 85 | **FAIL** 68.2 (n 44; B50 86.4) | **FAIL** 63.6 (n 44; B50 86.4) |
| dev: calm false alarms <= 8 % | **FAIL** 22.5 % of 111 calm normal rows (B50 18.3 %) | **FAIL** 26.1 % of 111 calm normal rows (B50 18.3 %) |
| dev: stage_40min pattern >= B50 | **FAIL** B50 72.2 -> v3 59.7 (n 72) | **FAIL** B50 72.2 -> v3 50.0 (n 72) |
| dev: stage_1.5h pattern >= B50 | **FAIL** B50 88.2 -> v3 72.5 (n 51) | **FAIL** B50 88.2 -> v3 78.4 (n 51) |
| dev: stage_3h pattern >= B50 | **FAIL** B50 80.0 -> v3 67.5 (n 40) | **FAIL** B50 80.0 -> v3 65.0 (n 40) |
| dev: young k=3-7 pattern >= B50 | **FAIL** B50 - -> v3 - (n 0) | **FAIL** B50 - -> v3 - (n 0) |
| E1: net >= 0 | **FAIL** net -45 over 184 stories | **FAIL** net -62 over 184 stories |
| E1: safety 16/16 | **FAIL** 10/18 correct | **FAIL** 8/18 correct |
| rename agreement >= noise floor | **FAIL** orig vs renamed 95.0 (n 60); noise floor 98.3 (n 60) | PASS orig vs renamed 96.7 (n 60); noise floor 96.7 (n 60) |
| unseen_metric: status >= 85 | PASS 89.0 (n 100) | PASS 89.0 (n 100) |
| unseen_metric: pattern >= 80 | PASS 85.0 (n 100) | PASS 86.0 (n 100) |
| unseen_metric: dq >= 90 | PASS 94.0 (n 100) | PASS 97.0 (n 100) |
| unseen_layout: status >= 85 and >= B50 | PASS 88.0 (n 100; B50 82.2) | PASS 85.0 (n 100; B50 82.2) |
| test_campus (real held-out): status >= B50 | PASS B50 81.9 -> v3 95.2 (n 83) | PASS B50 81.9 -> v3 97.6 (n 83) |
| calm-looking fault recall >= 85 | PASS 91.8 (n 97) | PASS 97.9 (n 97) |
| fault precision >= 90 | PASS 95.6 of 204 sensor_fault calls are real faults | **FAIL** 88.7 of 239 sensor_fault calls are real faults |
| false 'broken sensor' calls <= 3 % | PASS 1.6 % of 551 non-fault windows called sensor_fault | **FAIL** 4.9 % of 551 non-fault windows called sensor_fault |

## No-harm check vs snap_1750 (paired exact sign test; harm = worse with p < 0.05)
```
{
 "no_harm": false,
 "harm": [
  "calm_fault.status 98.0->92.0",
  "calm_fault.cause 98.0->92.0",
  "calm_fault.dq 98.0->92.0"
 ],
 "sets": {
  "unseen_metric": {
   "n": 100,
   "status": {
    "topup": 89.0,
    "snap_1750": 89.0,
    "wins": 2,
    "losses": 2,
    "p": 1.0,
    "harm": false
   },
   "pattern": {
    "topup": 85.0,
    "snap_1750": 86.0,
    "wins": 1,
    "losses": 2,
    "p": 1.0,
    "harm": false
   },
   "cause": {
    "topup": 76.0,
    "snap_1750": 77.0,
    "wins": 3,
    "losses": 4,
    "p": 1.0,
    "harm": false
   },
   "dq": {
    "topup": 94.0,
    "snap_1750": 97.0,
    "wins": 0,
    "losses": 3,
    "p": 0.25,
    "harm": false
   }
  },
  "unseen_layout": {
   "n": 100,
   "status": {
    "topup": 88.0,
    "snap_1750": 85.0,
    "wins": 5,
    "losses": 2,
    "p": 0.4531,
    "harm": false
   },
   "pattern": {
    "topup": 91.0,
    "snap_1750": 88.0,
    "wins": 3,
    "losses": 0,
    "p": 0.25,
    "harm": false
   },
   "cause": {
    "topup": 89.0,
    "snap_1750": 86.0,
    "wins": 5,
    "losses": 2,
    "p": 0.4531,
    "harm": false
   },
   "dq": {
    "topup": 96.0,
    "snap_1750": 96.0,
    "wins": 2,
    "losses": 2,
    "p": 1.0,
    "harm": false
   }
  },
  "campus": {
   "n": 100,
   "status": {
    "topup": 93.0,
    "snap_1750": 95.0,
    "wins": 0,
    "losses": 2,
    "p": 0.5,
    "harm": false
   },
   "pattern": {
    "topup": 90.0,
    "snap_1750": 91.0,
    "wins": 1,
    "losses": 2,
    "p": 1.0,
    "harm": false
   },
   "cause": {
    "topup": 92.0,
    "snap_1750": 91.0,
    "wins": 4,
    "losses": 3,
    "p": 1.0,
    "harm": false
   },
   "dq": {
    "topup": 98.0,
    "snap_1750": 99.0,
    "wins": 0,
    "losses": 1,
    "p": 1.0,
    "harm": false
   }
  },
  "calm_fault": {
   "n": 100,
   "status": {
    "topup": 92.0,
    "snap_1750": 98.0,
    "wins": 0,
    "losses": 6,
    "p": 0.0312,
    "harm": true
   },
   "pattern": {
    "topup": 99.0,
    "snap_1750": 100.0,
    "wins": 0,
    "losses": 1,
    "p": 1.0,
    "harm": false
   },
   "cause": {
    "topup": 92.0,
    "snap_1750": 98.0,
    "wins": 0,
    "losses": 6,
    "p": 0.0312,
    "harm": true
   },
   "dq": {
    "topup": 92.0,
    "snap_1750": 98.0,
    "wins": 0,
    "losses": 6,
    "p": 0.0312,
    "harm": true
   }
  },
  "rename": {
   "n": 180,
   "status": {
    "topup": 87.8,
    "snap_1750": 81.7,
    "wins": 11,
    "losses": 0,
    "p": 0.001,
    "harm": false
   },
   "pattern": {
    "topup": 92.2,
    "snap_1750": 91.7,
    "wins": 4,
    "losses": 3,
    "p": 1.0,
    "harm": false
   },
   "cause": {
    "topup": 87.8,
    "snap_1750": 85.0,
    "wins": 10,
    "losses": 5,
    "p": 0.3018,
    "harm": false
   },
   "dq": {
    "topup": 98.3,
    "snap_1750": 98.3,
    "wins": 3,
    "losses": 3,
    "p": 1.0,
    "harm": false
   }
  },
  "synthetic_slice": {
   "n": 120,
   "status": {
    "topup": 89.2,
    "snap_1750": 90.8,
    "wins": 2,
    "losses": 4,
    "p": 0.6875,
    "harm": false
   },
   "pattern": {
    "topup": 90.0,
    "snap_1750": 90.0,
    "wins": 4,
    "losses": 4,
    "p": 1.0,
    "harm": false
   },
   "cause": {
    "topup": 86.7,
    "snap_1750": 85.8,
    "wins": 7,
    "losses": 6,
    "p": 1.0,
    "harm": false
   },
   "dq": {
    "topup": 91.7,
    "snap_1750": 94.2,
    "wins": 1,
    "losses": 4,
    "p": 0.375,
    "harm": false
   }
  }
 }
}
```
FINAL hand-off: NOT written (needs gate PASS and no harm)

