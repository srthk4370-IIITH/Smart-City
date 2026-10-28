# v2 placement study: confusion analysis (device Q4_0)

## d=8 (40 min since onset), window n=48: pattern accuracy 0.738 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 86% | stable 3 |
| dip | 14 | 86% | gradual_increase 1, stable 1 |
| step_increase | 21 | 100% |  |
| step_decrease | 14 | 93% | oscillation 1 |
| gradual_increase | 21 | 86% | stable 2, INVALID 1 |
| gradual_decrease | 14 | 79% | stable 2, step_decrease 1 |
| exponential_increase | 21 | 76% | gradual_increase 3, INVALID 1, stable 1 |
| oscillation | 15 | 20% | stable 5, gradual_decrease 2, erratic 2, dip 2, step_decrease 1 |
| flatline | 21 | 90% | step_increase 1, spike 1 |
| erratic | 21 | 19% | spike 8, stable 4, dip 3, step_increase 1, oscillation 1 |

by role: air_quality 76% (n=70), power 73% (n=70), water 72% (n=43)

role x pattern (wrong/total): air_q/dip 1/7; air_q/erratic 7/7; air_q/exponential_increase 1/7; air_q/gradual_decrease 1/7; air_q/gradual_increase 1/7; air_q/oscillation 6/7; power/dip 1/7; power/erratic 5/7; power/exponential_increase 2/7; power/flatline 1/7; power/gradual_decrease 2/7; power/gradual_increase 1/7; power/oscillation 5/7; power/spike 1/7; power/step_decrease 1/7; water/erratic 5/7; water/exponential_increase 2/7; water/flatline 1/7; water/gradual_increase 1/7; water/oscillation 1/1; water/spike 2/7

## d=36 (180 min since onset), window n=48: pattern accuracy 0.825 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 76% | stable 5 |
| dip | 14 | 86% | iipowerfactor_dip 1, stable 1 |
| step_increase | 21 | 95% | dip 1 |
| step_decrease | 14 | 93% | INVALID 1 |
| gradual_increase | 21 | 90% | step_increase 1, stable 1 |
| gradual_decrease | 14 | 93% | stable 1 |
| exponential_increase | 21 | 71% | gradual_increase 6 |
| oscillation | 15 | 87% | step_decrease 1, stable 1 |
| flatline | 21 | 86% | gradual_decrease 3 |
| erratic | 21 | 57% | stable 4, spike 3, dip 1, step_increase 1 |

by role: air_quality 97% (n=70), power 73% (n=70), water 74% (n=43)

role x pattern (wrong/total): air_q/erratic 2/7; power/dip 2/7; power/erratic 5/7; power/exponential_increase 3/7; power/gradual_decrease 1/7; power/gradual_increase 1/7; power/oscillation 2/7; power/spike 4/7; power/step_decrease 1/7; water/erratic 2/7; water/exponential_increase 3/7; water/flatline 3/7; water/gradual_increase 1/7; water/spike 1/7; water/step_increase 1/7

## d=36 (180 min since onset), window n=96: pattern accuracy 0.836 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 71% | stable 5, sunflower_shaped 1 |
| dip | 14 | 93% | spike 1 |
| step_increase | 21 | 100% |  |
| step_decrease | 14 | 100% |  |
| gradual_increase | 21 | 71% | stable 3, exponential_increase 3 |
| gradual_decrease | 14 | 79% | stable 1, step_decrease 1, oscillation 1 |
| exponential_increase | 21 | 71% | gradual_increase 5, INVALID 1 |
| oscillation | 15 | 73% | step_decrease 2, stable 1, spike 1 |
| flatline | 21 | 95% | INVALID 1 |
| erratic | 21 | 86% | spike 1, dip 1, oscillation 1 |

by role: air_quality 94% (n=70), power 70% (n=70), water 88% (n=43)

role x pattern (wrong/total): air_q/gradual_decrease 1/7; air_q/gradual_increase 3/7; power/dip 1/7; power/erratic 3/7; power/exponential_increase 3/7; power/flatline 1/7; power/gradual_decrease 2/7; power/gradual_increase 3/7; power/oscillation 4/7; power/spike 4/7; water/exponential_increase 3/7; water/spike 2/7

## d=36 (180 min since onset), window n=144: pattern accuracy 0.803 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 71% | stable 4, step_decrease 1, oscillation 1 |
| dip | 14 | 93% | spike 1 |
| step_increase | 21 | 90% | oscillation 2 |
| step_decrease | 14 | 100% |  |
| gradual_increase | 21 | 62% | stable 4, exponential_increase 3, spike 1 |
| gradual_decrease | 14 | 64% | stable 1, oscillation 1, step_decrease 1, step_increase 1, spike 1 |
| exponential_increase | 21 | 67% | gradual_increase 5, stable 1, step_increase 1 |
| oscillation | 15 | 80% | stable 1, step_decrease 1, spike 1 |
| flatline | 21 | 100% |  |
| erratic | 21 | 81% | oscillation 2, spike 1, flatline 1 |

by role: air_quality 91% (n=70), power 69% (n=70), water 81% (n=43)

role x pattern (wrong/total): air_q/gradual_decrease 2/7; air_q/gradual_increase 4/7; power/dip 1/7; power/erratic 3/7; power/exponential_increase 3/7; power/gradual_decrease 3/7; power/gradual_increase 4/7; power/oscillation 3/7; power/spike 4/7; power/step_increase 1/7; water/erratic 1/7; water/exponential_increase 4/7; water/spike 2/7; water/step_increase 1/7

