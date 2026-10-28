| config | req | total s | prefill s | decode s | tokens | forced | stop | json | vs sp3old | sev/label/action1 vs gold (RWH) |
|---|---|---|---|---|---|---|---|---|---|---|
| sp3k4 | q0 | 27.8 | 2.8 | 24.9 | 429 | 107 | json | ok | bytes | - |
| sp3k4 | q1 | 21.6 | 1.8 | 19.8 | 358 | 102 | json | ok | DIFF | - |
| sp3k4 | q2 | 18.7 | 0.7 | 18.0 | 376 | 108 | json | ok | fields | = |
| sp3k4 | q3 | 18.7 | 0.7 | 18.0 | 349 | 106 | json | ok | fields | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| sp3k4 | q4 | 37.6 | 2.5 | 35.1 | 652 | 160 | json | ok | fields | critical/power_quality_issue/('request_facility_review',) vs critical/power_quality_issue/('inspect_electrical',) |
| sp3k4 | q5 | 19.4 | 0.6 | 18.8 | 389 | 125 | json | ok | bytes | = |
| sp3k4 | q6 | 21.5 | 0.9 | 20.6 | 383 | 111 | json | ok | fields | = |
| sp3k4 | q7 | 21.3 | 1.1 | 20.2 | 381 | 112 | json | ok | fields | = |
| sp3k4 | q8 | 17.6 | 0.7 | 16.9 | 345 | 105 | json | ok | fields | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| sp3k4 | q9 | 18.2 | 0.8 | 17.4 | 330 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **sp3k4** | mean | **22.2** | | | | | | | | |
| sp3k4 | agents | before==after True, ==ref True | reload - | | | | | | |
| sp3k4r8 | q0 | 28.0 | 2.8 | 25.2 | 429 | 107 | json | ok | fields | - |
| sp3k4r8 | q1 | 22.4 | 1.8 | 20.7 | 358 | 102 | json | ok | DIFF | - |
| sp3k4r8 | q2 | 19.1 | 0.7 | 18.4 | 374 | 108 | json | ok | fields | = |
| sp3k4r8 | q3 | 20.4 | 0.7 | 19.7 | 355 | 106 | json | ok | bytes | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| sp3k4r8 | q4 | 38.8 | 2.5 | 36.3 | 652 | 160 | json | ok | fields | critical/power_quality_issue/('request_facility_review',) vs critical/power_quality_issue/('inspect_electrical',) |
| sp3k4r8 | q5 | 20.7 | 0.6 | 20.1 | 389 | 125 | json | ok | bytes | = |
| sp3k4r8 | q6 | 22.7 | 0.9 | 21.7 | 383 | 111 | json | ok | bytes | = |
| sp3k4r8 | q7 | 22.6 | 1.1 | 21.6 | 381 | 112 | json | ok | fields | = |
| sp3k4r8 | q8 | 18.2 | 0.7 | 17.5 | 345 | 105 | json | ok | fields | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| sp3k4r8 | q9 | 19.2 | 0.8 | 18.4 | 329 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **sp3k4r8** | mean | **23.2** | | | | | | | | |
| sp3k4r8 | agents | before==after True, ==ref True | reload - | | | | | | |
| sp3new | q0 | 27.3 | 2.8 | 24.5 | 429 | 107 | json | ok | bytes | - |
| sp3new | q1 | 21.4 | 1.8 | 19.6 | 358 | 102 | json | ok | DIFF | - |
| sp3new | q2 | 18.7 | 0.7 | 18.0 | 376 | 108 | json | ok | fields | = |
| sp3new | q3 | 18.7 | 0.7 | 18.0 | 349 | 106 | json | ok | fields | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| sp3new | q4 | 33.6 | 2.4 | 31.1 | 599 | 157 | json | ok | fields | critical/power_quality_issue/('request_facility_review',) vs critical/power_quality_issue/('inspect_electrical',) |
| sp3new | q5 | 19.3 | 0.6 | 18.6 | 389 | 125 | json | ok | bytes | = |
| sp3new | q6 | 21.4 | 0.9 | 20.5 | 383 | 111 | json | ok | bytes | = |
| sp3new | q7 | 21.2 | 1.1 | 20.1 | 381 | 112 | json | ok | fields | = |
| sp3new | q8 | 17.4 | 0.7 | 16.7 | 345 | 105 | json | ok | fields | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| sp3new | q9 | 18.1 | 0.8 | 17.4 | 330 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **sp3new** | mean | **21.7** | | | | | | | | |
| sp3new | agents | before==after True, ==ref True | reload - | | | | | | |
| sp3old | q0 | 25.2 | 2.7 | 22.4 | 429 | 107 | json | ok | bytes | - |
| sp3old | q1 | 18.9 | 1.8 | 17.2 | 341 | 103 | json | ok | bytes | - |
| sp3old | q2 | 17.0 | 0.7 | 16.2 | 367 | 108 | json | ok | bytes | = |
| sp3old | q3 | 18.5 | 0.7 | 17.7 | 355 | 106 | json | ok | bytes | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| sp3old | q4 | 35.1 | 2.4 | 32.7 | 651 | 160 | json | ok | bytes | critical/power_quality_issue/('request_facility_review',) vs critical/power_quality_issue/('inspect_electrical',) |
| sp3old | q5 | 18.7 | 0.6 | 18.1 | 389 | 125 | json | ok | bytes | = |
| sp3old | q6 | 21.2 | 0.9 | 20.2 | 383 | 111 | json | ok | bytes | = |
| sp3old | q7 | 20.9 | 1.1 | 19.7 | 381 | 112 | json | ok | bytes | = |
| sp3old | q8 | 16.8 | 0.7 | 16.0 | 341 | 105 | json | ok | bytes | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| sp3old | q9 | 17.9 | 0.8 | 17.1 | 329 | 97 | json | ok | bytes | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **sp3old** | mean | **21.0** | | | | | | | | |
| sp3old | agents | before==after True, ==ref True | reload - | | | | | | |
