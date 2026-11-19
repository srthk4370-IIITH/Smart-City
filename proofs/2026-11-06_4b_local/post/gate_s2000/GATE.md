# 4B r3 gate: rsn_v3_4b_s2000 vs ft612 (rsn_v1) -> **PASS**

Rule (as g2b_r2): RWH and RWH-2 every report metric >= rsn_v1 (schema_err <=); round-1 dev within 1 item; strict JSON parse, same items; chat dev v3 pass rate > rsn_v1. Chat dev v3: the 4B with the r3 app prompt (21-tool header, adaptive think); rsn_v1 = its cached result with its own trained mode (empty think). Q4_0 on the host GPU (host = board numerics).

| suite | metric | 4B r3 | rsn_v1 | rule | ok |
|---|---|---|---|---|---|
| rwh | severity | 0.953 | 0.919 | >= | yes |
| rwh | label | 0.973 | 0.874 | >= | yes |
| rwh | check_recall | 0.924 | 0.848 | >= | yes |
| rwh | check_prec | 0.967 | 0.853 | >= | yes |
| rwh | req | 0.893 | 0.77 | >= | yes |
| rwh | schema_err | 0.007 | 0.081 | <= | yes |
| rwh2 | severity | 0.98 | 0.928 | >= | yes |
| rwh2 | label | 0.973 | 0.968 | >= | yes |
| rwh2 | check_recall | 0.917 | 0.675 | >= | yes |
| rwh2 | check_prec | 0.944 | 0.857 | >= | yes |
| rwh2 | req | 0.933 | 0.832 | >= | yes |
| rwh2 | schema_err | 0.027 | 0.056 | <= | yes |
| dev | severity | 0.917 | 0.923 | >= (1 item = 0.008) | yes |
| dev | label | 0.933 | 0.894 | >= (1 item = 0.008) | yes |
| dev | check_recall | 0.86 | 0.8 | >= (1 item = 0.023) | yes |
| dev | check_prec | 0.927 | 0.848 | >= (1 item = 0.024) | yes |
| dev | req | 0.9 | 0.798 | >= (1 item = 0.008) | yes |
| dev | schema_err | 0.008 | 0.038 | <= (1 item = 0.008) | yes |
| chatdev3 | pass_rate | 0.807 | 0.477 | > | yes |

rwh (n=150) with the one-bracket JSON repair (info): 4B {'severity': 0.953, 'label': 0.973, 'check_recall': 0.924, 'check_prec': 0.967, 'req': 0.893, 'schema_err': 0.007} / v1 {'severity': 0.919, 'label': 0.878, 'check_recall': 0.857, 'check_prec': 0.846, 'req': 0.777, 'schema_err': 0.088}

rwh2 (n=150) with the one-bracket JSON repair (info): 4B {'severity': 0.98, 'label': 0.973, 'check_recall': 0.917, 'check_prec': 0.944, 'req': 0.933, 'schema_err': 0.027} / v1 {'severity': 0.932, 'label': 0.946, 'check_recall': 0.783, 'check_prec': 0.863, 'req': 0.845, 'schema_err': 0.054}

dev (n=120) with the one-bracket JSON repair (info): 4B {'severity': 0.917, 'label': 0.933, 'check_recall': 0.86, 'check_prec': 0.927, 'req': 0.9, 'schema_err': 0.008} / v1 {'severity': 0.933, 'label': 0.908, 'check_recall': 0.837, 'check_prec': 0.735, 'req': 0.817, 'schema_err': 0.067}

## chat dev v3 (300)

| metric | 4B r3 (r3 prompt) | rsn_v1 |
|---|---|---|
| n | 300 | 300 |
| pass_rate | 0.807 | 0.477 |
| calls_ok | 0.88 | 0.65 |
| facts_ok | 0.853 | 0.61 |
| grounded | 0.987 | 0.973 |
| refusal_ok | 1.0 | 0.864 |
| hard_think_mean | 35.1 | 0.0 |
| easy_think_nonempty | 0.096 | 0.0 |
| wall_s_mean | 4.3 | 4.82 |
| gen_tokens_mean | 131.8 | 99.0 |

4B fail reasons: {'missing_fact': 67, 'missing_call': 43, 'think_not_empty': 19, 'extra_calls': 14, 'no_final': 12, 'invented_num': 4, 'unit_mismatch': 1}

rsn_v1 fail reasons: {'missing_fact': 162, 'missing_call': 109, 'extra_calls': 9, 'invented_num': 8, 'unexpected_call': 8, 'empty': 3, 'unit_mismatch': 3, 'no_refusal': 3, 'no_final': 2, 'invented_time': 2}

## Informational (not gating)

chat_test_r3: not run yet.

incidents_test_r2: not run yet.

### P0 regression

```
rsn_v3_4b_s2000 G1 False G2 FAIL R 0.886 T 0.850 U 0.710 S 0.874 total 0.840
ft612 G1 True G2 FAIL R 0.780 T 0.802 U 0.674 S 0.763 total 0.763
```