## d=24 (120 min since onset), window n=48: pattern accuracy 0.858 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 76% | stable 5 |
| dip | 14 | 86% | 니_(dip_at_12:25,_0.000)_[e3] 1, stable 1 |
| step_increase | 21 | 100% |  |
| step_decrease | 14 | 100% |  |
| gradual_increase | 21 | 86% | stable 1, INVALID 1, exponential_increase 1 |
| gradual_decrease | 14 | 86% | step_decrease 2 |
| exponential_increase | 21 | 71% | gradual_increase 6 |
| oscillation | 15 | 87% | stable 2 |
| flatline | 21 | 100% |  |
| erratic | 21 | 71% | stable 3, dip 1, spike 1, oscillation 1 |

by role: air_quality 97% (n=70), power 74% (n=70), water 86% (n=43)

role x pattern (wrong/total): air_q/erratic 1/7; air_q/gradual_increase 1/7; power/dip 2/7; power/erratic 4/7; power/exponential_increase 3/7; power/gradual_decrease 2/7; power/gradual_increase 1/7; power/oscillation 2/7; power/spike 4/7; water/erratic 1/7; water/exponential_increase 3/7; water/gradual_increase 1/7; water/spike 1/7

## d=18 (90 min since onset), window n=48: pattern accuracy 0.825 (n=183)

| truth | n | acc | predicted (count) |
|---|---|---|---|
| spike | 21 | 71% | stable 5, INVALID 1 |
| dip | 14 | 93% | stable 1 |
| step_increase | 21 | 100% |  |
| step_decrease | 14 | 93% | oscillation 1 |
| gradual_increase | 21 | 81% | exponential_increase 2, stable 1, INVALID 1 |
| gradual_decrease | 14 | 86% | step_decrease 1, stable 1 |
| exponential_increase | 21 | 71% | gradual_increase 6 |
| oscillation | 15 | 80% | stable 2, step_decrease 1 |
| flatline | 21 | 100% |  |
| erratic | 21 | 57% | spike 4, stable 2, step_increase 2, dip 1 |

by role: air_quality 94% (n=70), power 77% (n=70), water 72% (n=43)

role x pattern (wrong/total): air_q/erratic 1/7; air_q/gradual_decrease 1/7; air_q/gradual_increase 1/7; air_q/spike 1/7; power/dip 1/7; power/erratic 4/7; power/exponential_increase 2/7; power/gradual_decrease 1/7; power/gradual_increase 2/7; power/oscillation 2/7; power/spike 3/7; power/step_decrease 1/7; water/erratic 4/7; water/exponential_increase 4/7; water/gradual_increase 1/7; water/oscillation 1/1; water/spike 2/7

clean n=48: called [('stable', 63), ('spike', 16), ('oscillation', 5), ('gradual_increase', 4), ('step_increase', 3), ('dip', 3), ('step_decrease', 3), ('flatline', 2), ('erratic', 1)]; status!=normal 18/100 by role {'air_quality': '2/40', 'water': '2/20', 'power': '14/40'}

clean n=96: called [('stable', 43), ('spike', 21), ('oscillation', 13), ('INVALID', 7), ('flatline', 5), ('gradual_increase', 4), ('step_decrease', 3), ('gradual_decrease', 2), ('erratic', 1), ('dip', 1)]; status!=normal 29/100 by role {'air_quality': '9/40', 'water': '4/20', 'power': '16/40'}

clean n=144: called [('stable', 43), ('oscillation', 21), ('spike', 18), ('flatline', 8), ('gradual_increase', 4), ('step_decrease', 3), ('dip', 2), ('step_increase', 1)]; status!=normal 27/100 by role {'air_quality': '3/40', 'water': '6/20', 'power': '18/40'}

## n=48 paired d=24 -> d=36 (right->wrong / wrong->right per pattern)
spike: R->W 0, W->R 0
dip: R->W 0, W->R 0
step_increase: R->W 1, W->R 0
step_decrease: R->W 1, W->R 0
gradual_increase: R->W 0, W->R 1
gradual_decrease: R->W 0, W->R 1
exponential_increase: R->W 2, W->R 2
oscillation: R->W 0, W->R 0
flatline: R->W 3, W->R 0
erratic: R->W 3, W->R 0

## d=36: accuracy by window n and oracle over n
oracle(any of 48/96/144) 166/183 = 0.907; majority vote 3 lengths (tie->48) 156/183 = 0.852

## Apples-to-apples at 3 h (d=36, 4 h window)
v1: 184/208 = 0.885; v2: 151/183 = 0.825
v2 per-pattern acc reweighted to v1 mix: 0.833; v1 reweighted to v2 mix: 0.871
v1 by role at d=36: power 60/70, air_quality 66/70, water 58/68
| pattern | v1 n | v1 acc | v1 rules acc | v2 n | v2 acc |
|---|---|---|---|---|---|
| spike | 21 | 43% | 86% | 21 | 76% |
| dip | 21 | 95% | 86% | 14 | 86% |
| step_increase | 21 | 100% | 10% | 21 | 95% |
| step_decrease | 19 | 100% | 16% | 14 | 93% |
| gradual_increase | 21 | 86% | 52% | 21 | 90% |
| gradual_decrease | 21 | 100% | 71% | 14 | 93% |
| exponential_increase | 21 | 95% | 76% | 21 | 71% |
| oscillation | 21 | 100% | 52% | 15 | 87% |
| flatline | 21 | 100% | 100% | 21 | 86% |
| erratic | 21 | 67% | 14% | 21 | 57% |

v1 d=36 confusions: spike: stable 5, erratic 3, dip 3, oscillation 1; dip: stable 1; gradual_increase: exponential_increase 2, step_increase 1; exponential_increase: stable 1; erratic: stable 3, spike 2, oscillation 1, dip 1

shared base windows v1/v2 events: 7 of 154