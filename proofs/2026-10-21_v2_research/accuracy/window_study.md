# Window length study (device outputs)

## A. placement_v2 (paired across window length; 183 events, 100 clean)

### A1 pattern accuracy by window n x readings since onset d (all events)
| d | n=48 | n=96 | n=144 | McNemar 48 vs 144 (48-only/144-only, p) | 48 vs 96 |
|---|---|---|---|---|---|
| 4 (20 min) | 45 [38-53] n=183 | 48 [40-55] n=183 | 44 [37-51] n=183 | 13/10, p=0.678 | 4/8, p=0.388 |
| 8 (40 min) | 74 [67-80] n=183 | 75 [68-81] n=183 | 70 [63-76] n=183 | 17/10, p=0.248 | 7/9, p=0.804 |
| 12 (60 min) | 79 [72-84] n=183 | 79 [73-84] n=183 | 74 [67-80] n=183 | 16/7, p=0.093 | 7/8, p=1.000 |
| 18 (90 min) | 82 [76-87] n=183 | 77 [70-82] n=183 | 78 [72-84] n=183 | 15/7, p=0.134 | 14/4, p=0.031 |
| 24 (120 min) | 86 [80-90] n=183 | 80 [73-85] n=183 | 82 [76-87] n=183 | 12/5, p=0.143 | 16/5, p=0.027 |
| 36 (180 min) | 82 [76-87] n=183 | 84 [78-88] n=183 | 80 [74-85] n=183 | 17/13, p=0.585 | 12/14, p=0.845 |

clean windows (no event): n=48: false alarm (status!=normal) 18 [12-27] n=100, pattern!=stable 37 [28-47] n=100; n=96: false alarm (status!=normal) 29 [21-38] n=100, pattern!=stable 57 [47-66] n=100; n=144: false alarm (status!=normal) 27 [19-36] n=100, pattern!=stable 57 [47-66] n=100

