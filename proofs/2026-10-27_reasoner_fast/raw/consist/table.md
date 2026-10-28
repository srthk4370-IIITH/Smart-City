| prompt | runs | severity | label | actions | checks | guarded severity | first divergence: step, margin (top1-top2) |
|---|---|---|---|---|---|---|---|
| q0 INC-0361 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | step 55, margins 0.003-0.128; logits bitwise differ from step 0 |
| q1 INC-0362 | 5 | 80% ({'warning': 4, 'normal': 1}) | 80% | 60% | 80% | 100% | step 7, margins 0.005-0.164; logits bitwise differ from step 0 |
| q4 rwh:rwh-00142 | 5 | 100% ({'critical': 5}) | 100% | 60% | 100% | 100% | step 33, margins 0.027-0.478; logits bitwise differ from step 0 |
| q7 rwh:rwh-00100 | 5 | 100% ({'sensor_fault': 5}) | 100% | 80% | 100% | 100% | step 34, margins 0.009-0.046; logits bitwise differ from step 26 |
| q8 rwh:rwh-00063 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | none (identical picks); logits bitwise identical |
| q9 rwh:rwh-00117 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | none (identical picks); logits bitwise differ from step 194 |
| **all** | 30 | **97%** | **97%** | 83% | 97% | **100%** | |
