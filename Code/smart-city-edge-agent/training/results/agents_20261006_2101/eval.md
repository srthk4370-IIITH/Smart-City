# Agent evaluation (held-out Nov-Dec 2025 windows, host 4-bit)

Plan A: roles air_quality, water, power, occupancy, weather; 150 examples.

| role | model | JSON valid | pattern | status | cause | action | evidence ok | out tokens |
|---|---|---|---|---|---|---|---|---|
| air_quality | tuned | 1.0 | 0.967 | 0.967 | 0.967 | 0.967 | 1.0 | 90.6 |
| air_quality | base | 1.0 | 0.067 | 0.133 | 0.033 | 0.067 | 0.4 | 218.1 |
| air_quality | rules (Mode 1) | - | 0.633 | - | - | - | - | 0 |
| water | tuned | 1.0 | 0.967 | 0.867 | 0.867 | 0.767 | 1.0 | 85.5 |
| water | base | 0.967 | 0.133 | 0.5 | 0.233 | 0.333 | 0.3 | 210.2 |
| water | rules (Mode 1) | - | 0.6 | - | - | - | - | 0 |
| power | tuned | 1.0 | 0.867 | 0.833 | 0.9 | 0.867 | 1.0 | 90.5 |
| power | base | 1.0 | 0.1 | 0.4 | 0.133 | 0.167 | 0.167 | 220.0 |
| power | rules (Mode 1) | - | 0.533 | - | - | - | - | 0 |
| occupancy | tuned | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 66.8 |
| occupancy | base | 1.0 | 0.5 | 0.2 | 0.367 | 0.1 | 0.433 | 127.0 |
| occupancy | rules (Mode 1) | - | 1.0 | - | - | - | - | 0 |
| weather | tuned | 1.0 | 0.9 | 0.967 | 0.933 | 0.933 | 1.0 | 85.7 |
| weather | base | 1.0 | 0.2 | 0.233 | 0.133 | 0.467 | 0.433 | 218.3 |
| weather | rules (Mode 1) | - | 0.633 | - | - | - | - | 0 |
| ALL | tuned | 1.0 | 0.94 | 0.927 | 0.933 | 0.907 | 1.0 | 83.8 |
| ALL | base | 0.993 | 0.2 | 0.293 | 0.18 | 0.227 | 0.347 | 198.7 |
| ALL | rules (Mode 1) | - | 0.68 | - | - | - | - | 0 |