### A2 pattern accuracy by true pattern x d x n (best n bold when it beats the others by >= 10 pts)
| pattern | d | n=48 | n=96 | n=144 |
|---|---|---|---|---|
| dip | 4 | 79 [52-92] n=14 | 79 [52-92] n=14 | 71 [45-88] n=14 |
| dip | 8 | 86 [60-96] n=14 | 86 [60-96] n=14 | 79 [52-92] n=14 |
| dip | 12 | 93 [68-99] n=14 | 93 [68-99] n=14 | 86 [60-96] n=14 |
| dip | 18 | 93 [68-99] n=14 | 93 [68-99] n=14 | 93 [68-99] n=14 |
| dip | 24 | 86 [60-96] n=14 | 93 [68-99] n=14 | 86 [60-96] n=14 |
| dip | 36 | 86 [60-96] n=14 | 93 [68-99] n=14 | 93 [68-99] n=14 |
| erratic | 4 | 0 [0-16] n=21 | 14 [5-35] n=21 | 10 [3-29] n=21 |
| erratic | 8 | 19 [8-40] n=21 | 19 [8-40] n=21 | 10 [3-29] n=21 |
| erratic | 12 | 33 [17-55] n=21 | 43 [24-64] n=21 | 38 [21-59] n=21 |
| erratic | 18 | 57 [36-76] n=21 | 52 [32-72] n=21 | 52 [32-72] n=21 |
| erratic | 24 | 71 [50-86] n=21 | 67 [45-83] n=21 | 67 [45-83] n=21 |
| erratic | 36 | 57 [36-76] n=21 | 86 [65-95] n=21 | 81 [60-92] n=21 |
| exponential_increase | 4 | 76 [55-89] n=21 | 76 [55-89] n=21 | 67 [45-83] n=21 |
| exponential_increase | 8 | 76 [55-89] n=21 | 76 [55-89] n=21 | 71 [50-86] n=21 |
| exponential_increase | 12 | 67 [45-83] n=21 | 67 [45-83] n=21 | 57 [36-76] n=21 |
| exponential_increase | 18 | **71 [50-86] n=21** | 52 [32-72] n=21 | 52 [32-72] n=21 |
| exponential_increase | 24 | **71 [50-86] n=21** | 48 [28-68] n=21 | 52 [32-72] n=21 |
| exponential_increase | 36 | 71 [50-86] n=21 | 71 [50-86] n=21 | 67 [45-83] n=21 |
| flatline | 4 | 5 [1-23] n=21 | 10 [3-29] n=21 | 19 [8-40] n=21 |
| flatline | 8 | 90 [71-97] n=21 | 86 [65-95] n=21 | 90 [71-97] n=21 |
| flatline | 12 | 100 [84-100] n=21 | 100 [84-100] n=21 | 100 [84-100] n=21 |
| flatline | 18 | 100 [84-100] n=21 | 95 [77-99] n=21 | 100 [84-100] n=21 |
| flatline | 24 | 100 [84-100] n=21 | 95 [77-99] n=21 | 100 [84-100] n=21 |
| flatline | 36 | 86 [65-95] n=21 | 95 [77-99] n=21 | 100 [84-100] n=21 |
| gradual_decrease | 4 | 29 [12-55] n=14 | 29 [12-55] n=14 | 36 [16-61] n=14 |
| gradual_decrease | 8 | 79 [52-92] n=14 | 79 [52-92] n=14 | 86 [60-96] n=14 |
| gradual_decrease | 12 | 86 [60-96] n=14 | 79 [52-92] n=14 | 79 [52-92] n=14 |
| gradual_decrease | 18 | 86 [60-96] n=14 | 86 [60-96] n=14 | 79 [52-92] n=14 |
| gradual_decrease | 24 | 86 [60-96] n=14 | 86 [60-96] n=14 | 86 [60-96] n=14 |
| gradual_decrease | 36 | **93 [68-99] n=14** | 79 [52-92] n=14 | 64 [39-84] n=14 |
| gradual_increase | 4 | 19 [8-40] n=21 | 19 [8-40] n=21 | 14 [5-35] n=21 |
| gradual_increase | 8 | 86 [65-95] n=21 | 95 [77-99] n=21 | 76 [55-89] n=21 |
| gradual_increase | 12 | 81 [60-92] n=21 | 90 [71-97] n=21 | 76 [55-89] n=21 |
| gradual_increase | 18 | 81 [60-92] n=21 | 71 [50-86] n=21 | 81 [60-92] n=21 |
| gradual_increase | 24 | 86 [65-95] n=21 | 67 [45-83] n=21 | 81 [60-92] n=21 |
| gradual_increase | 36 | **90 [71-97] n=21** | 71 [50-86] n=21 | 62 [41-79] n=21 |
| oscillation | 4 | 0 [-0-20] n=15 | 0 [-0-20] n=15 | 0 [-0-20] n=15 |
| oscillation | 8 | 20 [7-45] n=15 | 27 [11-52] n=15 | 33 [15-58] n=15 |
| oscillation | 12 | 60 [36-80] n=15 | 53 [30-75] n=15 | 60 [36-80] n=15 |
| oscillation | 18 | 80 [55-93] n=15 | 60 [36-80] n=15 | 73 [48-89] n=15 |
| oscillation | 24 | 87 [62-96] n=15 | 73 [48-89] n=15 | 80 [55-93] n=15 |
| oscillation | 36 | 87 [62-96] n=15 | 73 [48-89] n=15 | 80 [55-93] n=15 |
| spike | 4 | 76 [55-89] n=21 | 86 [65-95] n=21 | 71 [50-86] n=21 |
| spike | 8 | 86 [65-95] n=21 | 86 [65-95] n=21 | 76 [55-89] n=21 |
| spike | 12 | 81 [60-92] n=21 | 81 [60-92] n=21 | 76 [55-89] n=21 |
| spike | 18 | 71 [50-86] n=21 | 76 [55-89] n=21 | 81 [60-92] n=21 |
| spike | 24 | 76 [55-89] n=21 | 81 [60-92] n=21 | 86 [65-95] n=21 |
| spike | 36 | 76 [55-89] n=21 | 71 [50-86] n=21 | 71 [50-86] n=21 |
| step_decrease | 4 | 79 [52-92] n=14 | 71 [45-88] n=14 | 71 [45-88] n=14 |
| step_decrease | 8 | 93 [68-99] n=14 | 93 [68-99] n=14 | 93 [68-99] n=14 |
| step_decrease | 12 | 93 [68-99] n=14 | 93 [68-99] n=14 | 86 [60-96] n=14 |
| step_decrease | 18 | 93 [68-99] n=14 | 93 [68-99] n=14 | 86 [60-96] n=14 |
| step_decrease | 24 | 100 [78-100] n=14 | 100 [78-100] n=14 | 100 [78-100] n=14 |
| step_decrease | 36 | 93 [68-99] n=14 | 100 [78-100] n=14 | 100 [78-100] n=14 |
| step_increase | 4 | 95 [77-99] n=21 | 90 [71-97] n=21 | 81 [60-92] n=21 |
| step_increase | 8 | 100 [84-100] n=21 | 100 [84-100] n=21 | 90 [71-97] n=21 |
| step_increase | 12 | 100 [84-100] n=21 | 95 [77-99] n=21 | 86 [65-95] n=21 |
| step_increase | 18 | 100 [84-100] n=21 | 100 [84-100] n=21 | 90 [71-97] n=21 |
| step_increase | 24 | 100 [84-100] n=21 | 100 [84-100] n=21 | 90 [71-97] n=21 |
| step_increase | 36 | 95 [77-99] n=21 | 100 [84-100] n=21 | 90 [71-97] n=21 |

