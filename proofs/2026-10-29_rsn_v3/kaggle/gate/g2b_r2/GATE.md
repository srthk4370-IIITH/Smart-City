# rsn_v3 gate: rsn_v3_g2b_r2 vs ft612 -> **FAIL**

Rule: RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); dev within 1 item; strict JSON parse, same items; chat dev v3 pass rate > rsn_v1.

| suite | metric | rsn_v3 | rsn_v1 | rule | ok |
|---|---|---|---|---|---|
| rwh | severity | 0.793 | 0.919 | >= | **NO** |
| rwh | label | 0.907 | 0.874 | >= | yes |
| rwh | check_recall | 0.405 | 0.848 | >= | **NO** |
| rwh | check_prec | 0.961 | 0.853 | >= | yes |
| rwh | req | 0.867 | 0.77 | >= | yes |
| rwh | schema_err | 0.147 | 0.081 | <= | **NO** |
| rwh2 | severity | 0.793 | 0.928 | >= | **NO** |
| rwh2 | label | 0.92 | 0.968 | >= | **NO** |
| rwh2 | check_recall | 0.467 | 0.675 | >= | **NO** |
| rwh2 | check_prec | 0.903 | 0.857 | >= | yes |
| rwh2 | req | 0.88 | 0.832 | >= | yes |
| rwh2 | schema_err | 0.113 | 0.056 | <= | **NO** |
| dev | severity | 0.833 | 0.923 | >= (1 item = 0.008) | **NO** |
| dev | label | 0.833 | 0.894 | >= (1 item = 0.008) | **NO** |
| dev | check_recall | 0.419 | 0.8 | >= (1 item = 0.023) | **NO** |
| dev | check_prec | 0.9 | 0.848 | >= (1 item = 0.050) | yes |
| dev | req | 0.875 | 0.798 | >= (1 item = 0.008) | yes |
| dev | schema_err | 0.05 | 0.038 | <= (1 item = 0.008) | **NO** |
| chatdev3 | pass_rate | 0.737 | 0.477 | > | yes |

rwh (n=150) with the one-bracket JSON repair (info): v3 {'severity': 0.793, 'label': 0.907, 'check_recall': 0.405, 'check_prec': 0.961, 'req': 0.867, 'schema_err': 0.147} / v1 {'severity': 0.919, 'label': 0.878, 'check_recall': 0.857, 'check_prec': 0.846, 'req': 0.777, 'schema_err': 0.088}

rwh2 (n=150) with the one-bracket JSON repair (info): v3 {'severity': 0.793, 'label': 0.92, 'check_recall': 0.467, 'check_prec': 0.903, 'req': 0.88, 'schema_err': 0.113} / v1 {'severity': 0.932, 'label': 0.946, 'check_recall': 0.783, 'check_prec': 0.863, 'req': 0.845, 'schema_err': 0.054}

dev (n=120) with the one-bracket JSON repair (info): v3 {'severity': 0.833, 'label': 0.833, 'check_recall': 0.419, 'check_prec': 0.9, 'req': 0.875, 'schema_err': 0.05} / v1 {'severity': 0.933, 'label': 0.908, 'check_recall': 0.837, 'check_prec': 0.735, 'req': 0.817, 'schema_err': 0.067}

## chat dev v3

| metric | rsn_v3 | rsn_v1 |
|---|---|---|
| n | 300 | 300 |
| pass_rate | 0.737 | 0.477 |
| calls_ok | 0.827 | 0.65 |
| facts_ok | 0.79 | 0.61 |
| grounded | 0.983 | 0.973 |
| refusal_ok | 0.909 | 0.864 |
| hard_think_mean | 12.5 | 0.0 |
| easy_think_nonempty | 0.0 | 0.0 |
| wall_s_mean | 2.6 | 4.82 |
| gen_tokens_mean | 117.3 | 99.0 |

rsn_v3 fail reasons: {'missing_fact': 86, 'missing_call': 54, 'extra_calls': 14, 'no_final': 7, 'invented_num': 5, 'unit_mismatch': 2, 'no_refusal': 2, 'think_too_long': 1}

rsn_v1 fail reasons: {'missing_fact': 162, 'missing_call': 109, 'extra_calls': 9, 'invented_num': 8, 'unexpected_call': 8, 'empty': 3, 'unit_mismatch': 3, 'no_refusal': 3, 'no_final': 2, 'invented_time': 2}

## P0 regression (informational)

```
rsn_v3_g2b_r2 G1 True G2 FAIL R 0.767 T 0.820 U 0.692 S 0.762 total 0.765
ft612 G1 True G2 FAIL R 0.780 T 0.802 U 0.674 S 0.763 total 0.763
```
