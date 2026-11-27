# Hands-on sweep of the live app on the QIDK (2026-11-26 22:50 -> 2026-11-27 night)

Board: QIDK SM8650, app phase1q + this sweep's fixes, htpd_v9h, agents `agt3_s0450_q4_0`, reasoner `rsn_v3_4b_v5_q4_0`
(prompt v4, adaptive thinking). The board is off the campus network (campus API, MQTT and fog relays unreachable), so
readings were fed through `POST /api/ingest` exactly as a gateway would (owner-approved: full faults, state restored
afterwards). Raw logs: `feeder.log` / `incidents_log.jsonl` (run 1, before the fixes), `feeder2.log` /
`incidents2_log.jsonl` (run 2, after), `chat_battery.jsonl`, `tele.log` (thermals), `ui/*.png`, `api_get.json`.
State backup `state_backup.tgz`; the board's sweep state is kept as `state_sweep1127_*`.

## 1. How a reading becomes a report (step by step, as the code runs it)

1. **Input.** Readings arrive from the campus API poller (`campus.go`, every 5 s, 12 h backfill), MQTT (`prod_mqtt.go`),
   or `POST /api/ingest` (`dataquality.go IngestReading`). Each reading is checked: known sensor, a number, inside the
   sensor's physical range, not a duplicate timestamp, not in maintenance; a device clock that is unset or ahead is
   replaced by the arrival time (marked "uncertain"). Readings older than retention are rejected; late ones merge into
   closed 5-minute buckets ("late").
2. **Bucket tick** (`engine.go Tick`, every poll). In live mode the engine advances one 5-min bucket per real 5 min
   (catch-up after a stall: up to 160 buckets, history only for anything older than 1 h).
3. **Rules per sensor** (`detect`). For every sensor: the 4-hour window (48 buckets; coverage gate, critical readings
   may bypass a gap) -> `RuleFinding` (pattern: stable / spike / dip / step / gradual / exponential / flatline /
   erratic, status normal / warning / critical / sensor_fault, likely cause). HVAC context sensors only get 1 h
   averages. A single-reading glitch is removed before judging. Maintenance silences a sensor; a snooze lets only
   critical through. ISA-18.2 style deadband/off-delay stops a value hovering at a limit from flooding.
4. **Gate** (when does the AI run). Three ways out of `detect`:
   - **Fast path:** 2 consecutive readings beyond the CRITICAL limit -> an incident opens at once with the rules report
     (`fastpath.go`), AI follows.
   - **Batch:** a sensor with 4 abnormal readings in its last 8 opens a batch; the batch waits 3 more readings (up to
     10) for co-occurring sensors, then closes and every abnormal sensor in it is "alerted".
   - **Rises:** an already-alerted sensor whose rule status rises (2 readings) re-asks its incident.
5. **Routing of candidates** (`reason.go HandleCandidates`): event-mode (alarm flood in one building = one
   incident) -> fast split -> **promotion** (a candidate whose sensor belongs to an OPEN incident joins it instead of
   opening a new one) -> NEW (this sweep) **split of unrelated sensors** into separate incidents -> one NPU queue
   (pending batch, jobs, promotions, early AI, refinements, in that priority). A hot board (NPU >= 88 C / skin >= 60 C)
   queues the work and resumes when cool.
6. **Incident analysis, Mode 3** (`Process` -> `analyse`):
   1. incident persisted as "running" (survives a crash), preliminary report from retrieval + rules shown at once;
   2. **orchestrator**: each flagged sensor -> its domain agent on the NPU (htpd, `agt3_s0450`, ~3 s each, one after
      another); related context sensors -> "context agents" = their rule findings on the CPU; invalid agent answers are
      re-run alone once; an unsure agent may ask for a longer window (`askMoreData`);
   3. **routing to the reasoner**: NEW (2026-11-26) if every flagged agent AND rule says normal -> deterministic normal
      report, no reasoner; otherwise the v3 reasoner writes the report (single-domain incidents too);
   4. **reasoner** (`reasoner_v3.go`): v4 prompt (site tree, MEMORY of past incidents, evidence ids per sensor), htpd
      swaps the reasoner in (~3 s), adaptive thinking, at most one tool round, title and severity streamed to the UI as
      soon as they are decoded;
   5. **policy gate** (`checkReportV3For`): JSON, enums, evidence ids exist, numbers exist in the input, checklist
      actions whitelisted, action floor for critical, no actuation language. Repairs instead of rejections where safe
      (trailing comma, NEW: over-long title, trimmed lists);
   6. **guards**: pH wording, severity guard (the reasoner may not call "normal" what the rules call warning/critical),
      fault guard, coverage check (every alerting sensor mentioned; NEW: missing ones get a line, no 45 s retry);
   7. invalid report -> deterministic cross-domain report from the validated agent findings.