### A3 by runtime severity (status of the EARLY 4 h call, what LadderN sees) at the refinement stages
| stage | early status | n events | n=48 | n=96 | n=144 | clean windows with that early status: false alarm at 48/96/144 |
|---|---|---|---|---|---|---|
| d=18 | normal | 65 | 77 [65-86] n=65 | 69 [57-79] n=65 | 72 [60-82] n=65 | [0, 16, 16] of 82 |
| d=18 | warning | 45 | 87 [74-94] n=45 | 82 [69-91] n=45 | 84 [71-92] n=45 | [4, 3, 3] of 4 |
| d=18 | critical | 34 | 79 [63-90] n=34 | 68 [51-81] n=34 | 68 [51-81] n=34 | [12, 9, 7] of 12 |
| d=18 | sensor_fault | 37 | 92 [79-97] n=37 | 92 [79-97] n=37 | 89 [75-96] n=37 | [2, 1, 1] of 2 |
| d=24 | normal | 65 | 82 [70-89] n=65 | 77 [65-86] n=65 | 78 [67-87] n=65 | [0, 16, 16] of 82 |
| d=24 | warning | 45 | 87 [74-94] n=45 | 78 [64-88] n=45 | 78 [64-88] n=45 | [4, 3, 3] of 4 |
| d=24 | critical | 34 | 79 [63-90] n=34 | 71 [54-83] n=34 | 74 [57-85] n=34 | [12, 9, 7] of 12 |
| d=24 | sensor_fault | 37 | 100 [91-100] n=37 | 95 [82-98] n=37 | 100 [91-100] n=37 | [2, 1, 1] of 2 |
| d=36 | normal | 65 | 78 [67-87] n=65 | 77 [65-86] n=65 | 74 [62-83] n=65 | [0, 16, 16] of 82 |
| d=36 | warning | 45 | 89 [76-95] n=45 | 84 [71-92] n=45 | 73 [59-84] n=45 | [4, 3, 3] of 4 |
| d=36 | critical | 34 | 76 [60-88] n=34 | 79 [63-90] n=34 | 82 [66-92] n=34 | [12, 9, 7] of 12 |
| d=36 | sensor_fault | 37 | 89 [75-96] n=37 | 97 [86-100] n=37 | 97 [86-100] n=37 | [2, 1, 1] of 2 |

### A4 by EARLY predicted pattern family (runtime-visible) at the refinement stages
| stage | early family | n | n=48 | n=96 | n=144 |
|---|---|---|---|---|---|
| d=18 | transient | 44 | 86 [73-94] n=44 | 89 [76-95] n=44 | 91 [79-96] n=44 |
| d=18 | step | 38 | 92 [79-97] n=38 | 95 [83-98] n=38 | 84 [70-93] n=38 |
| d=18 | trend | 51 | 86 [74-93] n=51 | 72 [59-83] n=51 | 76 [63-86] n=51 |
| d=18 | noisy | 11 | 64 [35-85] n=11 | 55 [28-79] n=11 | 55 [28-79] n=11 |
| d=18 | flat | 19 | 100 [83-100] n=19 | 95 [75-99] n=19 | 100 [83-100] n=19 |
| d=18 | stable | 18 | 39 [20-61] n=18 | 17 [6-39] n=18 | 28 [12-51] n=18 |
| d=18 | invalid | 2 | 50 [10-90] n=2 | 100 [34-100] n=2 | 100 [34-100] n=2 |
| d=36 | transient | 44 | 80 [66-89] n=44 | 93 [82-98] n=44 | 89 [76-95] n=44 |
| d=36 | step | 38 | 90 [76-96] n=38 | 95 [83-98] n=38 | 87 [73-94] n=38 |
| d=36 | trend | 51 | 90 [79-96] n=51 | 80 [68-89] n=51 | 72 [59-83] n=51 |
| d=36 | noisy | 11 | 82 [52-95] n=11 | 82 [52-95] n=11 | 100 [74-100] n=11 |
| d=36 | flat | 19 | 90 [69-97] n=19 | 95 [75-99] n=19 | 100 [83-100] n=19 |
| d=36 | stable | 18 | 50 [29-71] n=18 | 33 [16-56] n=18 | 33 [16-56] n=18 |
| d=36 | invalid | 2 | 50 [10-90] n=2 | 100 [34-100] n=2 | 100 [34-100] n=2 |

