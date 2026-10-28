# Placement study - agent pattern accuracy vs readings since onset (4 h window, QIDK NPU)

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 24% (49/208) | 42% (88/208) | 57% (119/208) | 67% (139/208) | 76% (158/208) | 88% (184/208) |
| spike | 67% (14/21) | 81% (17/21) | 76% (16/21) | 62% (13/21) | 76% (16/21) | 43% (9/21) |
| dip | 100% (21/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 95% (20/21) |
| step_increase | 24% (5/21) | 81% (17/21) | 95% (20/21) | 95% (20/21) | 100% (21/21) | 100% (21/21) |
| step_decrease | 26% (5/19) | 79% (15/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) |
| gradual_increase | 0% (0/21) | 0% (0/21) | 0% (0/21) | 5% (1/21) | 43% (9/21) | 86% (18/21) |
| gradual_decrease | 0% (0/21) | 29% (6/21) | 71% (15/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| exponential_increase | 14% (3/21) | 52% (11/21) | 81% (17/21) | 90% (19/21) | 95% (20/21) | 95% (20/21) |
| oscillation | 0% (0/21) | 0% (0/21) | 5% (1/21) | 0% (0/21) | 24% (5/21) | 100% (21/21) |
| flatline | 0% (0/21) | 0% (0/21) | 33% (7/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| erratic | 5% (1/21) | 5% (1/21) | 14% (3/21) | 19% (4/21) | 24% (5/21) | 67% (14/21) |

## Status accuracy

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 57% (118/208) | 62% (128/208) | 71% (148/208) | 74% (154/208) | 79% (164/208) | 86% (180/208) |
| spike | 52% (11/21) | 76% (16/21) | 67% (14/21) | 52% (11/21) | 62% (13/21) | 48% (10/21) |
| dip | 86% (18/21) | 86% (18/21) | 86% (18/21) | 86% (18/21) | 86% (18/21) | 86% (18/21) |
| step_increase | 81% (17/21) | 90% (19/21) | 95% (20/21) | 95% (20/21) | 95% (20/21) | 95% (20/21) |
| step_decrease | 95% (18/19) | 95% (18/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) |
| gradual_increase | 33% (7/21) | 29% (6/21) | 38% (8/21) | 43% (9/21) | 62% (13/21) | 90% (19/21) |
| gradual_decrease | 67% (14/21) | 76% (16/21) | 95% (20/21) | 95% (20/21) | 100% (21/21) | 95% (20/21) |
| exponential_increase | 62% (13/21) | 71% (15/21) | 76% (16/21) | 90% (19/21) | 90% (19/21) | 90% (19/21) |
| oscillation | 71% (15/21) | 71% (15/21) | 76% (16/21) | 57% (12/21) | 67% (14/21) | 100% (21/21) |
| flatline | 10% (2/21) | 0% (0/21) | 38% (8/21) | 95% (20/21) | 95% (20/21) | 86% (18/21) |
| erratic | 14% (3/21) | 24% (5/21) | 43% (9/21) | 29% (6/21) | 33% (7/21) | 76% (16/21) |

## Flagged at all (status not normal or pattern not stable)

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 73% (152/208) | 77% (160/208) | 84% (175/208) | 90% (187/208) | 89% (186/208) | 95% (198/208) |
| spike | 86% (18/21) | 95% (20/21) | 95% (20/21) | 81% (17/21) | 95% (20/21) | 76% (16/21) |
| dip | 100% (21/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 95% (20/21) |
| step_increase | 90% (19/21) | 95% (20/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| step_decrease | 90% (17/19) | 95% (18/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) | 100% (19/19) |
| gradual_increase | 71% (15/21) | 76% (16/21) | 95% (20/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| gradual_decrease | 52% (11/21) | 67% (14/21) | 90% (19/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| exponential_increase | 81% (17/21) | 90% (19/21) | 95% (20/21) | 95% (20/21) | 95% (20/21) | 95% (20/21) |
| oscillation | 81% (17/21) | 62% (13/21) | 43% (9/21) | 57% (12/21) | 33% (7/21) | 100% (21/21) |
| flatline | 29% (6/21) | 14% (3/21) | 43% (9/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| erratic | 52% (11/21) | 76% (16/21) | 81% (17/21) | 67% (14/21) | 71% (15/21) | 86% (18/21) |

## Rules (Mode 1) pattern accuracy

| pattern | d=4 (20 min) | d=8 (40 min) | d=12 (60 min) | d=18 (90 min) | d=24 (120 min) | d=36 (180 min) |
|---|---|---|---|---|---|---|
| ALL | 26% (53/208) | 33% (68/208) | 36% (75/208) | 60% (124/208) | 61% (126/208) | 57% (118/208) |
| spike | 90% (19/21) | 95% (20/21) | 86% (18/21) | 81% (17/21) | 76% (16/21) | 86% (18/21) |
| dip | 81% (17/21) | 81% (17/21) | 86% (18/21) | 86% (18/21) | 86% (18/21) | 86% (18/21) |
| step_increase | 10% (2/21) | 10% (2/21) | 10% (2/21) | 90% (19/21) | 19% (4/21) | 10% (2/21) |
| step_decrease | 0% (0/19) | 21% (4/19) | 58% (11/19) | 74% (14/19) | 84% (16/19) | 16% (3/19) |
| gradual_increase | 0% (0/21) | 0% (0/21) | 0% (0/21) | 5% (1/21) | 43% (9/21) | 52% (11/21) |
| gradual_decrease | 0% (0/21) | 14% (3/21) | 19% (4/21) | 52% (11/21) | 71% (15/21) | 71% (15/21) |
| exponential_increase | 71% (15/21) | 90% (19/21) | 90% (19/21) | 95% (20/21) | 95% (20/21) | 76% (16/21) |
| oscillation | 0% (0/21) | 14% (3/21) | 14% (3/21) | 14% (3/21) | 33% (7/21) | 52% (11/21) |
| flatline | 0% (0/21) | 0% (0/21) | 0% (0/21) | 100% (21/21) | 100% (21/21) | 100% (21/21) |
| erratic | 0% (0/21) | 0% (0/21) | 0% (0/21) | 0% (0/21) | 0% (0/21) | 14% (3/21) |

## What the agent called it (top 3)

- **spike**: d=4: [('spike', 14), ('erratic', 3), ('stable', 3)]; d=8: [('spike', 17), ('erratic', 1), ('stable', 1)]; d=12: [('spike', 16), ('erratic', 3), ('dip', 1)]; d=18: [('spike', 13), ('INVALID', 3), ('erratic', 2)]; d=24: [('spike', 16), ('erratic', 4), ('stable', 1)]; d=36: [('spike', 9), ('stable', 5), ('erratic', 3)]
- **dip**: d=4: [('dip', 21)]; d=8: [('dip', 21)]; d=12: [('dip', 21)]; d=18: [('dip', 21)]; d=24: [('dip', 21)]; d=36: [('dip', 20), ('stable', 1)]
- **step_increase**: d=4: [('spike', 13), ('step_increase', 5), ('stable', 2)]; d=8: [('step_increase', 17), ('exponential_increase', 2), ('stable', 1)]; d=12: [('step_increase', 20), ('exponential_increase', 1)]; d=18: [('step_increase', 20), ('exponential_increase', 1)]; d=24: [('step_increase', 21)]; d=36: [('step_increase', 21)]
- **step_decrease**: d=4: [('dip', 12), ('step_decrease', 5), ('stable', 2)]; d=8: [('step_decrease', 15), ('dip', 3), ('INVALID', 1)]; d=12: [('step_decrease', 19)]; d=18: [('step_decrease', 19)]; d=24: [('step_decrease', 19)]; d=36: [('step_decrease', 19)]
- **gradual_increase**: d=4: [('exponential_increase', 7), ('spike', 6), ('stable', 4)]; d=8: [('exponential_increase', 16), ('INVALID', 3), ('stable', 2)]; d=12: [('exponential_increase', 20), ('stable', 1)]; d=18: [('exponential_increase', 19), ('step_increase', 1), ('gradual_increase', 1)]; d=24: [('exponential_increase', 12), ('gradual_increase', 9)]; d=36: [('gradual_increase', 18), ('exponential_increase', 2), ('step_increase', 1)]
- **gradual_decrease**: d=4: [('dip', 8), ('stable', 8), ('step_decrease', 3)]; d=8: [('stable', 7), ('gradual_decrease', 6), ('dip', 5)]; d=12: [('gradual_decrease', 15), ('step_decrease', 4), ('stable', 2)]; d=18: [('gradual_decrease', 21)]; d=24: [('gradual_decrease', 21)]; d=36: [('gradual_decrease', 21)]
- **exponential_increase**: d=4: [('spike', 12), ('stable', 4), ('exponential_increase', 3)]; d=8: [('exponential_increase', 11), ('spike', 8), ('stable', 2)]; d=12: [('exponential_increase', 17), ('spike', 3), ('stable', 1)]; d=18: [('exponential_increase', 19), ('stable', 1), ('spike', 1)]; d=24: [('exponential_increase', 20), ('stable', 1)]; d=36: [('exponential_increase', 20), ('stable', 1)]
- **oscillation**: d=4: [('dip', 9), ('spike', 5), ('stable', 4)]; d=8: [('stable', 8), ('spike', 6), ('dip', 5)]; d=12: [('stable', 12), ('spike', 6), ('dip', 2)]; d=18: [('stable', 10), ('spike', 6), ('dip', 3)]; d=24: [('stable', 14), ('oscillation', 5), ('spike', 2)]; d=36: [('oscillation', 21)]
- **flatline**: d=4: [('stable', 15), ('erratic', 2), ('gradual_decrease', 1)]; d=8: [('stable', 18), ('spike', 1), ('step_increase', 1)]; d=12: [('stable', 12), ('flatline', 7), ('spike', 1)]; d=18: [('flatline', 21)]; d=24: [('flatline', 21)]; d=36: [('flatline', 21)]
- **erratic**: d=4: [('stable', 11), ('dip', 5), ('spike', 4)]; d=8: [('spike', 8), ('dip', 6), ('stable', 5)]; d=12: [('dip', 8), ('spike', 6), ('stable', 4)]; d=18: [('dip', 6), ('stable', 5), ('erratic', 4)]; d=24: [('dip', 8), ('stable', 6), ('erratic', 5)]; d=36: [('erratic', 14), ('stable', 3), ('spike', 2)]
