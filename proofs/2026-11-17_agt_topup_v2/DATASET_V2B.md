# DATASET_V2B: error-driven top-up data (generated 2026-11-17 11:44:02)

Why: the Kaggle eval of the v2 snapshots (latest: s0200) was NOT GOOD (see ../data/kaggle_eval/DECISION.md). Failure rates per generator key come from the failed rows of tool turn 1 (missed or unneeded calls, wrong tool/args), tool final answers and the hard-case slice, by family.

| generator key | eval rows | failed | rate | multiplier (raw) | multiplier (rescaled to the v2 new-row total) |
|---|---|---|---|---|---|
| dyn | 30 | 0 | 0.00 | 0.80 | 0.56 |
| hard_standby | 18 | 3 | 0.17 | 1.33 | 0.94 |
| hard_leak | 20 | 2 | 0.10 | 1.20 | 0.85 |
| hard_night | 15 | 0 | 0.00 | 0.80 | 0.56 |
| hard_plateau | 25 | 3 | 0.12 | 1.24 | 0.88 |
| hard_limits | 27 | 6 | 0.22 | 1.44 | 1.02 |
| hard_ph | 12 | 2 | 0.17 | 1.33 | 0.94 |
| weak | 43 | 7 | 0.16 | 1.33 | 0.94 |
| tool_history | 60 | 34 | 0.57 | 2.13 | 1.51 |
| tool_neighbors | 32 | 22 | 0.69 | 2.38 | 1.68 |
| tool_card | 12 | 10 | 0.83 | 2.50 | 1.77 |
| tool_card_neighbors | 12 | 9 | 0.75 | 2.50 | 1.77 |

What changed vs v2 data: (1) gen_run.py PLAN counts x the multipliers above (env FAM_MULT), more and more varied scenarios of the failing kinds (new generator seed 2117 -> different random scenarios, windows, values, neighbours; dyn_* rows are the clear 'no call needed' negatives so they are up-weighted when direct_ok fails); (2) families with < 10 % failures are down-weighted to 0.8 before the rescale; (3) replay stays ~55-58 % of the mix (real val protection); (4) all checks re-run (check_data_v2.py: schema, tool protocol, gold consistency, leakage, 904+240+136 <= 1280 tokens).

Result: {"n_total": 10152, "new": 4604, "replay": 5548, "replay_frac": 0.5465, "real_replay": 3711, "steps_1_pass": 318, "tool_share_of_new": 0.3369, "local": {"val_sel": 400, "tool_t1": 90, "tool_t2": 56, "hard_val": 265}}
Checks: PASSED (/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2/data_b/checks_report.json). Continuation dev (fixed, seed 5151, disjoint from the eval sets): gendev: 30 call, 15 direct, 15 final, 40 hard.
