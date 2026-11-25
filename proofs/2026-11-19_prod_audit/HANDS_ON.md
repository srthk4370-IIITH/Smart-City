# Hands-on test + stored-incident audit (2026-11-19, board: agent s0450, reasoner p2, APK phase1j -> phase1k)

## Stored incidents (25) audit: faults FIXED in phase1k
1. False sensor_fault from the rules on an idle meter (11/25 incidents, SR-EM-KH04-01 power 0.0026-0.0027 kW):
   the flat-run check counted readings rounded to the card's 4-decimal cap, so real values 0.00264/0.00268/0.00271
   looked stuck; agent + reasoner said normal every time. Fix: features.go rawFlatRun, flatline needs the raw
   readings to repeat (tolerance = display half-step or 0.1% of the level). Same data reaches rules and AI
   (checked: rule window = agent prompt series); no slider values involved.
   Parity test: 2 of 400 Python fixtures (jittering temp plateaus) diverge on purpose (documented in parity_test.go).
2. Misleading watchdog text "no new readings for 5 min" on every fast-path critical (pH INC-0009/15/18/23) even while
   readings arrived: the AI waits for the event to last 8 readings. Text now says that.
3. (deployed in phase1j) reasoner sensor_fault only with a rule or agent fault finding (faultGuard).

## Stored incidents: found, NOT fixed (discuss / polish)
- pH probe (WM-WD-KH98-00, hourly cadence, window interpolated): fast-path critical never gets an AI analysis
  (needs 8 readings = 8 h). Polish item "AI on past readings" covers it.
- Reasoner still writes "data gaps / no judgement possible" titles on complete windows (INC-0013/14/19/22).
- Forced deploy check incidents (INC-0025, all sensors normal, opened by the deploy script) look like real ones.
- Injected demo spike reaches the rules window but not the agent's longer refine window (INC-0010: rule critical
  spike 126.6, agent window 9 h without it -> "normal"); demo-only.
- Weather rh flatline sensor_fault (INC-0022) while the window rises 41->45 %: the rule finding is from an earlier
  window; to recheck after phase1k.
- Occupancy "intermittent" -> sensor_fault by the rules (INC-0007/8) on a sensor that toggles.

