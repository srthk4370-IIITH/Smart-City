| config | req | total s | prefill s | decode s | tokens | forced | stop | json | vs single | sev/label/action1 vs gold (RWH) |
|---|---|---|---|---|---|---|---|---|---|---|
| single | q0 | 30.1 | 2.9 | 27.1 | 441 | 107 | json | ok | bytes | - |
| single | q1 | 26.9 | 1.8 | 25.1 | 424 | 116 | json | ok | bytes | - |
| single | q2 | 22.4 | 0.7 | 21.7 | 382 | 108 | json | ok | bytes | = |
| single | q3 | 20.4 | 0.7 | 19.7 | 354 | 106 | json | ok | bytes | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| single | q4 | 45.0 | 2.5 | 42.4 | 680 | 168 | json | ok | bytes | = |
| single | q5 | 22.1 | 0.6 | 21.4 | 390 | 124 | json | ok | bytes | = |
| single | q6 | 23.5 | 0.9 | 22.5 | 393 | 111 | json | ok | bytes | = |
| single | q7 | 26.6 | 1.1 | 25.5 | 445 | 129 | json | ok | bytes | = |
| single | q8 | 19.8 | 0.7 | 19.1 | 345 | 107 | json | ok | bytes | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| single | q9 | 19.5 | 0.8 | 18.7 | 332 | 97 | json | ok | bytes | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **single** | mean | **25.6** | | | | | | | | |
| single | agents | before==after True, ==ref True | reload - | | | | | | |
| sp3 | q0 | 26.4 | 2.8 | 23.6 | 429 | 107 | json | ok | fields | - |
| sp3 | q1 | 21.1 | 1.8 | 19.3 | 358 | 102 | json | ok | DIFF | - |
| sp3 | q2 | 18.7 | 0.7 | 18.0 | 379 | 108 | json | ok | fields | = |
| sp3 | q3 | 18.7 | 0.7 | 18.0 | 349 | 106 | json | ok | fields | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| sp3 | q4 | 36.3 | 2.5 | 33.9 | 650 | 160 | json | ok | DIFF | critical/power_quality_issue/('request_facility_review',) vs critical/power_quality_issue/('inspect_electrical',) |
| sp3 | q5 | 19.1 | 0.6 | 18.4 | 389 | 125 | json | ok | fields | = |
| sp3 | q6 | 21.2 | 0.9 | 20.3 | 383 | 111 | json | ok | fields | = |
| sp3 | q7 | 20.5 | 1.1 | 19.4 | 375 | 112 | json | ok | fields | = |
| sp3 | q8 | 16.9 | 0.7 | 16.2 | 341 | 105 | json | ok | fields | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| sp3 | q9 | 18.0 | 0.8 | 17.2 | 329 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **sp3** | mean | **21.7** | | | | | | | | |
| sp3 | agents | before==after True, ==ref True | reload - | | | | | | |
