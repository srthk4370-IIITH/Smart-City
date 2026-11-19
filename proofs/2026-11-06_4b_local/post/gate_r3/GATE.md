# 4B r3 gate: rsn_v3_4b_r3 vs ft612 (rsn_v1) -> **PASS**

Rule (as g2b_r2): RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); round-1 dev within 1 item; strict JSON parse, same items; chat dev v3 pass rate > rsn_v1. Chat dev v3: the 4B with the r3 app prompt (21-tool header, adaptive think); rsn_v1 = its cached result with its own trained mode (empty think). Q4_0 on the host GPU (host = board numerics).

| suite | metric | 4B r3 | rsn_v1 | rule | ok |
|---|---|---|---|---|---|
| rwh | severity | 0.947 | 0.919 | >= | yes |
| rwh | label | 0.96 | 0.874 | >= | yes |
| rwh | check_recall | 0.937 | 0.848 | >= | yes |
| rwh | check_prec | 0.974 | 0.853 | >= | yes |
| rwh | req | 0.88 | 0.77 | >= | yes |
| rwh | schema_err | 0.0 | 0.081 | <= | yes |
| rwh2 | severity | 0.993 | 0.928 | >= | yes |
| rwh2 | label | 1.0 | 0.968 | >= | yes |
| rwh2 | check_recall | 0.883 | 0.675 | >= | yes |
| rwh2 | check_prec | 0.982 | 0.857 | >= | yes |
| rwh2 | req | 0.927 | 0.832 | >= | yes |
| rwh2 | schema_err | 0.02 | 0.056 | <= | yes |
| dev | severity | 0.942 | 0.923 | >= (1 item = 0.008) | yes |
| dev | label | 0.942 | 0.894 | >= (1 item = 0.008) | yes |
| dev | check_recall | 0.86 | 0.8 | >= (1 item = 0.023) | yes |
| dev | check_prec | 0.927 | 0.848 | >= (1 item = 0.024) | yes |
| dev | req | 0.925 | 0.798 | >= (1 item = 0.008) | yes |
| dev | schema_err | 0.008 | 0.038 | <= (1 item = 0.008) | yes |
| chatdev3 | pass_rate | 0.813 | 0.477 | > | yes |

rwh (n=150) with the one-bracket JSON repair (info): 4B {'severity': 0.947, 'label': 0.96, 'check_recall': 0.937, 'check_prec': 0.974, 'req': 0.88, 'schema_err': 0.0} / v1 {'severity': 0.919, 'label': 0.878, 'check_recall': 0.857, 'check_prec': 0.846, 'req': 0.777, 'schema_err': 0.088}

rwh2 (n=150) with the one-bracket JSON repair (info): 4B {'severity': 0.993, 'label': 1.0, 'check_recall': 0.883, 'check_prec': 0.982, 'req': 0.927, 'schema_err': 0.02} / v1 {'severity': 0.932, 'label': 0.946, 'check_recall': 0.783, 'check_prec': 0.863, 'req': 0.845, 'schema_err': 0.054}

dev (n=120) with the one-bracket JSON repair (info): 4B {'severity': 0.942, 'label': 0.942, 'check_recall': 0.86, 'check_prec': 0.927, 'req': 0.925, 'schema_err': 0.008} / v1 {'severity': 0.933, 'label': 0.908, 'check_recall': 0.837, 'check_prec': 0.735, 'req': 0.817, 'schema_err': 0.067}

## chat dev v3 (300)

| metric | 4B r3 (r3 prompt) | rsn_v1 |
|---|---|---|
| n | 300 | 300 |
| pass_rate | 0.813 | 0.477 |
| calls_ok | 0.89 | 0.65 |
| facts_ok | 0.847 | 0.61 |
| grounded | 0.973 | 0.973 |
| refusal_ok | 0.955 | 0.864 |
| hard_think_mean | 33.8 | 0.0 |
| easy_think_nonempty | 0.045 | 0.0 |
| wall_s_mean | 3.5 | 4.82 |
| gen_tokens_mean | 127.0 | 99.0 |

4B fail reasons: {'missing_fact': 56, 'missing_call': 38, 'extra_calls': 11, 'think_not_empty': 9, 'invented_num': 8, 'no_final': 7, 'think_too_long': 2, 'no_refusal': 1}

rsn_v1 fail reasons: {'missing_fact': 162, 'missing_call': 109, 'extra_calls': 9, 'invented_num': 8, 'unexpected_call': 8, 'empty': 3, 'unit_mismatch': 3, 'no_refusal': 3, 'no_final': 2, 'invented_time': 2}

## Informational (not gating)

### chat_test_r3 (held-out r3 test, r3 verifier; rsn_v1 never saw the r3 header/fog tools: out of distribution)

