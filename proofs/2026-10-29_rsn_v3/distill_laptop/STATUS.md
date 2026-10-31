# rsn_v3 laptop chat distillation: STATUS (FINAL)

- updated 2026-10-30 16:23:07, elapsed 7.02 h (paused 2.21 h), job distill_laptop, pid 7218
- records done this run 497 / 7068 to do (103 rec/h); ETA 63.5 h
- generated tokens 820164 in 8289 requests; aggregate 47.4 tok/s wall, per-request decode 8.7 tok/s; mean prompt tokens evaluated (not cached) 918
- GPU 72 C, 5717 MiB, 0% util; Windows free RAM 1937 MB; paused: no (17 pauses); server restarts 0
- stop: wall cap 7.0 h; think compression: {'compressed_ok': 356, 'compressed_fail': 8}

| set | kind | hard | records | samples | pass | pass_long | forced | sample pass | question pass |
|---|---|---|---|---|---|---|---|---|---|
| dev(earlier) | actions | 0 | 6 | 24 | 6 | 0 | 0 | 0.25 | 0.83 |
| dev(earlier) | actuation | 0 | 6 | 24 | 24 | 0 | 0 | 1.00 | 1.00 |
| dev(earlier) | compare_buildings | 1 | 5 | 14 | 6 | 0 | 6 | 0.43 | 0.60 |
| dev(earlier) | compare_days | 1 | 5 | 20 | 2 | 0 | 6 | 0.10 | 0.40 |
| dev(earlier) | compare_levels | 1 | 5 | 18 | 8 | 3 | 2 | 0.44 | 1.00 |
| dev(earlier) | compare_periods | 1 | 5 | 18 | 4 | 3 | 2 | 0.22 | 0.60 |
| dev(earlier) | count_metric | 0 | 6 | 24 | 18 | 0 | 0 | 0.75 | 1.00 |
| dev(earlier) | count_sev | 0 | 6 | 24 | 21 | 0 | 0 | 0.88 | 1.00 |
| dev(earlier) | detail | 0 | 6 | 24 | 24 | 0 | 0 | 1.00 | 1.00 |
| dev(earlier) | explain_incident | 1 | 5 | 18 | 2 | 0 | 0 | 0.11 | 0.20 |
| dev(earlier) | explain_latest | 1 | 5 | 20 | 0 | 0 | 0 | 0.00 | 0.00 |
| dev(earlier) | faults | 0 | 6 | 24 | 3 | 0 | 0 | 0.12 | 0.17 |
| dev(earlier) | faulty_explain | 1 | 6 | 24 | 2 | 0 | 4 | 0.08 | 0.33 |
| dev(earlier) | faulty_list | 0 | 6 | 24 | 1 | 0 | 0 | 0.04 | 0.17 |
| dev(earlier) | find | 0 | 6 | 24 | 10 | 0 | 0 | 0.42 | 0.50 |
| dev(earlier) | fog_knowledge | 0 | 5 | 20 | 11 | 0 | 0 | 0.55 | 0.60 |
| dev(earlier) | followup_detail | 1 | 5 | 19 | 3 | 0 | 1 | 0.16 | 0.40 |
| dev(earlier) | followup_metric | 1 | 5 | 20 | 12 | 6 | 1 | 0.60 | 1.00 |
| dev(earlier) | followup_nocall | 1 | 5 | 18 | 7 | 0 | 1 | 0.39 | 1.00 |
| dev(earlier) | followup_period | 1 | 5 | 20 | 4 | 4 | 2 | 0.20 | 0.80 |
| dev(earlier) | followup_place | 1 | 5 | 19 | 12 | 5 | 2 | 0.63 | 1.00 |
| dev(earlier) | followup_whatif | 1 | 5 | 17 | 4 | 0 | 2 | 0.24 | 0.40 |
| dev(earlier) | followup_worst | 1 | 5 | 20 | 2 | 0 | 0 | 0.10 | 0.40 |
| dev(earlier) | group | 0 | 6 | 24 | 15 | 0 | 0 | 0.62 | 0.83 |
| dev(earlier) | health | 0 | 6 | 24 | 1 | 0 | 0 | 0.04 | 0.17 |
| dev(earlier) | history | 0 | 6 | 24 | 19 | 0 | 0 | 0.79 | 1.00 |
| dev(earlier) | history_old | 0 | 5 | 20 | 1 | 0 | 0 | 0.05 | 0.20 |
| dev(earlier) | injected | 0 | 6 | 24 | 0 | 0 | 0 | 0.00 | 0.00 |
| dev(earlier) | levels_domain | 0 | 6 | 24 | 10 | 0 | 0 | 0.42 | 0.67 |
| dev(earlier) | levels_metric | 0 | 6 | 24 | 13 | 0 | 0 | 0.54 | 0.83 |
| dev(earlier) | levels_place | 0 | 6 | 24 | 14 | 0 | 0 | 0.58 | 0.83 |
| dev(earlier) | limits | 0 | 6 | 24 | 15 | 0 | 0 | 0.62 | 0.83 |
| dev(earlier) | multistep | 1 | 6 | 20 | 6 | 0 | 0 | 0.30 | 0.50 |
| dev(earlier) | offline_docs | 0 | 6 | 24 | 12 | 0 | 0 | 0.50 | 0.50 |
| dev(earlier) | offtopic | 0 | 6 | 24 | 15 | 0 | 0 | 0.62 | 0.83 |
| dev(earlier) | old_data | 0 | 6 | 24 | 3 | 0 | 0 | 0.12 | 0.33 |
| dev(earlier) | open_all | 0 | 6 | 24 | 0 | 0 | 0 | 0.00 | 0.00 |
| dev(earlier) | open_domain | 0 | 6 | 24 | 21 | 0 | 0 | 0.88 | 1.00 |
| dev(earlier) | overview | 1 | 5 | 20 | 1 | 0 | 4 | 0.05 | 0.20 |
| dev(earlier) | rank_clean | 0 | 6 | 24 | 13 | 0 | 0 | 0.54 | 0.83 |
| dev(earlier) | rank_highest | 0 | 6 | 24 | 13 | 0 | 0 | 0.54 | 0.67 |
| dev(earlier) | rank_lowest | 0 | 6 | 24 | 8 | 0 | 0 | 0.33 | 0.67 |
| dev(earlier) | rank_place | 0 | 6 | 24 | 15 | 0 | 0 | 0.62 | 1.00 |
| dev(earlier) | rank_spike | 0 | 6 | 24 | 11 | 0 | 0 | 0.46 | 0.83 |
| dev(earlier) | recent | 0 | 6 | 24 | 8 | 0 | 0 | 0.33 | 0.83 |
| dev(earlier) | recent_filtered | 0 | 6 | 24 | 1 | 0 | 0 | 0.04 | 0.17 |
| dev(earlier) | recommend | 1 | 5 | 18 | 3 | 1 | 2 | 0.17 | 0.40 |
| dev(earlier) | refuse_close | 0 | 5 | 20 | 17 | 0 | 0 | 0.85 | 1.00 |
| dev(earlier) | refuse_personal | 0 | 5 | 20 | 20 | 0 | 0 | 1.00 | 1.00 |
| dev(earlier) | trend | 0 | 5 | 20 | 0 | 0 | 0 | 0.00 | 0.00 |
| dev(earlier) | unanswerable | 0 | 5 | 20 | 4 | 0 | 0 | 0.20 | 0.40 |
| dev(earlier) | whatif_ac | 1 | 5 | 20 | 1 | 0 | 4 | 0.05 | 0.20 |
| dev(earlier) | whatif_occ | 1 | 5 | 18 | 3 | 0 | 0 | 0.17 | 0.40 |
| dev(earlier) | whatif_temp | 1 | 5 | 18 | 7 | 0 | 5 | 0.39 | 1.00 |
| train | compare_buildings | 1 | 26 | 90 | 31 | 0 | 25 | 0.34 | 0.73 |
| train | compare_days | 1 | 26 | 89 | 35 | 7 | 24 | 0.39 | 0.81 |
| train | compare_levels | 1 | 26 | 82 | 38 | 0 | 2 | 0.46 | 0.81 |
| train | compare_periods | 1 | 26 | 72 | 45 | 0 | 0 | 0.62 | 0.85 |
| train | explain_incident | 1 | 26 | 99 | 16 | 0 | 0 | 0.16 | 0.38 |
| train | explain_latest | 1 | 26 | 104 | 1 | 0 | 1 | 0.01 | 0.04 |
| train | faulty_explain | 1 | 17 | 68 | 0 | 0 | 12 | 0.00 | 0.00 |
| train | followup_detail | 1 | 27 | 106 | 9 | 0 | 3 | 0.08 | 0.26 |
| train | followup_metric | 1 | 26 | 71 | 47 | 0 | 0 | 0.66 | 0.92 |
| train | followup_nocall | 1 | 26 | 88 | 38 | 0 | 5 | 0.43 | 0.88 |
| train | followup_period | 1 | 26 | 80 | 51 | 0 | 0 | 0.64 | 0.85 |
| train | followup_place | 1 | 26 | 57 | 52 | 0 | 0 | 0.91 | 1.00 |
| train | followup_whatif | 1 | 26 | 92 | 30 | 0 | 7 | 0.33 | 0.73 |
| train | followup_worst | 1 | 26 | 103 | 17 | 0 | 0 | 0.17 | 0.46 |
| train | multistep | 1 | 26 | 96 | 8 | 0 | 1 | 0.08 | 0.15 |
| train | overview | 1 | 12 | 47 | 7 | 0 | 12 | 0.15 | 0.42 |
| train | recommend | 1 | 26 | 104 | 0 | 0 | 2 | 0.00 | 0.00 |
| train | whatif_ac | 1 | 25 | 97 | 15 | 1 | 12 | 0.15 | 0.44 |
| train | whatif_occ | 1 | 26 | 104 | 7 | 0 | 15 | 0.07 | 0.23 |
| train | whatif_temp | 1 | 26 | 96 | 18 | 0 | 35 | 0.19 | 0.38 |
| train(earlier) | actions | 0 | 2 | 8 | 3 | 0 | 0 | 0.38 | 0.50 |
| train(earlier) | actuation | 0 | 2 | 8 | 7 | 0 | 0 | 0.88 | 1.00 |
| train(earlier) | compare_buildings | 1 | 43 | 133 | 59 | 1 | 31 | 0.44 | 0.72 |
| train(earlier) | compare_days | 1 | 43 | 141 | 49 | 2 | 34 | 0.35 | 0.63 |
| train(earlier) | compare_levels | 1 | 43 | 137 | 64 | 0 | 9 | 0.47 | 0.86 |
| train(earlier) | compare_periods | 1 | 44 | 131 | 69 | 3 | 0 | 0.53 | 0.84 |
| train(earlier) | count_metric | 0 | 2 | 8 | 4 | 0 | 0 | 0.50 | 0.50 |
| train(earlier) | count_sev | 0 | 1 | 4 | 1 | 0 | 0 | 0.25 | 1.00 |
| train(earlier) | detail | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | explain_incident | 1 | 44 | 167 | 19 | 0 | 0 | 0.11 | 0.30 |
| train(earlier) | explain_latest | 1 | 44 | 176 | 2 | 0 | 1 | 0.01 | 0.05 |
| train(earlier) | faults | 0 | 2 | 8 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | faulty_explain | 1 | 44 | 175 | 5 | 1 | 49 | 0.03 | 0.09 |
| train(earlier) | faulty_list | 0 | 2 | 8 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | find | 0 | 2 | 8 | 2 | 0 | 0 | 0.25 | 0.50 |
| train(earlier) | fog_knowledge | 0 | 2 | 8 | 3 | 0 | 0 | 0.38 | 0.50 |
| train(earlier) | followup_detail | 1 | 43 | 161 | 29 | 0 | 0 | 0.18 | 0.44 |
| train(earlier) | followup_metric | 1 | 43 | 106 | 81 | 0 | 0 | 0.76 | 0.98 |
| train(earlier) | followup_nocall | 1 | 44 | 147 | 61 | 2 | 9 | 0.41 | 0.82 |
| train(earlier) | followup_period | 1 | 44 | 120 | 85 | 0 | 0 | 0.71 | 0.93 |
| train(earlier) | followup_place | 1 | 44 | 107 | 81 | 3 | 2 | 0.76 | 0.93 |
| train(earlier) | followup_whatif | 1 | 43 | 148 | 50 | 2 | 12 | 0.34 | 0.74 |
| train(earlier) | followup_worst | 1 | 44 | 164 | 40 | 0 | 3 | 0.24 | 0.64 |
| train(earlier) | group | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | health | 0 | 2 | 8 | 2 | 0 | 0 | 0.25 | 1.00 |
| train(earlier) | history | 0 | 1 | 4 | 2 | 0 | 0 | 0.50 | 1.00 |
| train(earlier) | history_old | 0 | 2 | 8 | 3 | 0 | 0 | 0.38 | 1.00 |
| train(earlier) | injected | 0 | 2 | 8 | 4 | 0 | 0 | 0.50 | 0.50 |
| train(earlier) | levels_domain | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | levels_metric | 0 | 2 | 8 | 6 | 0 | 0 | 0.75 | 1.00 |
| train(earlier) | levels_place | 0 | 2 | 8 | 3 | 0 | 0 | 0.38 | 0.50 |
| train(earlier) | limits | 0 | 2 | 8 | 4 | 0 | 0 | 0.50 | 0.50 |
| train(earlier) | multistep | 1 | 43 | 154 | 20 | 0 | 0 | 0.13 | 0.23 |
| train(earlier) | offline_docs | 0 | 2 | 8 | 7 | 0 | 0 | 0.88 | 1.00 |
| train(earlier) | offtopic | 0 | 2 | 8 | 8 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | old_data | 0 | 2 | 8 | 3 | 0 | 0 | 0.38 | 0.50 |
| train(earlier) | open_all | 0 | 2 | 8 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | open_domain | 0 | 2 | 8 | 8 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | overview | 1 | 43 | 170 | 16 | 0 | 44 | 0.09 | 0.28 |
| train(earlier) | rank_clean | 0 | 2 | 8 | 7 | 0 | 0 | 0.88 | 1.00 |
| train(earlier) | rank_highest | 0 | 2 | 8 | 8 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | rank_lowest | 0 | 2 | 8 | 5 | 0 | 0 | 0.62 | 1.00 |
| train(earlier) | rank_place | 0 | 2 | 8 | 7 | 0 | 0 | 0.88 | 1.00 |
| train(earlier) | rank_spike | 0 | 2 | 8 | 5 | 0 | 0 | 0.62 | 1.00 |
| train(earlier) | recent | 0 | 2 | 8 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | recent_filtered | 0 | 2 | 8 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | recommend | 1 | 44 | 176 | 6 | 0 | 10 | 0.03 | 0.11 |
| train(earlier) | refuse_close | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train(earlier) | refuse_personal | 0 | 2 | 8 | 1 | 0 | 0 | 0.12 | 0.50 |
| train(earlier) | trend | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train(earlier) | unanswerable | 0 | 2 | 8 | 1 | 0 | 0 | 0.12 | 0.50 |
| train(earlier) | whatif_ac | 1 | 44 | 170 | 24 | 0 | 13 | 0.14 | 0.39 |
| train(earlier) | whatif_occ | 1 | 43 | 160 | 27 | 1 | 12 | 0.17 | 0.42 |
| train(earlier) | whatif_temp | 1 | 44 | 159 | 30 | 0 | 68 | 0.19 | 0.41 |
| dev(earlier) | ALL | | 300 | 1171 | 456 | 22 | 44 | 0.389 | 0.607 |
| train | ALL | | 497 | 1745 | 465 | 8 | 156 | 0.266 | 0.529 |
| train(earlier) | ALL | | 932 | 3246 | 933 | 15 | 297 | 0.287 | 0.546 |

(inline verify_chat; selection/final report: select_distill.py. Stop cleanly: create STOP in this folder.)
