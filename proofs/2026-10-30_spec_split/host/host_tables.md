# v9 host test tables (WSL CPU)

## base

| req | wall s | stop | tokens | steps | rows/step | decode ms/step | ubatch/step | drafted | kept % | partial % | extra rows | seq_cp ms/step | draft ms/call | RSS MB | same text as base | same as base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a2#0 | 51.24 | action,action | 96,101 | - | - | - | - | - | - | - | - | - | - | 1371 | yes | yes |
| q10#0 | 153.29 | max | 700 | 679 | 1.03 | 153.58 | - | - | - | - | - | - | - | 1584 | yes | yes |
| q10#1 | 113.33 | max | 700 | 679 | 1.03 | 141.51 | - | - | - | - | - | - | - | 1585 | yes | yes |
| q11#0 | 100.2 | max | 1131 | 508 | 2.21 | 171.06 | - | - | - | - | - | - | - | 1582 | yes | yes |
| q12#0 | 90.0 | max | 1114 | 646 | 1.72 | 123.24 | - | - | - | - | - | - | - | 1581 | yes | yes |
| q13#0 | 83.32 | max | 982 | 524 | 1.87 | 130.46 | - | - | - | - | - | - | - | 1585 | yes | yes |
| q14#0 | 149.0 | max | 1535 | 619 | 2.47 | 224.13 | - | - | - | - | - | - | - | 1580 | yes | yes |
| q15#0 | 96.92 | max | 1208 | 630 | 1.91 | 141.18 | - | - | - | - | - | - | - | 1580 | yes | yes |
| s14#0 | 78.55 | max | 700 | 594 | 1.18 | 118.28 | - | - | - | - | - | - | - | 1580 | yes | yes |
| a2#1 | 52.86 | action,action | 96,101 | - | - | - | - | - | - | - | - | - | - | 1391 | yes | yes |

## v9k0

| req | wall s | stop | tokens | steps | rows/step | decode ms/step | ubatch/step | drafted | kept % | partial % | extra rows | seq_cp ms/step | draft ms/call | RSS MB | same text as base | same as base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a2#0 | 45.48 | action,action | 96,101 | - | - | - | - | - | - | - | - | - | - | 1371 | yes | yes |
| q10#0 | 111.85 | max | 700 | 679 | 1.03 | 109.57 | - | - | - | - | - | - | - | 1589 | yes | yes |
| q10#1 | 100.14 | max | 700 | 679 | 1.03 | 116.52 | - | - | - | - | - | - | - | 1589 | yes | yes |
| q11#0 | 83.56 | max | 1131 | 508 | 2.21 | 140.78 | - | - | - | - | - | - | - | 1586 | yes | yes |
| q12#0 | 109.16 | max | 1114 | 646 | 1.72 | 151.54 | - | - | - | - | - | - | - | 1585 | yes | yes |
| q13#0 | 94.35 | max | 982 | 524 | 1.87 | 144.05 | - | - | - | - | - | - | - | 1589 | yes | yes |
| q14#0 | 133.85 | max | 1535 | 619 | 2.47 | 199.79 | - | - | - | - | - | - | - | 1584 | yes | yes |
| q15#0 | 126.48 | max | 1208 | 630 | 1.91 | 187.15 | - | - | - | - | - | - | - | 1583 | yes | yes |
| s14#0 | 93.37 | max | 700 | 594 | 1.18 | 141.09 | - | - | - | - | - | - | - | 1584 | yes | yes |
| a2#1 | 59.71 | action,action | 96,101 | - | - | - | - | - | - | - | - | - | - | 1394 | yes | yes |

**v9k0 vs base** (7 reason requests, warm-up excluded): identical text 7/7; steps 600.0 -> 600.0 (+0.0%); wall 101.6 -> 105.8 s (+4.2%)