| slice | 4B r3 | rsn_v1 (OOD) |
|---|---|---|
| pass_rate | 0.744 | 0.212 |
| n | 983 | 983 |
| fog=offline | 341/493 = 0.692 | 103/493 = 0.209 |
| fog=online | 354/421 = 0.841 | 101/421 = 0.240 |
| fog=timeout | 36/69 = 0.522 | 4/69 = 0.058 |
| group=new | 485/700 = 0.693 | 93/700 = 0.133 |
| group=old | 246/283 = 0.869 | 115/283 = 0.406 |
| hinglish=False | 643/867 = 0.742 | 185/867 = 0.213 |
| hinglish=True | 88/116 = 0.759 | 23/116 = 0.198 |
| hard=False | 430/556 = 0.773 | 163/556 = 0.293 |
| hard=True | 301/427 = 0.705 | 45/427 = 0.105 |

4B per kind: {'actions': '9/9', 'actuation': '4/4', 'compare_buildings': '8/8', 'compare_days': '8/8', 'compare_levels': '7/8', 'compare_tool': '29/35', 'cooccur': '22/35', 'count_metric': '9/9', 'count_sev': '9/9', 'detail': '9/9', 'explain_incident': '5/8', 'explain_latest': '2/7', 'faults': '5/5', 'faulty_list': '7/7', 'find': '8/8', 'fog_drop': '22/35', 'fog_find_old': '9/35', 'fog_old_detail': '22/35', 'fog_resolve': '25/35', 'fog_sensor_monthly': '28/35', 'fog_status': '26/35', 'fog_text': '14/35', 'fog_trend': '31/35', 'followup_detail': '7/7', 'followup_metric': '5/5', 'followup_nocall': '3/3', 'followup_period': '3/3', 'followup_place': '5/5', 'followup_whatif': '5/5', 'followup_worst': '2/4', 'fu_cooccur': '4/35', 'fu_fog_detail': '32/35', 'fu_fog_period': '30/35', 'fu_fog_status': '16/35', 'group': '8/8', 'health': '3/3', 'history': '9/9', 'inject_fog': '25/35', 'injected': '3/3', 'knowledge': '34/35', 'levels_domain': '4/4', 'levels_metric': '6/6', 'levels_place': '4/4', 'limits': '3/3', 'multistep': '2/2', 'offtopic': '2/2', 'old_count': '35/35', 'open_all': '3/3', 'open_domain': '1/3', 'overview': '1/2', 'rank_clean': '4/8', 'rank_highest': '8/8', 'rank_lowest': '8/8', 'rank_place': '8/8', 'rank_spike': '7/8', 'recent': '2/2', 'recent_filtered': '3/7', 'recent_vs_fog': '23/35', 'recommend': '3/5', 'recurring': '23/35', 'refuse_close': '7/7', 'refuse_fog': '35/35', 'refuse_personal': '4/4', 'trend': '4/8', 'unanswerable': '2/6', 'whatif_ac': '3/7', 'whatif_occ': '7/7', 'whatif_temp': '7/7'}

4B fail reasons: {'missing_fact': 276, 'missing_call': 110, 'think_not_empty': 73, 'extra_calls': 12, 'think_too_long': 9, 'unit_mismatch': 5, 'invented_num': 2, 'no_final': 1}

### incidents_test_r2 per slice (gold = the row's report; strict JSON)

| slice | model | n | parsed | severity | label | check_recall | check_prec | req | schema_err |
|---|---|---|---|---|---|---|---|---|---|
| all | 4B r3 | 1364 | 1.0 | 0.944 | 0.953 | 0.861 | 0.932 | 0.89 | 0.003 |
| all | rsn_v1 | 1364 | 0.86 | 0.694 | 0.714 | 0.364 | 0.545 | 0.633 | 0.071 |
| gen_heldout | 4B r3 | 640 | 1.0 | 0.941 | 0.953 | 0.775 | 0.982 | 0.877 | 0.005 |
| gen_heldout | rsn_v1 | 640 | 0.859 | 0.867 | 0.882 | 0.536 | 0.767 | 0.795 | 0.04 |
| heat | 4B r3 | 284 | 1.0 | 0.873 | 0.884 | 0.844 | 0.805 | 0.761 | 0.0 |
| heat | rsn_v1 | 284 | 0.852 | 0.541 | 0.554 | 0.378 | 0.416 | 0.529 | 0.029 |
| targeted | 4B r3 | 280 | 1.0 | 0.993 | 0.996 | 0.993 | 0.964 | 0.993 | 0.0 |
| targeted | rsn_v1 | 280 | 0.871 | 0.537 | 0.557 | 0.174 | 0.386 | 0.443 | 0.135 |
| targeted_novel_names | 4B r3 | 160 | 1.0 | 1.0 | 1.0 | 0.987 | 0.914 | 0.994 | 0.006 |
| targeted_novel_names | rsn_v1 | 160 | 0.856 | 0.547 | 0.599 | 0.159 | 0.387 | 0.511 | 0.153 |

### P0 regression

```
rsn_v3_4b_r3 G1 True G2 FAIL R 0.877 T 0.901 U 0.731 S 0.878 total 0.854
ft612 G1 True G2 FAIL R 0.780 T 0.802 U 0.674 S 0.763 total 0.763
```
