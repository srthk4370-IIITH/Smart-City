# Reasoner big top-up: frozen gate (p2 vs new)

Scores only: no PASS / auto-deploy (owner decides together). Rows are few per sub-slice (1 row = 1/n), so deltas there are anecdotes; the 4 main slices are the evidence.

candidate adapter: /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best/ckpt_best_0242
candidate GGUF (not deployed): /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_big_q4_0.gguf

## report_all (n=40; p2 missing 0, new missing 0)

| metric | p2 | new | delta |
|---|---|---|---|
| valid | 0.975 | 1.000 | +0.025 |
| sev | 0.825 | 0.800 | -0.025 |
| hyg | 0.950 | 0.975 | +0.025 |
| ok | 0.825 | 0.775 | -0.050 |

| sub-slice | n | p2 ok | new ok | delta |
|---|---|---|---|---|
| dev_inc | 5 | 0.80 | 0.60 | -0.20 |
| test_campus_inc | 14 | 0.79 | 0.86 | +0.07 |
| test_real_agent | 6 | 0.83 | 0.50 | -0.33 |
| test_taxonomy | 5 | 0.80 | 0.80 | +0.00 |
| test_unseen_layout | 5 | 1.00 | 0.80 | -0.20 |
| test_unseen_metric | 5 | 0.80 | 1.00 | +0.20 |

## new_family (n=30; p2 missing 0, new missing 0)

| metric | p2 | new | delta |
|---|---|---|---|
| valid | 0.967 | 1.000 | +0.033 |
| sev | 0.700 | 0.700 | +0.000 |
| hyg | 0.800 | 0.967 | +0.167 |
| ok | 0.667 | 0.700 | +0.033 |

| sub-slice | n | p2 ok | new ok | delta |
|---|---|---|---|---|
| big_benign | 2 | 1.00 | 1.00 | +0.00 |
| big_co2 | 6 | 0.83 | 0.67 | -0.17 |
| big_pm | 5 | 0.60 | 0.60 | +0.00 |
| big_temp | 5 | 0.80 | 0.80 | +0.00 |
| dev_p2:batch | 2 | 1.00 | 1.00 | +0.00 |
| dev_p2:batch_late | 2 | 1.00 | 1.00 | +0.00 |
| dev_p2:fault_2nd | 1 | 0.00 | 1.00 | +1.00 |
| dev_p2:flat_alone | 1 | 0.00 | 0.00 | +0.00 |
| dev_p2:flat_mem | 1 | 0.00 | 0.00 | +0.00 |
| dev_p2:plateau_real | 1 | 0.00 | 1.00 | +1.00 |
| dev_p2:step_real | 1 | 0.00 | 0.00 | +0.00 |
| dev_p2:step_real_mem | 1 | 0.00 | 0.00 | +0.00 |
| p2_batch_late | 2 | 1.00 | 1.00 | +0.00 |

## chat_en (n=39; p2 missing 0, new missing 0)

| metric | p2 | new | delta |
|---|---|---|---|
| nonempty | 0.974 | 0.949 | -0.026 |
| calls | 0.846 | 0.872 | +0.026 |
| args | 0.564 | 0.641 | +0.077 |
| grounded | 1.000 | 1.000 | +0.000 |
| short | 1.000 | 1.000 | +0.000 |
| fmt | 0.949 | 0.974 | +0.026 |
| extra | 0.974 | 0.974 | +0.000 |
| ok | 0.513 | 0.615 | +0.103 |

| sub-slice | n | p2 ok | new ok | delta |
|---|---|---|---|---|
| find_empty | 1 | 1.00 | 0.00 | -1.00 |
| fmt_one_word | 1 | 0.00 | 0.00 | +0.00 |
| fmt_shorter | 1 | 0.00 | 1.00 | +1.00 |
| fmt_simple | 1 | 1.00 | 1.00 | +0.00 |
| followup_period | 1 | 1.00 | 1.00 | +0.00 |
| nocall | 2 | 0.50 | 0.50 | +0.00 |
| short_status | 3 | 0.00 | 0.33 | +0.33 |
| site_old | 25 | 0.56 | 0.64 | +0.08 |
| units | 2 | 1.00 | 1.00 | +0.00 |
| unknown_sensor | 2 | 0.00 | 0.50 | +0.50 |

## tool_chain (n=20; p2 missing 0, new missing 0)

| metric | p2 | new | delta |
|---|---|---|---|
| nonempty | 0.650 | 0.750 | +0.100 |
| calls | 0.400 | 0.600 | +0.200 |
| args | 0.350 | 0.400 | +0.050 |
| grounded | 1.000 | 1.000 | +0.000 |
| short | 1.000 | 1.000 | +0.000 |
| fmt | 1.000 | 1.000 | +0.000 |
| extra | 0.550 | 0.700 | +0.150 |
| ok | 0.250 | 0.400 | +0.150 |

| sub-slice | n | p2 ok | new ok | delta |
|---|---|---|---|---|
| cooccur | 3 | 0.00 | 0.00 | +0.00 |
| faulty_vs_empty | 3 | 0.00 | 0.00 | +0.00 |
| find_get | 3 | 0.33 | 0.00 | -0.33 |
| fog_trend | 2 | 1.00 | 1.00 | +0.00 |
| followup_domain | 1 | 0.00 | 1.00 | +1.00 |
| followup_severity | 1 | 1.00 | 1.00 | +0.00 |
| forecast | 2 | 0.50 | 1.00 | +0.50 |
| get_missing | 2 | 0.00 | 1.00 | +1.00 |
| rank_linked | 3 | 0.00 | 0.00 | +0.00 |

## Flags (informational)

FLAG: report_all ok dropped -0.050
FLAG: report_all/dev_inc ok dropped -0.20 (n=5)
FLAG: report_all/test_real_agent ok dropped -0.33 (n=6)
FLAG: report_all/test_unseen_layout ok dropped -0.20 (n=5)
FLAG: new_family/big_co2 ok dropped -0.17 (n=6)

RESULT: SCORES ONLY (deploy decided by the owner)
