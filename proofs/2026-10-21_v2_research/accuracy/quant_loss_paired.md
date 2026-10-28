# Host bf16 vs device Q4_0, paired

| metric | n | host bf16 | device Q4_0 | delta | host-only right | device-only right | exact McNemar p |
|---|---|---|---|---|---|---|---|
| json | 112 | 1.000 | 0.982 | -1.8 | 2 | 0 | 0.500 |
| pattern | 112 | 0.938 | 0.929 | -0.9 | 1 | 0 | 1.000 |
| status | 112 | 0.920 | 0.920 | +0.0 | 1 | 1 | 1.000 |
| cause | 112 | 0.884 | 0.893 | +0.9 | 0 | 1 | 1.000 |
| action | 112 | 0.902 | 0.911 | +0.9 | 1 | 2 | 1.000 |
| event_active | 112 | 0.964 | 0.946 | -1.8 | 2 | 0 | 0.500 |
| onset_15 | 112 | 0.911 | 0.920 | +0.9 | 0 | 1 | 1.000 |
| policy | 112 | 1.000 | 0.982 | -1.8 | 2 | 0 | 0.500 |
| false_alarm | 39 | 0.026 | 0.026 | +0.0 | 0 | 0 | 1.000 |

identical text 0/112; identical pattern label 110/112
roles: Counter({'occupancy': 67, 'weather': 33, 'water': 8, 'power': 4}); families: Counter({'occupancy': 67, 'event': 25, 'compound': 6, 'fault': 4, 'real_routine': 4, 'stable': 3, 'long_drift': 2, 'recurring': 1})
pattern disagreements (id, gold, host, device): ('test-weather-00344', 'exponential_increase', 'gradual_increase', None); ('test-weather-00066', 'gradual_decrease', 'gradual_decrease', None)