number of flagged sensors: NOT derivable from these data (every placement case and test row is one sensor); needs an app-level multi-sensor run.

### A5 window-selection policies through the app chain (early 4 h -> 1.5 h -> 3 h, keep-early-spike/dip rule)
| policy | 1.5 h pattern acc | 3 h pattern acc | mean n at 3 h |
|---|---|---|---|
| ladder (current LadderN) | 0.792 | 0.858 | 106 |
| fixed 4 h | 0.836 | 0.842 | 48 |
| fixed 8 h | 0.781 | 0.852 | 96 |
| fixed 12 h | 0.787 | 0.814 | 144 |
| learned table (leave-one-case-out CV) | 0.825 | 0.874 | 86 |
| learned table (in-sample, optimistic) | 0.852 | 0.907 | 86 |

learned cells (stage, early status, early family) -> n [acc 48/96/144 of cnt]: (18, 'critical', 'noisy'): 144 [1/1/1 of 2]; (18, 'critical', 'step'): 48 [8/8/7 of 9]; (18, 'critical', 'transient'): 48 [12/11/11 of 12]; (18, 'critical', 'trend'): 48 [7/4/4 of 11]; (18, 'normal', 'invalid'): 48 [1/2/2 of 2]; (18, 'normal', 'noisy'): 48 [4/3/3 of 5]; (18, 'normal', 'stable'): 48 [7/3/5 of 18]; (18, 'normal', 'step'): 48 [11/11/10 of 11]; (18, 'normal', 'transient'): 96 [18/19/19 of 21]; (18, 'normal', 'trend'): 48 [10/9/10 of 10]; (18, 'sensor_fault', 'flat'): 144 [19/18/19 of 19]; (18, 'sensor_fault', 'noisy'): 144 [2/2/2 of 4]; (18, 'sensor_fault', 'step'): 96 [13/14/12 of 14]; (18, 'warning', 'step'): 96 [3/3/3 of 4]; (18, 'warning', 'transient'): 96 [10/11/11 of 11]; (18, 'warning', 'trend'): 48 [27/24/25 of 30]; (36, 'critical', 'noisy'): 144 [1/1/2 of 2]; (36, 'critical', 'step'): 48 [8/8/7 of 9]; (36, 'critical', 'transient'): 96 [10/12/11 of 12]; (36, 'critical', 'trend'): 144 [8/7/8 of 11]; (36, 'normal', 'invalid'): 48 [1/2/2 of 2]; (36, 'normal', 'noisy'): 48 [5/4/5 of 5]; (36, 'normal', 'stable'): 48 [9/6/6 of 18]; (36, 'normal', 'step'): 96 [10/11/10 of 11]; (36, 'normal', 'transient'): 96 [17/21/19 of 21]; (36, 'normal', 'trend'): 48 [10/8/8 of 10]; (36, 'sensor_fault', 'flat'): 144 [17/18/19 of 19]; (36, 'sensor_fault', 'noisy'): 144 [3/4/4 of 4]; (36, 'sensor_fault', 'step'): 96 [13/14/13 of 14]; (36, 'warning', 'step'): 96 [3/3/3 of 4]; (36, 'warning', 'transient'): 96 [11/11/11 of 11]; (36, 'warning', 'trend'): 48 [28/26/21 of 30]

