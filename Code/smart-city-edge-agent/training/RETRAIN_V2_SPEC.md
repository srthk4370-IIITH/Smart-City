# Domain-agent retrain v2: specification (agreed 2026-10-16, 24 questions)

This is the final training of the **domain agents**. The cross-domain reasoner is separate and starts next.

## Why
The window, placement and long-range studies (HANDBOOK 2.38–2.39, `proofs/2026-10-16_*`) found:
- **Too-young events are misread.** The app asks the agent 40 min after an event starts, but training
  placed events 1–3 h into the window. Pattern accuracy is 42% at 40 min and 88% at 3 h.
- **One window length only.** The model knows only 4 h windows; other lengths drop accuracy
  significantly.
- **Some events are never caught.** Old steps, slow drifts and recurring small spikes are missed or
  misnamed.
- **Routine looks like trouble.** About 31% false alarms on calm data come from normal routines such as
  refills, load switching and daily cycles.

## Decisions
| # | Topic | Decision |
|---|---|---|
| 1 | Where | Laptop RTX 4050, **sessions of 6–8 h**, resumable. The user says "start session"; an open AskUserQuestion offers "stop", and a stop is graceful (checkpoint, clean exit). |
| 2 | Deploy | Merge, then **GGUF Q4_0 direct** (importance matrix from our own prompts), then htpd. Measure host vs device accuracy before accepting. AI Hub only as a fallback. |
| 3/5 | Run-time window | **Dynamic per incident, by severity and stage.** Early alert 4 h for all, so the alert path is unchanged. Refinements: normal 4 h, warning 8 h, critical/fault 12 h. |
| 4 | Roles | air_quality, water, power, occupancy, weather **+ new HVAC agent**. All domains, final. |
| 6 | Event age | Onset placed **uniformly from 3 readings before the end to the window start**, with extra weight on 20–60 min. |
| 7 | History in the prompt | A **12 h summary line** (level shift / drift, as in `longrange.go`) and a **recent-episodes line** (excursions beyond normal noise in 12 h). |
| 8 | Prompt hint | Window length shown ("N x 5 min"); stage NOT shown. |
| 9 | Patterns | Everything: today's 12 + recurring small spikes, old level shift, long drift, more sensor faults (bias jump, calibration drift, noise increase, dropout/gaps, saturation, quantised steps), compound shapes (dominant pattern + second observation). |
| 10 | Hard negatives | Everything plausible: tank refill/drain and pump cycles, load switching, daily cycles (temperature, CO2 with occupancy, outdoor PM), HVAC cycling, weekday/weekend schedules, and more. |
| 11 | Event size | **1.5–12× noise**. Below about 3× the label stays stable/normal with an observation, so the boundary is learned. |
| 12 | Data | No new raw data: generate from the existing series (all nodes, all months, many windows per node). |
| 13 | Output size | Same schema, **max 2 observations of ~14 words**. Target 55–60 tokens before the new fields. |
| 14 | New fields | `event_active` (bool), `onset` (HH:MM) on every finding; `fault_kind` only when status = sensor_fault (stuck, bias, drift, noise, dropout, saturation). |
| 15 | Confidence | **Calibrated**: target = expected accuracy for that age, size and pattern (placement study). |
| 16 | Wording | 10–20 local deterministic templates per pattern and cause; numbers only from the evidence. Nothing leaves the laptop. |
| 17 | Size | **~36k examples, 2 epochs.** About 36 h, so 5–6 sessions. |
| 18 | Model | Llama 3.2 3B (same NPU speed), one multi-role adapter, **LoRA r=32**. |
| 19 | HVAC | Room temperature vs setpoint band (too hot/cold for too long, slow recovery); AC behaviour (short-cycling, running without cooling, stuck on/off, running in an empty room). |
| 20 | Accept if | (a) pattern accuracy ≥ 65% at 40 min and ≥ 88% at 3 h; (b) no regression on the 54/900-window evals, JSON and policy ≥ 98%; (c) latency is **not** a gate (user, 2026-10-16): train for accuracy first, then optimise latency until it is back at or below today's; (d) fewer false alarms on calm and routine windows than today (31%). All on the QIDK NPU, test months only. |
| 21 | Hold-out | Test months (Nov–Dec) **plus ~15% of sensors per role never seen in training**; report seen vs unseen separately. |
| 22 | Spot-check | Before training: a local, private HTML review page of 60 random samples, plus automatic checks (balance, numbers match evidence, token lengths). |
| 23 | Sessions | See #1. |
| 24 | Schema | **Frozen now** (below). The backend accepts the new fields; the old model simply doesn't emit them. |

