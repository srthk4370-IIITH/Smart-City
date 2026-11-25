# Chat router: template vs reasoner (2026-11-20)

Code: Code/smart-city-edge-agent/app/backend/chat*.go (chat_polish.go is new). Order in chatStore.answer:
v25 router -> older router -> (open question with tool data) reasoner -> template fallback. Every answer then goes
through chatFinish (plain words + asked format).

## Answered by template (lookup, no NPU, "How I found this" tool shown)
- Current reading / value of a sensor, metric or place ("CO2 in KH level 03", "how is the tank").
- Peak / lowest of a metric in a period, with its time ("highest CO2 in KH level 03 in the last 4 hours and when").
- History / trend of a sensor over a span; average, min, max.
- Sensor health of one named sensor; which sensors are faulty; which sensors are NOT sending data
  (data-health stale/missing, same logic as /api/health/data).
- Incident counts, lists, open / waiting for decision, per domain / severity / building, any span; false alarms
  (outcome false_alarm or dismissed); dismissed vs approved counts.
- "Which critical first": open incidents ranked by severity, then still flagged now, then newest; same-sensor duplicates collapsed.
- Forecast "when will X cross N": straight-line estimate over the last 2 h (chatFit), a time, "not rising" or "already above".
- Facts of one incident by id (status, who handled it, how long); glossary ("what does TDS mean"); what-if with a target
  value against the alert limits; failure scenarios ("how fast would we know").
- Refusals: actions (close / dismiss / change setpoint), prompt injection, out-of-scope, future weather.

## Sent to the reasoner (NPU chat model) with the template answer as facts
Condition: the question is open (why, how come, should I / we, what should, explain, summarise, compare, is it safe,
do I need, recommend) AND the template produced an answer with tool data AND no output format was asked.
The facts are appended as "[Facts already read from the device: ...]"; the model may still call tools.
If the NPU is busy (another chat or an alert analysis) or fails, the template answer is returned at once.
- "why is pH so high, is the water safe?" -> facts = on-board incident + root cause + reading + alert limits; the fog
  lookup is only mentioned once as "unavailable" when the fog is down.
- "should I worry about INC-0023", "explain what happened", "compare KH and PB CO2", "summarise the week".
- Questions no template recognises (free-form, multi-step, cross-domain) go to the reasoner without facts, as before.

## Stays template even if open
- Asked format: "in two lines", "in one line", "short", "for my manager", "in simple words" -> template, trimmed to
  N sentences (chatFormatAnswer); plain words drops rule thresholds and the "ask why" hint.
- Refusals and answers without tool data (glossary).

## Answer wording rules the training data should follow
- Buttons are "I'm on it" and "Dismiss" (never "approve or dismiss").
- No internal ids in text: air_quality, sensor_fault, power_kw, S1.E4 rule refs; say "air quality", "sensor fault".
- Outdoor stations (weather, outdoor air): no AHU / damper / fresh-air / ventilation advice.
- A new topic (false alarms, forecast, which first, silent sensors) never reuses the previous turn's incident or sensor;
  only "and yesterday?", "why?", "that sensor", "those" do.
- Follow-up chat sessions older than 30 days are archived (state/chats_archive.json); POST /api/chat/sessions/clear clears all.