## Hands-on (phone 412 px + desktop 1366 px, headless Chromium; chat app; chaos ingest) 2026-11-19 ~16:36-17:00 UTC
### Faults (fix now)
F1 /api/ingest single {"node","metric","value"} (the API's own example) went to the old slider bank: clamped
   (-5000 ppm -> 250, 1e12 kW -> 2000, pH 15.5 -> 14), answered "stored", then IGNORED by the live campus feed.
   FIXED (phase1l, server.go + ingest_single_test.go): device path with range/duplicate checks.
F2 Daily summary prints Go map syntax: "domains map[air_quality:1 power:2 ...]" (Sensors tab).
F3 Chat history dated "Sep 24" (device RTC 2023), not the corrected clock; old test sessions ("Write me a poem
   about cricket", "Close all open incidents") ship in the user's history.
F4 Chat: "why is the pH so high in KH, is the water safe?" -> "fog server unreachable, cache has nothing" although
   INC-0023 (pH 11.25 critical) is on the board. "which sensor is broken?" answered about the previous CO2 question
   (context bleed) instead of listing the faulty sensors. Hindi question answered in English. Chat says
   "approve or dismiss", the app says "I'm on it / Dismiss".
F5 Critical pH incident: "WHY IT MATTERS: Nothing abnormal was confirmed. Dismiss it with a short note" on a
   CRITICAL 11.25 pH (> 9.0); "HOW SURE THE AI IS: High - from the automatic rules (no AI)"; checklist is the generic
   water playbook ("Confirm the level sensor", "Check for leaks or overflow") for a pH alarm.
F6 Home after reboot: "ALL CLEAR / Everything within normal range / All 6 areas normal" next to "Starting up",
   "Got worse (was Normal)", "Data: 5 not reporting", "14 decisions waiting" while /api/health/data says 23 sensors
   fresh (12 h backfill done). "Got worse" for starting-up is wrong.
F7 Phone layout: area cards 2 columns too narrow -> "since 22:00 (5 min)" wraps one character per line; opening the
   gear menu scrolls the page sideways (horizontal overflow). Desktop: the header clock overlaps the MAP tab.
F8 3 of 10 demo scenarios fail ("not a live sensor": crowded_room, pump_cycling, stuck_sensor, off_hours_presence);
   tank_leak "ok" on a sensor that is stale for 2.4 h (does nothing). Injected throttle ceiling has zero noise ->
   rules call it flatline sensor_fault (demo artefact).
F9 MQTT down since the WSL restart (laptop relay: Windows cannot reach WSL :1883); board logs EOF reconnects.
   Fog upload EOF every minute (fog not added yet).
### UX nitpicks (polish)
- Incidents judged FINE still sit in "Needs decision" (INC-0024): operators must dismiss noise one by one.
- 4 separate pH critical incidents for one sensor, all "Needs decision"; no merge / reopen.
- Sheet header "DONE" (close) reads like "mark incident done".
- Header icons: "Who?", "</>", theme and gear look alike (two sun-like icons); "Engineering view" jargon.
- Map: "Site version 1 (auto, saved ...) 214 nodes 246 links", "REBUILD FROM API" (destructive) at the top,
  "B8/BE" glyphs, Football Ground "(building)", huge dotted page titles eat a third of a phone screen.
- Chat answers to "is anything wrong?" are raw counts with domain ids (air_quality, sensor_fault).

## Chat: 10 precise questions (2026-11-19 ~17:28 UTC; chat runs on this backend's htpd reasoner rsn_v3_4b_p2, prompt r3)
Only 2 of 10 answers used the NPU model (7-8 s); 8 were template lookups ("0.0 s").
C1 "No CO2 sensor at KH03 in that window" - wrong, SR-AQ-KH03-03 co2 exists (answered 687 ppm minutes earlier).
C2 Context bleed: "false alarms this week" and "when will CO2 cross 1000 ppm" both answered with the previous AC-KH03
   question's incident list. The forecast tool (chat_tools_v3 estimate) was never used.
C3 "Which sensors are not sending data?" -> "Live: no faults right now" while pH, TDS, tank level are stale and the
   water flow sensor never reported.
C4 "Which critical first?" -> oldest duplicate pH incident (INC-0018) instead of the live PM2.5 critical (INC-0026).
C5 INC-0026 (outdoor PM2.5) checklist: "inspect ventilation (fresh-air dampers, AHU fan)" - indoor playbook for an
   outdoor station; "AI report is not final yet" after an hour.
C6 "Is the KH04 meter faulty or is the room empty?" never looks at occupancy; counts 6 earlier false sensor-fault
   incidents as history.
C7 "Summarise INC-0023 for my manager in two lines" -> long template, not two lines.
C8 Vocabulary "approve or dismiss" vs the app's "I'm on it / Dismiss"; Hindi asked -> English answer.
C9 Chat list shows old test sessions and RTC dates (fixed for new sessions in phase1l).

## Models on injected scenarios (16:36 -> 17:32 UTC)
M1 Only 1 of 5 live injections produced an incident in 56 min (INC-0026 PM2.5). Its AI never ran (fast-path
   critical, a short spike never lasts 8 readings) -> preliminary rules report forever.
M2 Power throttle + load surge on SR-EM-KH04-01: 18 kW ceiling, rules "flatline sensor_fault" for 10 readings, no
   incident (an open incident on that sensor already exists, "Needs decision" since 21:15). A real event can hide
   behind an old unresolved incident on the same sensor.
M3 Ventilation failure (CO2 exp rise) and heat build-up: slow injections, still normal after ~1 h.
M4 Tank leak injection accepted on a sensor stale for 2.4 h (no effect, no warning to the user).