## Frozen agent output schema (v2)
```json
{"pattern": "<one of the role's patterns>", "status": "normal|warning|critical|sensor_fault",
 "observations": ["<= 2 short strings, each ending with cited ids like [E1,E4]"],
 "likely_cause": "<one of the role's causes>", "confidence": 0.0-1.0,
 "event_active": true, "onset": "HH:MM",
 "fault_kind": "stuck|bias|drift|noise|dropout|saturation (only when status = sensor_fault)",
 "action": "<derived by the backend; generation stops at this key>"}
```
- **Key order is fixed as above.** Generation stops where `"action"` starts, as it does today
  (`answerscan.go`).
- **Evidence ids:** E1–E8 as today, E9 for the 12 h summary line, E10 for the recent-episodes line.

## Latency policy (user, 2026-10-16)
- **Accuracy first.** Training is completed even if latency rises.
- **Then optimise, every time.** After training comes a latency optimisation pass, and it is not done
  until agent latency through the app is at or below today's: 13-agent batch about 14.7 s, typical
  incident about 3.8 s.
- **Expected costs and offsets.** The two history lines add about +40–60 prompt tokens (+4–6% prefill),
  while max 2 short observations offset the new fields.
- **Levers for the optimisation pass:**
  - trim templates or history lines;
  - prefix-cache the new system prompt;
  - imatrix Q4_0 tuning;
  - draft tuning for the new schema;
  - shorter observation caps;
  - htpd knobs (HANDBOOK 2.37).

## Data decisions after the first build (user, 2026-10-17)
| # | Decision |
|---|---|
| D1 | **HVAC per indoor unit**, re-extracted from `SR-AC.csv` (87 units, 2025). The app gets per-unit HVAC sensors; the floor aggregate stays a CPU context signal. |
| D2 | **Abnormal tank fills** become warning or critical when the level goes past the high limit, the fill lasts longer than normal, or fills happen off-hours repeatedly. Routine refills stay normal. |
| D3 | False alarm (acceptance d) = the agent says **status ≠ normal** on a normal window. Naming the shape correctly is not an alarm. |
| D4 | Confidence targets stay as generated (from current-model accuracy). After training, recalibrate in the backend from v2's placement-study results (a mapping table, no retraining). |
| D5 | Recurring small spikes = `spike` / normal, citing E10. Power is excluded. |
| D6 | `fault_kind` gains **`quantised`**. The frozen enum becomes stuck, bias, drift, noise, dropout, saturation, quantised. |
| D7 | Calibration-drift rules on real windows stay but are **tightened** (longer duration, higher r²). Injected drift faults stay. |
| D8 | Weather is tested on seen stations only (a stated limit). The water test also draws from held-out water sensors in Sep–Oct. |
| D9 | **AC running in an empty room is flagged** (warning) with the new action **`switch_off_ac`**. It is a recommendation that still needs human approval in the app; nothing is switched off automatically. It is trained on synthetic occupancy pairing; with no occupancy feed the prompt says "occupancy n/a". |
| D10 | HVAC uses the same series format as every other role (10-min means, any N from 24 to 144). |
| D11 | The 4 HVAC units with bad sensors all year become **real fault examples**, never normal bases. |
| D12 | Dense sampling of "unit on" HVAC windows, so running and off are balanced in training. |