7. **After the report**: severity becomes the reasoner's (`finaliseSeverity`), the retrieval index learns the report,
   refinements are scheduled at 1.5 h and 3 h of sensor time (`refine.go`: the agents and reasoner re-read longer
   windows; severity may be elevated or curbed only when AI and rules both agree), the workflow checklist is built
   (`workflow.go`: needs_decision -> acknowledged "I'm on it" -> steps done / not needed -> closed with an outcome).
8. **Alerts** (`prod_alert.go`): critical (fast path / reasoner / rules) and operator approvals go to the configured
   webhooks/SMTP; persistent queue, retries 15 s..15 min, dropped after 24 h; unacknowledged criticals re-sent after
   15 / 30 / 60 min (the last also to the backup contact); flood guard 30/h.
9. **Fog**: reports, decisions and health (never raw readings) go to the fog outbox -> relay / Supabase.
10. **Chat** (`chat_router_v25.go`, `chat.go`): intent by question type (readings, health, incidents, actions,
    out-of-scope; English + Hinglish + typos) -> deterministic answers where possible (0 ms) -> otherwise the same
    4B model with read-only tools (sensor history, incidents, site tree, knowledge cache) -> answer checker (ids must
    appear in tool results; the period asked for must be the one read).

## 2. What was measured live (run 1, before the fixes)

| step | measured |
|---|---|
| agent call (NPU) | 2.8-3.6 s each, first token 0.4-0.7 s, 145-176 tokens; run one after another |
| reasoner report | 26.6 s (1 sensor) to 35.2 s (3 domains); swap-in ~3 s |
| fast-path incident (PM2.5 critical) | opened at the 2nd critical reading; full AI report 29.5 s later |
| multi-domain incident INC-0015 | 90.3 s: agents 10 s + reasoner 35 s + coverage retry 45 s (then discarded) |
| workflow API (ack / close) | 28-68 ms |
| chat, deterministic answers | 0-0.1 s |
| chat, model answers | 5-11 s |
| board temperature | 50-83 C peaks during reports; ~4.4 GB free RAM; no thermal hold |

## 3. Problems found and what was done

