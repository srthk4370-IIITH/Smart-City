# rsn_v3 laptop chat distillation: STATUS (FINAL)

- updated 2026-10-29 23:07:11, elapsed 0.13 h (paused 0.03 h), job distill_laptop_smoke, pid 16967
- records done this run 24 / 24 to do (260 rec/h); ETA 0.0 h
- generated tokens 16682 in 192 requests; aggregate 50.3 tok/s wall, per-request decode 16.2 tok/s; mean prompt tokens evaluated (not cached) 443
- GPU 69 C, 5697 MiB, 0% util; Windows free RAM 2886 MB; paused: no (4 pauses); server restarts 0
- stop: all records done; think compression: {'compressed_ok': 4}

| set | kind | hard | records | samples | pass | pass_long | forced | sample pass | question pass |
|---|---|---|---|---|---|---|---|---|---|
| train | actions | 0 | 1 | 2 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | compare_periods | 1 | 1 | 4 | 1 | 0 | 0 | 0.25 | 1.00 |
| train | count_metric | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | explain_incident | 1 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | explain_latest | 1 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | faults | 0 | 1 | 2 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | faulty_explain | 1 | 1 | 4 | 0 | 0 | 2 | 0.00 | 0.00 |
| train | faulty_list | 0 | 1 | 2 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | fog_knowledge | 0 | 1 | 2 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | followup_nocall | 1 | 1 | 3 | 2 | 0 | 0 | 0.67 | 1.00 |
| train | followup_place | 1 | 1 | 3 | 2 | 0 | 0 | 0.67 | 1.00 |
| train | followup_worst | 1 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | history_old | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | injected | 0 | 1 | 2 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | levels_metric | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | levels_place | 0 | 1 | 2 | 1 | 0 | 0 | 0.50 | 1.00 |
| train | limits | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | old_data | 0 | 1 | 2 | 1 | 0 | 0 | 0.50 | 1.00 |
| train | open_domain | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | rank_clean | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | rank_highest | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | rank_lowest | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | rank_spike | 0 | 1 | 2 | 2 | 0 | 0 | 1.00 | 1.00 |
| train | whatif_temp | 1 | 1 | 4 | 0 | 0 | 3 | 0.00 | 0.00 |
| train | ALL | | 24 | 62 | 25 | 0 | 5 | 0.403 | 0.583 |

(inline verify_chat; selection/final report: select_distill.py. Stop cleanly: create STOP in this folder.)
