# PILOT: 30 Set B cases (stratified N=2 / 3-4 / 5+), injected faults in real held-out campus windows

Generated 2026-11-25 22:20 by pilot_score.py from `runs/pilot/records.jsonl` (one run per case: agents + reasoner on the host; cheap arm computed offline from the same agent outputs).

## Headline

- **Discordance (cheap = isolatedReport vs full = reasoner; label OR severity differs): 70.0 %** (label only 70.0 %, severity only 13.3 %). vs the fallbackReport template: 73.3 %.
- Accuracy vs the injection gold (n = 30):

| arm | label acc % | severity acc % | both % | affected-domain F1 % | missed critical |
|---|---|---|---|---|---|
| cheap | 23.3 | 80.0 | 23.3 | 45.5 | 2 / 20 |
| cheap_x | 23.3 | 83.3 | 23.3 | 90.2 | 2 / 20 |
| full | 86.7 | 93.3 | 80.0 | 82.1 | 2 / 20 |

- Oracle headroom (full right and cheap wrong on label+severity): 56.7 % of cases; reverse (cheap right, full wrong): 0.0 %.

## By stratum

| N domains | n | discordance % | full label | cheap label | full sev | cheap sev |
|---|---|---|---|---|---|---|
| 2 | 10 | 50.0 | 100.0 | 50.0 | 90.0 | 60.0 |
| 3-4 | 10 | 70.0 | 80.0 | 10.0 | 90.0 | 90.0 |
| 5+ | 10 | 90.0 | 80.0 | 10.0 | 100.0 | 90.0 |

## Runtime (host, laptop GPU, Q4_0; ONE model at a time)

- Reasoner phase wall per case: mean 12.0 s, median 12.0 s, max 15.0 s (prefill 2318 tokens, decode 559 tokens, think adaptive).
- Agent phase: 3.73 agent calls per case, 117.7 s wall in total for the whole batch (np=4 parallel slots) = 3.9 s per case amortised.
- Total about 15.9 s per case (agents amortised + reasoner). Board latency is a separate measurement (RQ1 cost needs the board).

## Health and trigger inputs on the 30

- Reasoner output valid (JSON, label and severity enums): 100.0 %; fallback template fired 0 times; think on in 100.0 % of cases; 0 tool calls (empty frozen corpus).
- Domain agent outputs rejected by the enum gate: 0.
- Trigger inputs: rules-vs-agent disagreement in 56.7 % of cases; any critical 73.3 %; agent confidence < 0.6 in 3.3 %; flagged sensors site-linked 100.0 %; the app's own rule (>= 2 domains) would escalate 100.0 %.

## Label confusion (gold -> full / cheap), counts

- weather_driven -> full weather_driven / cheap hvac_or_thermal_issue: 6
- weather_driven -> full weather_driven / cheap ventilation_issue: 5
- occupancy_driven_load -> full occupancy_driven_load / cheap ventilation_issue: 4
- hvac_or_thermal_issue -> full hvac_or_thermal_issue / cheap hvac_or_thermal_issue: 3
- weather_driven -> full weather_driven / cheap weather_driven: 3
- sensor_fault -> full sensor_fault / cheap normal_operation: 2
- occupancy_driven_load -> full occupancy_driven_load / cheap power_load_anomaly: 1
- air_pollution_event -> full air_pollution_event / cheap air_pollution_event: 1
- occupancy_driven_load -> full ventilation_issue / cheap ventilation_issue: 1
- weather_driven -> full hvac_or_thermal_issue / cheap hvac_or_thermal_issue: 1
- weather_driven -> full air_pollution_event / cheap ventilation_issue: 1
- weather_driven -> full hvac_or_thermal_issue / cheap ventilation_issue: 1
- weather_driven -> full weather_driven / cheap power_load_anomaly: 1

## Caveats (read before using any number)

- Gold comes from the injection (injected cases only; real windows are baselines). n = 30, so 95% intervals are about +-18 points; this pilot only sizes the effect.
- The cheap arm is a port of Go `isolatedReport` (unit-tested byte-exact against the Go report in proofs/2026-10-16_hw_grid/workload_INC-0407.json, the only Go-produced isolated report stored). It was designed for ONE domain: at N >= 2 it reports the lead sensor only (affected_domains = [lead role]), so low domain F1 at N >= 2 is by construction. `cheap_x` (fallbackReport port) is the natural cross-domain template; both are shown.
- Cheap-arm severity is not a field of Go's isolatedReport; it is derived as the lead finding's status (the app derives severity elsewhere).
- Rule view (rule-vs-agent disagreement, context agents) is the Python mirror of the Mode 1 rules (training/generate_dataset.py + features.py), not rules.go with per-node card thresholds; disagreement rates are therefore approximate.
- Reasoner tools answer from an empty frozen corpus (retrieval off, see LEAKAGE.md). Host Q4_0 timings are not board timings.
