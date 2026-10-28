| config | req | total s | prefill s | decode s | tokens | forced | stop | json | vs base | sev/label/action1 vs gold (RWH) |
|---|---|---|---|---|---|---|---|---|---|---|
| base | q0 | 31.4 | 2.8 | 28.5 | 441 | 107 | json | ok | bytes | - |
| base | q1 | 30.4 | 1.9 | 28.5 | 453 | 122 | json | ok | bytes | - |
| base | q2 | 24.5 | 0.7 | 23.8 | 382 | 108 | json | ok | bytes | = |
| base | q3 | 22.6 | 0.8 | 21.8 | 354 | 106 | json | ok | bytes | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| base | q4 | 48.3 | 2.7 | 45.5 | 684 | 168 | json | ok | bytes | = |
| base | q5 | 24.0 | 0.7 | 23.3 | 390 | 124 | json | ok | bytes | = |
| base | q6 | 25.6 | 1.1 | 24.5 | 393 | 111 | json | ok | bytes | = |
| base | q7 | 28.7 | 1.2 | 27.5 | 445 | 129 | json | ok | bytes | = |
| base | q8 | 21.8 | 0.8 | 21.0 | 345 | 107 | json | ok | bytes | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| base | q9 | 21.1 | 0.8 | 20.2 | 332 | 97 | json | ok | bytes | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **base** | mean | **27.8** | | | | | | | | |
| base | agents | before==after True, ==ref True | reload - | | | | | | |
| outq4 | q0 | 30.4 | 2.9 | 27.4 | 436 | 107 | json | ok | fields | - |
| outq4 | q1 | 29.0 | 1.9 | 27.1 | 445 | 116 | json | ok | DIFF | - |
| outq4 | q2 | 23.6 | 0.8 | 22.8 | 384 | 108 | json | ok | fields | = |
| outq4 | q3 | 21.2 | 0.8 | 20.5 | 354 | 106 | json | ok | fields | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| outq4 | q4 | 46.2 | 2.8 | 43.3 | 678 | 167 | json | ok | fields | = |
| outq4 | q5 | 23.1 | 0.7 | 22.3 | 390 | 124 | json | ok | fields | = |
| outq4 | q6 | 23.7 | 1.1 | 22.6 | 382 | 111 | json | ok | fields | = |
| outq4 | q7 | 27.2 | 1.1 | 26.0 | 442 | 131 | json | ok | DIFF | = |
| outq4 | q8 | 20.5 | 0.7 | 19.7 | 345 | 107 | json | ok | DIFF | normal/normal_operation/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| outq4 | q9 | 22.4 | 0.9 | 21.5 | 355 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **outq4** | mean | **26.7** | | | | | | | | |
| outq4 | agents | before==after True, ==ref True | reload - | | | | | | |
| outq4poll | q0 | 29.9 | 2.8 | 27.1 | 463 | 114 | json | ok | fields | - |
| outq4poll | q1 | 27.6 | 1.8 | 25.8 | 445 | 116 | json | ok | DIFF | - |
| outq4poll | q2 | 22.0 | 0.7 | 21.3 | 384 | 108 | json | ok | fields | = |
| outq4poll | q3 | 20.1 | 0.7 | 19.3 | 354 | 106 | json | ok | fields | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| outq4poll | q4 | 44.8 | 2.6 | 42.2 | 684 | 168 | json | ok | DIFF | = |
| outq4poll | q5 | 21.9 | 0.6 | 21.2 | 390 | 124 | json | ok | fields | = |
| outq4poll | q6 | 22.4 | 0.9 | 21.4 | 382 | 111 | json | ok | fields | = |
| outq4poll | q7 | 26.0 | 1.1 | 24.9 | 442 | 131 | json | ok | DIFF | = |
| outq4poll | q8 | 19.4 | 0.7 | 18.7 | 345 | 107 | json | ok | DIFF | normal/normal_operation/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| outq4poll | q9 | 20.9 | 0.8 | 20.1 | 355 | 97 | json | ok | fields | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **outq4poll** | mean | **25.5** | | | | | | | | |
| outq4poll | agents | before==after True, ==ref True | reload - | | | | | | |
| poll | q0 | 28.3 | 2.9 | 25.4 | 419 | 107 | json | ok | fields | - |
| poll | q1 | 25.9 | 1.8 | 24.1 | 409 | 116 | json | ok | DIFF | - |
| poll | q2 | 22.7 | 0.7 | 22.0 | 382 | 108 | json | ok | bytes | = |
| poll | q3 | 20.8 | 0.7 | 20.0 | 354 | 106 | json | ok | bytes | sensor_fault/sensor_fault/('recalibrate_sensor',) vs sensor_fault/sensor_fault/('check_sensor',) |
| poll | q4 | 46.0 | 2.5 | 43.5 | 680 | 168 | json | ok | DIFF | = |
| poll | q5 | 22.6 | 0.6 | 22.0 | 390 | 124 | json | ok | bytes | = |
| poll | q6 | 24.0 | 0.9 | 23.0 | 393 | 111 | json | ok | bytes | = |
| poll | q7 | 27.2 | 1.1 | 26.0 | 445 | 129 | json | ok | bytes | = |
| poll | q8 | 20.2 | 0.7 | 19.5 | 345 | 107 | json | ok | bytes | normal/unknown/('monitor',) vs normal/unknown/('restart_or_reconnect_sensor',) |
| poll | q9 | 19.9 | 0.8 | 19.1 | 332 | 97 | json | ok | bytes | normal/normal_operation/('monitor',) vs sensor_fault/sensor_fault/('restart_or_reconnect_sensor',) |
| **poll** | mean | **25.8** | | | | | | | | |
| poll | agents | before==after True, ==ref True | reload - | | | | | | |
