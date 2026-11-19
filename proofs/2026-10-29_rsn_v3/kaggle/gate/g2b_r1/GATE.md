# rsn_v3 gate: rsn_v3_g2b_r1 vs ft612 -> **FAIL**

Rule: RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); dev within 1 item; strict JSON parse, same items; chat dev v3 pass rate > rsn_v1.

| suite | metric | rsn_v3 | rsn_v1 | rule | ok |
|---|---|---|---|---|---|
| rwh | severity | 0.912 | 0.919 | >= | **NO** |
| rwh | label | 0.905 | 0.874 | >= | yes |
| rwh | check_recall | 0.865 | 0.848 | >= | yes |
| rwh | check_prec | 0.895 | 0.853 | >= | yes |
| rwh | req | 0.831 | 0.77 | >= | yes |
| rwh | schema_err | 0.095 | 0.081 | <= | **NO** |
| rwh2 | severity | 0.939 | 0.928 | >= | yes |
| rwh2 | label | 0.946 | 0.968 | >= | **NO** |
| rwh2 | check_recall | 0.776 | 0.675 | >= | yes |
| rwh2 | check_prec | 0.738 | 0.857 | >= | **NO** |
| rwh2 | req | 0.884 | 0.832 | >= | yes |
| rwh2 | schema_err | 0.102 | 0.056 | <= | **NO** |
| dev | severity | 0.923 | 0.923 | >= (1 item = 0.009) | yes |
| dev | label | 0.889 | 0.894 | >= (1 item = 0.009) | yes |
| dev | check_recall | 0.805 | 0.8 | >= (1 item = 0.024) | yes |
| dev | check_prec | 0.786 | 0.848 | >= (1 item = 0.024) | **NO** |
| dev | req | 0.863 | 0.798 | >= (1 item = 0.009) | yes |
| dev | schema_err | 0.103 | 0.038 | <= (1 item = 0.009) | **NO** |
| chatdev3 | pass_rate | 0.183 | 0.477 | > | **NO** |

rwh (n=150) with the one-bracket JSON repair (info): v3 {'severity': 0.912, 'label': 0.905, 'check_recall': 0.865, 'check_prec': 0.895, 'req': 0.831, 'schema_err': 0.095} / v1 {'severity': 0.919, 'label': 0.878, 'check_recall': 0.857, 'check_prec': 0.846, 'req': 0.777, 'schema_err': 0.088}

rwh2 (n=150) with the one-bracket JSON repair (info): v3 {'severity': 0.939, 'label': 0.946, 'check_recall': 0.776, 'check_prec': 0.738, 'req': 0.884, 'schema_err': 0.102} / v1 {'severity': 0.932, 'label': 0.946, 'check_recall': 0.783, 'check_prec': 0.863, 'req': 0.845, 'schema_err': 0.054}

dev (n=120) with the one-bracket JSON repair (info): v3 {'severity': 0.923, 'label': 0.889, 'check_recall': 0.805, 'check_prec': 0.786, 'req': 0.863, 'schema_err': 0.103} / v1 {'severity': 0.933, 'label': 0.908, 'check_recall': 0.837, 'check_prec': 0.735, 'req': 0.817, 'schema_err': 0.067}

## chat dev v3

| metric | rsn_v3 | rsn_v1 |
|---|---|---|
| n | 300 | 300 |
| pass_rate | 0.183 | 0.477 |
| calls_ok | 0.757 | 0.65 |
| facts_ok | 0.683 | 0.61 |
| grounded | 0.933 | 0.973 |
| refusal_ok | 0.773 | 0.864 |
| hard_think_mean | 55.4 | 0.0 |
| easy_think_nonempty | 0.98 | 0.0 |
| wall_s_mean | 5.99 | 4.82 |
| gen_tokens_mean | 232.4 | 99.0 |

rsn_v3 fail reasons: {'think_not_empty': 194, 'missing_fact': 124, 'missing_call': 70, 'extra_calls': 25, 'invented_num': 20, 'too_long': 12, 'no_final': 11, 'think_too_long': 8, 'unexpected_call': 5, 'no_refusal': 5, 'empty': 4, 'unit_mismatch': 3}

rsn_v1 fail reasons: {'missing_fact': 162, 'missing_call': 109, 'extra_calls': 9, 'invented_num': 8, 'unexpected_call': 8, 'empty': 3, 'unit_mismatch': 3, 'no_refusal': 3, 'no_final': 2, 'invented_time': 2}

## P0 regression (informational)

```
rsn_v3_g2b_r1 G1 False G2 FAIL R 0.756 T 0.814 U 0.697 S 0.733 total 0.757
ft612 G1 True G2 FAIL R 0.780 T 0.802 U 0.674 S 0.763 total 0.763
```