## B. device test rows (host400 + partial test split, dedup; unpaired, all six roles)
| slice | n | pattern | status | cause | false alarm (negatives) |
|---|---|---|---|---|---|
| window <=3h | 126 | 90 [83-94] n=126 | 88 [81-93] n=126 | 90 [83-94] n=126 | 12 [5-27] n=33 |
| window 4h | 462 | 92 [89-94] n=462 | 94 [91-96] n=462 | 91 [88-93] n=462 | 4 [2-9] n=129 |
| window 4-8h | 266 | 88 [84-91] n=266 | 92 [88-95] n=266 | 91 [87-94] n=266 | 13 [7-22] n=79 |
| window 8-12h | 199 | 87 [82-91] n=199 | 90 [85-93] n=199 | 88 [83-92] n=199 | 16 [8-27] n=58 |
| age a<=40min x window <=3h | 22 | 91 [72-98] n=22 | 82 [62-93] n=22 | 86 [67-95] n=22 | 0 [0-56] n=3 |
| age a<=40min x window 4h | 61 | 90 [80-95] n=61 | 93 [84-97] n=61 | 88 [78-94] n=61 | 0 [-0-28] n=10 |
| age a<=40min x window 4-8h | 42 | 88 [75-95] n=42 | 95 [84-99] n=42 | 93 [81-98] n=42 | 0 [0-23] n=13 |
| age a<=40min x window 8-12h | 19 | 95 [75-99] n=19 | 90 [69-97] n=19 | 90 [69-97] n=19 | 0 [0-79] n=1 |
| age b<=1.5h x window <=3h | 43 | 91 [78-96] n=43 | 88 [76-95] n=43 | 93 [81-98] n=43 | 0 [0-49] n=4 |
| age b<=1.5h x window 4h | 104 | 95 [89-98] n=104 | 93 [87-97] n=104 | 92 [86-96] n=104 | 5 [1-25] n=19 |
| age b<=1.5h x window 4-8h | 33 | 94 [80-98] n=33 | 97 [85-100] n=33 | 91 [76-97] n=33 | 17 [3-56] n=6 |
| age b<=1.5h x window 8-12h | 27 | 85 [68-94] n=27 | 96 [82-99] n=27 | 96 [82-99] n=27 | 0 [0-35] n=7 |
| age c<=3h x window <=3h | 36 | 86 [71-94] n=36 | 89 [75-96] n=36 | 92 [78-97] n=36 | 17 [5-45] n=12 |
| age c<=3h x window 4h | 104 | 88 [80-92] n=104 | 93 [87-97] n=104 | 91 [84-95] n=104 | 0 [0-17] n=19 |
| age c<=3h x window 4-8h | 33 | 82 [66-91] n=33 | 94 [80-98] n=33 | 91 [76-97] n=33 | 0 [-0-43] n=5 |
| age c<=3h x window 8-12h | 9 | 89 [56-98] n=9 | 89 [56-98] n=9 | 89 [56-98] n=9 | 50 [10-90] n=2 |
| age d>3h x window <=3h | 13 | 92 [67-99] n=13 | 92 [67-99] n=13 | 85 [58-96] n=13 | 25 [5-70] n=4 |
| age d>3h x window 4h | 122 | 93 [88-97] n=122 | 96 [91-98] n=122 | 92 [86-96] n=122 | 3 [1-16] n=31 |
| age d>3h x window 4-8h | 108 | 87 [79-92] n=108 | 89 [82-94] n=108 | 91 [84-95] n=108 | 15 [5-36] n=20 |
| age d>3h x window 8-12h | 92 | 87 [79-92] n=92 | 90 [82-95] n=92 | 86 [77-92] n=92 | 11 [3-33] n=18 |
| age no_event x window <=3h | 12 | 92 [65-98] n=12 | 92 [65-98] n=12 | 83 [55-95] n=12 | 10 [2-40] n=10 |
| age no_event x window 4h | 71 | 90 [81-95] n=71 | 92 [83-96] n=71 | 90 [81-95] n=71 | 6 [2-16] n=50 |
| age no_event x window 4-8h | 50 | 90 [79-96] n=50 | 92 [81-97] n=50 | 92 [81-97] n=50 | 17 [8-33] n=35 |
| age no_event x window 8-12h | 52 | 85 [72-92] n=52 | 86 [75-93] n=52 | 88 [77-95] n=52 | 20 [10-37] n=30 |
| gold status normal x window <=3h | 67 | 90 [80-95] n=67 | 90 [80-95] n=67 | 92 [84-97] n=67 | 9 [3-24] n=32 |
| gold status normal x window 4h | 247 | 90 [86-93] n=247 | 96 [92-98] n=247 | 92 [88-95] n=247 | 3 [1-8] n=127 |
| gold status normal x window 4-8h | 162 | 88 [82-92] n=162 | 96 [91-98] n=162 | 94 [90-97] n=162 | 6 [2-13] n=73 |
| gold status normal x window 8-12h | 124 | 87 [80-92] n=124 | 94 [88-97] n=124 | 92 [86-96] n=124 | 11 [5-22] n=55 |
| gold status warning x window <=3h | 32 | 94 [80-98] n=32 | 91 [76-97] n=32 | 94 [80-98] n=32 | 100 [21-100] n=1 |
| gold status warning x window 4h | 92 | 94 [86-97] n=92 | 90 [82-95] n=92 | 89 [81-94] n=92 | 0 [0-79] n=1 |
| gold status warning x window 4-8h | 55 | 86 [74-92] n=55 | 86 [74-92] n=55 | 84 [72-91] n=55 | 100 [61-100] n=6 |
| gold status warning x window 8-12h | 30 | 80 [63-90] n=30 | 77 [59-88] n=30 | 77 [59-88] n=30 | 100 [44-100] n=3 |
| gold status critical x window <=3h | 9 | 78 [45-94] n=9 | 67 [35-88] n=9 | 56 [27-81] n=9 | - |
| gold status critical x window 4h | 31 | 77 [60-89] n=31 | 84 [67-93] n=31 | 74 [57-86] n=31 | 100 [21-100] n=1 |
| gold status critical x window 4-8h | 14 | 86 [60-96] n=14 | 79 [52-92] n=14 | 86 [60-96] n=14 | - |
| gold status critical x window 8-12h | 13 | 85 [58-96] n=13 | 92 [67-99] n=13 | 85 [58-96] n=13 | - |
| gold status sensor_fault x window <=3h | 18 | 89 [67-97] n=18 | 89 [67-97] n=18 | 89 [67-97] n=18 | - |
| gold status sensor_fault x window 4h | 92 | 98 [92-99] n=92 | 96 [89-98] n=92 | 96 [89-98] n=92 | - |
| gold status sensor_fault x window 4-8h | 35 | 91 [78-97] n=35 | 91 [78-97] n=35 | 91 [78-97] n=35 | - |
| gold status sensor_fault x window 8-12h | 32 | 94 [80-98] n=32 | 88 [72-95] n=32 | 88 [72-95] n=32 | - |
| family event x window 4h | 109 | 84 [76-90] n=109 | 94 [87-97] n=109 | 86 [78-92] n=109 | 10 [3-31] n=19 |
| family event x window 4-8h | 88 | 81 [71-88] n=88 | 92 [84-96] n=88 | 88 [79-93] n=88 | 7 [1-32] n=14 |
| family event x window 8-12h | 60 | 80 [68-88] n=60 | 90 [80-95] n=60 | 87 [76-93] n=60 | 17 [3-56] n=6 |
| family fault x window 4h | 32 | 94 [80-98] n=32 | 91 [76-97] n=32 | 91 [76-97] n=32 | - |
| family fault x window 4-8h | 23 | 87 [68-96] n=23 | 87 [68-96] n=23 | 87 [68-96] n=23 | - |
| family fault x window 8-12h | 25 | 92 [75-98] n=25 | 84 [65-94] n=25 | 84 [65-94] n=25 | - |
| family compound x window 4h | 19 | 68 [46-85] n=19 | 63 [41-81] n=19 | 53 [32-73] n=19 | - |
| family compound x window 4-8h | 25 | 96 [80-99] n=25 | 88 [70-96] n=25 | 92 [75-98] n=25 | - |
| family compound x window 8-12h | 11 | 91 [62-98] n=11 | 82 [52-95] n=11 | 73 [43-90] n=11 | - |
| family old_shift x window 4h | 15 | 93 [70-99] n=15 | 93 [70-99] n=15 | 80 [55-93] n=15 | 0 [0-66] n=2 |
| family old_shift x window 4-8h | 14 | 86 [60-96] n=14 | 93 [68-99] n=14 | 93 [68-99] n=14 | 100 [21-100] n=1 |
| family old_shift x window 8-12h | 8 | 88 [53-98] n=8 | 88 [53-98] n=8 | 88 [53-98] n=8 | 33 [6-79] n=3 |
| family long_drift x window 4h | 11 | 100 [74-100] n=11 | 100 [74-100] n=11 | 100 [74-100] n=11 | 0 [0-66] n=2 |
| family long_drift x window 4-8h | 11 | 91 [62-98] n=11 | 100 [74-100] n=11 | 100 [74-100] n=11 | 33 [6-79] n=3 |
| family long_drift x window 8-12h | 10 | 90 [60-98] n=10 | 100 [72-100] n=10 | 90 [60-98] n=10 | 33 [6-79] n=3 |
| family recurring x window 4h | 10 | 100 [72-100] n=10 | 100 [72-100] n=10 | 100 [72-100] n=10 | - |
| family recurring x window 4-8h | 8 | 100 [68-100] n=8 | 100 [68-100] n=8 | 100 [68-100] n=8 | - |
| family routine x window 4h | 22 | 91 [72-98] n=22 | 96 [78-99] n=22 | 86 [67-95] n=22 | 0 [0-15] n=22 |
| family routine x window 4-8h | 23 | 91 [73-98] n=23 | 96 [79-99] n=23 | 96 [79-99] n=23 | 4 [1-21] n=23 |
| family routine x window 8-12h | 15 | 93 [70-99] n=15 | 100 [80-100] n=15 | 100 [80-100] n=15 | 0 [-0-20] n=15 |
| family real_routine x window 4h | 21 | 95 [77-99] n=21 | 95 [77-99] n=21 | 95 [77-99] n=21 | 5 [1-23] n=21 |
| family real_routine x window 4-8h | 12 | 83 [55-95] n=12 | 83 [55-95] n=12 | 83 [55-95] n=12 | 17 [5-45] n=12 |
| family stable x window 4h | 16 | 75 [50-90] n=16 | 88 [64-96] n=16 | 81 [57-93] n=16 | 12 [4-36] n=16 |
| family stable x window 4-8h | 17 | 82 [59-94] n=17 | 88 [66-97] n=17 | 88 [66-97] n=17 | 24 [10-47] n=17 |
| family stable x window 8-12h | 16 | 75 [50-90] n=16 | 75 [50-90] n=16 | 75 [50-90] n=16 | 25 [10-50] n=16 |
| fault noise (all windows) | 33 | 79 [62-89] n=33 | 76 [59-87] n=33 | 76 [59-87] n=33 | - |
| fault stuck (all windows) | 35 | 100 [90-100] n=35 | 100 [90-100] n=35 | 100 [90-100] n=35 | - |
| fault dropout (all windows) | 23 | 96 [79-99] n=23 | 91 [73-98] n=23 | 91 [73-98] n=23 | - |
| fault bias (all windows) | 37 | 100 [91-100] n=37 | 97 [86-100] n=37 | 97 [86-100] n=37 | - |
| fault saturation (all windows) | 15 | 93 [70-99] n=15 | 93 [70-99] n=15 | 93 [70-99] n=15 | - |
| fault drift (all windows) | 12 | 100 [76-100] n=12 | 92 [65-98] n=12 | 92 [65-98] n=12 | - |
| fault quantised (all windows) | 22 | 100 [85-100] n=22 | 100 [85-100] n=22 | 100 [85-100] n=22 | - |
| onset inside window (d <= n) | 803 | 89 [87-91] n=803 | 92 [90-94] n=803 | 91 [88-92] n=803 | 6 [3-11] n=163 |
| onset OLDER than window (d > n) | 65 | 97 [90-99] n=65 | 95 [87-98] n=65 | 91 [81-96] n=65 | 18 [5-48] n=11 |

onset older than window, by family: Counter({'long_drift': 28, 'recurring': 20, 'old_shift': 16, 'fault': 1}); by window: Counter({'4h': 30, '4-8h': 19, '<=3h': 13, '8-12h': 3})
  fault: outside 100 [21-100] n=1 vs inside 90 [81-94] n=86
  long_drift: outside 96 [82-99] n=28 vs inside 91 [62-98] n=11
  old_shift: outside 94 [72-99] n=16 vs inside 84 [65-94] n=25
  recurring: outside 100 [84-100] n=20 vs inside 100 [61-100] n=6