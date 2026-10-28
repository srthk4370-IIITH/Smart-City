# Placement study: when does the 4 h agent read an event right? (QIDK NPU, 2026-10-16)

## Why
- **When the app calls the agent.** The app calls the domain agent once a sensor has been abnormal for
  8 readings (`engine.go` `persistReadings`). The 4 h window ends at that moment, so the event sits in
  the window's last ~40 minutes.
- **Where training put events.** Earlier in the window: steps 12–36 readings before the end, slow rises
  starting in the first ~70 minutes.

## Method
- **Events:** 208 events in real calm 4 h windows from the test months, across air quality, water and
  power. There are 10 patterns, about 21 events each.
- **Placement:** each event (same base window, same amplitude and shape parameters) is placed with its
  onset d = 4, 8, 12, 18, 24 or 36 readings before the window end. That gives 1248 NPU calls, paired
  per event.
- **Runtime:** fine-tuned agent, htpd v6, 13 streams × 768. Prompts are byte-identical in format to
  training.
- **Truth:** the injected pattern; status from the training generator's labeller.
- **Code:** `training/window_study/placement_study.py`. The cases hash is in `manifest.json`; raw
  per-sample data (`samples.jsonl`, `cases.jsonl`, `prompts.jsonl`) is kept locally, not in git.

## Results: agent pattern accuracy vs time since onset
| | 20 min | **40 min (today)** | 1 h | 1.5 h | 2 h | 3 h |
|---|---|---|---|---|---|---|
| all patterns | 24% | **42%** | 57% | 67% | 76% | **88%** |
| status (all) | 57% | 62% | 71% | 74% | 79% | 86% |
| flagged at all | 73% | 77% | 84% | 90% | 89% | 95% |

**Paired tests:** every later placement beats 40 min (McNemar p < 0.0001). For example, at 3 h, 105
events are right that were wrong at 40 min, and only 9 the other way round.

| Pattern | Reliable from | Before that, the agent says |
|---|---|---|
| spike, dip | 20–40 min | best early; at 3 h a spike is often called "stable" (43%) |
| step increase/decrease | 1 h (95–100%) | spike / dip (at 20 min) |
| flatline (stuck) | 1.5 h (100%) | "stable" (0% at 40 min) |
| gradual decrease | 1.5 h (100%) | dip / stable |
| exponential increase | 1.5 h (90%) | spike |
| gradual increase | 3 h (86%) | "exponential increase" (a fresh ramp looks exponential) |
| oscillation | 3 h (100%) | stable / spike / dip (0–24%) |
| erratic | 3 h (67%) | spike / dip |

Full tables (status, flag rate, rules, what the agent called each pattern): `tables.md`. Plot:
`placement.svg`. Paired tests: `paired_tests.txt`.

## Decision (team, 2026-10-16)
1. Keep the **early alert** at 8 readings, so alerting stays fast.
2. **Re-analyse automatically at 1.5 h and 3 h** after onset. Each time, the refined finding replaces the
   early one, with the history shown.
3. Exception: an early spike or dip is kept when the refined answer is only "stable", because the event
   is over, not wrong.

## Limits
- The "onset" here is the event's true start. In the app the abnormal count starts when the rules first
  see the sensor as abnormal, which for slow events is later than the true onset. So the real delays are
  somewhat longer than 40 min, which helps.
- An injected slow rise reaches its full amplitude at the window end whatever its length, so a 20-minute
  "slow rise" is steep. Calling it exponential or a spike is then partly fair.
- n = 19–21 per pattern and placement: per-pattern differences under ~20 points are within noise.
