# Refined re-analysis + 12 h checks, through the app on the QIDK (2026-10-16)

Tool: `app/tools/refine_check.py`. Method: restart the sensor clock once (1 s polls), build 45 readings of
history, then inject scenarios one after another without a reset. Real NPU (htpd v6, fine-tuned agents).
Raw per-stage incident JSON: `device/`, `device_run2/` (`refine_check.jsonl`, `INC-*_<stage>.json`).

## Run 1 (before the 12 h severity rule)
| scenario | early | 1.5 h | 3 h |
|---|---|---|---|
| stuck_sensor | flatline / sensor_fault | same | same |
| tank_leak | stable / normal | stable / normal; **12 h: slow drift -64.7 (32x)** | same; severity stayed normal (gap found) |
| pm_spike | spike / critical | same | same |

## Run 2 (12 h finding raises a sensor its agent called normal to warning, title.go longRangeRaise)
| scenario | early | 1.5 h | 3 h |
|---|---|---|---|
| tank_leak | stable / normal | **warning: "Tank level slow drift (12 h view)"** | warning |
| ventilation_failure | exponential_increase / warning (12 h: level +187 ppm) | spike / critical | spike / critical |
| power_throttling | exponential_increase / critical | **throttling / critical** (correct) | step_decrease / critical |

3/3 incidents reached the 3 h stage in both runs; stages ~18 s apart at 1 s polls.

## Notes
- **12 h checks fire only after 8 h of history.** At the early stage there were about 65 readings since
  the clock restart, so they were not active yet. In the field, history is continuous.
- **Demo scenarios end after 30 readings (2.5 h, Hold=false).** By the 3 h stage the event is over, so
  the agents describe a rise and its end ("spike", "step decrease"). Power then still says "critical"
  though the level is back to normal.
- **The stress test (`stress_app.py`) resets the clock between scenarios.** That drops pending
  refinements by design ("sensor history is gone"), so it cannot test refinements. 129/135 checks; the 6
  failures are thermal (95–96 °C on all three chaos runs).

## Run 3: keep the worst severity + demo scenarios hold until cleared
| scenario | early | 1.5 h | 3 h |
|---|---|---|---|
| power_throttling | exponential_increase / critical | **throttling / critical** | **throttling / critical** (stable now that the event holds) |
| ventilation_failure | exponential_increase / warning | exponential_increase / **critical** | throttling / critical (CO2 held at its peak: a rise then a plateau) |
| stuck_sensor | flatline / sensor_fault | same | same |

Raw data: `device_run3/`. 3/3 incidents reached 3 h.