| # | problem (seen live) | fix (deployed) |
|---|---|---|
| 1 | A new critical pH episode was absorbed by a 6-day-old open incident: "promotion re-check: no change", no new incident, no alert | an incident open > 24 h no longer absorbs a new episode of its own sensor (`promote.go`) |
| 2 | Unrelated sensors on campus batched into one incident (KH tank pH + KH level-03 heat; outdoor PM10 + SB00 power factor); reasoner invented links ("dust ingress ... power factor") | candidates split by site-tree relation into separate incidents; only related young sensors hold a batch open (`batchsplit.go`, `batch_split=0` = old way) |
| 3 | A power-factor WARNING waited 42 min because unrelated young sensors kept the batch open | same as 2 |
| 4 | Coverage retry: +45 s, still missed the sensor, the good AI report was replaced by a weaker template | keep the AI report, add one line per missing sensor, no second NPU call (`coverage_retry=1` = old way) |
| 5 | Whole valid AI report rejected for a title over 80 characters | title shortened at a word / clause boundary (repair) |
| 6 | A sensor reported for high CO2 that then read an impossible 300 ppm was not re-armed for 4 h (no fault incident) | a new sensor_fault status re-arms an alerted sensor (`engine.go`) |
| 7 | With a campus URL configured, readings from MQTT / ingest were "missing" in data health, chat and the "No data available" full-screen page (which hid an open critical incident) | data health uses the engine's own update time; `/api/campus/status` counts a live ingest feed (`phase1.go`) |
| 8 | "No data available" page came back on every resume, with a cut Go error text | dismissal remembered for 1 h; short human reason instead of the raw error (`phase1.js`) |
| 9 | "Reconnecting ... values may be stale" banner on every screen wake (WebView timers pause) | grace period + immediate refresh on `visibilitychange` (`app.js`) |
| 10 | UI times from the board's 2023 RTC: "Since 22 Sep", "detected 00:09 (just now)" for a 23:40 incident; timeline lines stamped 19:20 | `/api/status` now carries the corrected `now_unix`; the UI applies the skew; every timeline stamp uses the corrected IST clock |
| 11 | "Next check at 1.5 h · in ~36 s" (demo replay speed assumed) | live mode: ETA = remaining sensor seconds (`live` flag in status) |
| 12 | Android Back on an open incident left the app | Back closes the top sheet, then returns Home, then leaves (`MainActivity` asks the page first) |
| 13 | "OFFLINE" overlapped the page title | shown on its own line |
| 14 | Hero counters "0 critical" next to "3 critical incidents open"; "19 sensors" vs 27 | labels "Critical now / Warning now / Faulty now / Sensors watched" |
| 15 | Closed incidents told the operator to "dismiss it"; "that fix did not hold" after an automatic no-action close | texts depend on state / outcome |
| 16 | Chat "status of the campus" -> "the device has no site tree" | generic words (campus, site, all ...) resolve to the campus root |
| 17 | Chat "latest critical incident" returned an older closed one; "waiting for a decision" said none (the newest incident had exactly the current bucket time, excluded by an exclusive end) | spans that end at now include now |
| 18 | About page said "Llama 3.2 3B ... Genie"; `/api/status` models wrong | real models from the htpd profile (agt3_s0450, rsn_v3_4b_v5, prompt v4, adaptive) |
| 19 | Template report printed "(S7): stable" with no sensor name | names for HVAC context metrics |
| 20 | agent.log: ~750 identical fog failures, a campus line every 10 s | repeated failures logged once per 10 min with a count |
| 21 | htpd profile re-read from disk on every call | cached by size + mtime |

Not changed (needs the owner or training data): see `questions.md` (model wording errors, weak incident chat
follow-ups, stale-incident policy, board clock / NTP, relays).

## 4. Verification after the fixes (run 2, `feeder2.py`, same board, state restored first)

| check | before (run 1) | after (run 2) |
|---|---|---|
| critical pH while a 6-day-old pH incident is open | absorbed, no incident, no alert | new INC-0015 (fast path 01:50, AI report 24.3 s), alert queued `INC-0015\|critical` |
| unrelated warning (feeder pf) at the same time as a KH03 heat event | held 42 min, merged with PM10, invented link | own incident INC-0016 after ~20 min (the 4-of-8 rule), report 31.5 s |
| CO2 impossible 300 ppm after an earlier high-CO2 episode | never alerted | INC-0018 raised to sensor_fault at the 2nd fault reading (rise path) |
| coverage miss | +45 s retry, AI report discarded | not hit in run 2 (unit test: AI report kept, 1 reasoner call) |
| data health with ingest feed | 27 "missing" | "every one of the 27 sensors checked has sent data within the last 30 minutes" |
| "No data available" page | shown over a live critical incident | not shown while readings flow; shown (with "network unreachable") once they stop |
| Android Back on an open incident | left the app | closes the incident, stays in the app |
| chat "status of the campus" | "the device has no site tree" | "The campus is normal ... top incident INC-0001" (10 s) |
| chat "latest critical incident" | older closed INC-0009 | INC-0015 (the newest) |
| chat follow-ups ("why?", "sensor fault or real?") | (run-1 test reused no chat id: my harness) | answered from the incident ("a real water quality event") |
| log | fog line every minute, campus every 10 s | one line per 10 min with "(repeated N more times)" |

Still weak in run 2 (see `questions.md`): the reasoner called a corroborated room heat-up a "sensor jump"
(INC-0017; AC on/off context added since); a stuck TDS needs 80 min before it is a fault; some incident chat
follow-ups pick the wrong incident (place / history / urgency).

Deployed: APK `b6b6e131` (edge-agent `3275c3b0`), `htpd_profile` unchanged. Rollback: `adb install -r -d
deploy/pre_sweep_a22142b5.apk` and restart. Go tests: all pass (`go test .`, 220 s), plus new tests
`TestReasonerCoverageAddsLines`, `TestAllNormal`, `TestTrailingCommaRe`.
