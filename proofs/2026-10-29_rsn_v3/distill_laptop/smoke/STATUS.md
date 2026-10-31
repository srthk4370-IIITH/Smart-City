# rsn_v3 laptop chat distillation: STATUS (FINAL)

- updated 2026-10-29 18:54:10, elapsed 0.25 h (paused 0.15 h), job distill_laptop_smoke, pid 3512
- records done this run 20 / 20 to do (195 rec/h); ETA 0.0 h
- generated tokens 15000 in 214 requests; aggregate 40.7 tok/s wall, per-request decode 17.2 tok/s; mean prompt tokens evaluated (not cached) 378
- GPU 70 C, 5613 MiB, 0% util; Windows free RAM 2413 MB; paused: no (5 pauses); server restarts 1
- stop: all records done

| set | kind | hard | records | samples | pass | pass_long | forced | sample pass | question pass |
|---|---|---|---|---|---|---|---|---|---|
| train | actions | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | count_metric | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train | explain_incident | 1 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | explain_latest | 1 | 1 | 4 | 0 | 0 | 1 | 0.00 | 0.00 |
| train | faults | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | faulty_explain | 1 | 1 | 4 | 0 | 0 | 4 | 0.00 | 0.00 |
| train | fog_knowledge | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | followup_nocall | 1 | 1 | 4 | 2 | 0 | 1 | 0.50 | 1.00 |
| train | followup_place | 1 | 1 | 4 | 0 | 4 | 2 | 0.00 | 0.00 |
| train | followup_worst | 1 | 1 | 4 | 0 | 0 | 3 | 0.00 | 0.00 |
| train | history_old | 0 | 1 | 4 | 3 | 0 | 0 | 0.75 | 1.00 |
| train | injected | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | levels_place | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | limits | 0 | 1 | 4 | 1 | 0 | 0 | 0.25 | 1.00 |
| train | old_data | 0 | 1 | 4 | 0 | 0 | 0 | 0.00 | 0.00 |
| train | open_domain | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train | rank_clean | 0 | 1 | 4 | 3 | 0 | 0 | 0.75 | 1.00 |
| train | rank_highest | 0 | 1 | 4 | 4 | 0 | 0 | 1.00 | 1.00 |
| train | rank_lowest | 0 | 1 | 4 | 3 | 0 | 0 | 0.75 | 1.00 |
| train | whatif_temp | 1 | 1 | 4 | 0 | 0 | 4 | 0.00 | 0.00 |
| train | ALL | | 20 | 80 | 24 | 4 | 15 | 0.300 | 0.400 |

(inline verify_chat; selection/final report: select_distill.py. Stop cleanly: create STOP in this folder.)
