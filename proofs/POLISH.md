# Polish list (owner, after execution)
- 2026-11-19 (owner): when the AI analysis times out for lack of fresh readings (e.g. rare-cadence pH fast path, INC-0009/INC-0018), do NOT just stop: run a base AI analysis on the past readings available (history window, last readings, context sensors) and give an AI verdict marked "limited data". AI reasoning on every alert is the core of the project.
- 2026-11-19 (owner): rare-cadence sensors (pH) -> AI on past readings when fresh readings stall: POLISH (not now).
- 2026-11-19 (owner): near-zero flat meter (3 W standby repeating) -> sensor_fault: leave to the new reasoner for now; discuss rule ("idle or stuck" warning + second-evidence) in polish.
- 2026-11-19: reasoner "data gaps / insufficient data" verdicts with 1/48 missing -> re-check after p2 reasoner deploy.
- 2026-11-19: agent tool calls = 0 on board so far; verify tool path in real incidents (and call recall ~40%).
- 2026-11-19: fog upload server (owner adds later).
