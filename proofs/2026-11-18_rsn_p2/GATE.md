RULE: PASS if weighted delta (r3 .35, r4 .35, new families .30) >= +0.02, no slice drop > 0.10, r4 and new-family severity drop <= 0.03, JSON validity >= 0.98

weighted delta -0.0044 (>=0.02 False); slice drops ok True; safety (r4, severity) ok True; JSON validity 0.984 ok True

# Reasoner part 2 gate (fine-tune best step 400 vs p2 best step 220)

| slice | ft best | p2 best | rule | ok |
|---|---|---|---|---|
| r3 slice (gen eval) | 0.9917 | 0.9917 | weighted | +0.000 |
| r4 incidents (gen eval) | 0.6134 | 0.6280 | weighted, safety | +0.015 |
| new families held-out, n=63 (severity + id hygiene) | 0.3968 | 0.3651 | weighted | -0.032 |

severity-only: ft 0.4286 p2 0.4127; hygiene: ft 0.6825 p2 0.7619

per family [n, sev ok, hygiene ok, both]: ft {"p2_batch": [8, 6, 7, 5], "p2_batch_late": [8, 2, 3, 2], "p2_fault_2nd": [8, 5, 7, 5], "p2_flat_alone": [8, 1, 4, 1], "p2_flat_mem": [8, 3, 3, 2], "p2_plateau_real": [8, 7, 8, 7], "p2_step_real": [8, 2, 7, 2], "p2_step_real_mem": [7, 1, 4, 1]}
 p2 {"p2_batch": [8, 6, 8, 6], "p2_batch_late": [8, 3, 8, 3], "p2_fault_2nd": [8, 5, 6, 4], "p2_flat_alone": [8, 0, 3, 0], "p2_flat_mem": [8, 2, 3, 1], "p2_plateau_real": [8, 6, 7, 6], "p2_step_real": [8, 2, 7, 2], "p2_step_real_mem": [7, 2, 6, 1]}

candidate GGUF: /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_p2_q4_0.gguf (not deployed)

RESULT: FAIL
