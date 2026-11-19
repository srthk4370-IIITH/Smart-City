# Board chat sweep and deploy23 (2026-11-01)

**Method.** 40 operator questions (questions.json: counts, lists, sensor status, why, what-if, maintenance, follow-ups,
Hindi-English, typos, out-of-scope). They were asked on the board through the app (`/api/chat` via `adb shell curl`), one
at a time, with the board at 60 C or less before each (max thermal zone, as chaos2.py temp_c). Same letter = same chat
session. Script: sweep.py / run_sweep.sh. Raw data: sweep1.jsonl (deploy22 r3) and sweep2.jsonl (deploy23). Incident,
sensor and status snapshots were taken at the start and end (inc_sweep*_*.json). Grades: grades1.json / grades2.json,
scored with grade.py. Each answer was checked against the app's own data (/api/incidents, /api/sensors, /api/live).

**Board state during the sweep.** All 27 sensors were set through the API (sliders), then left alone. After 15 min of
wall time with no update, `heldStale` stops recording them: quality is "stale" and there are no readings. The replay
clock runs at 5 sensor-min per second. Incident data was stable during each sweep (start and end snapshots match).
All count answers matched the data: 3 today, 0 critical in 7 d / 30 d, 0 water this month, 1 approved in 7 d,
6 SR-AC-KH02-24 this month, 18 needs_decision.

## Before (deploy22 r3): 27/40 pass (67.5 %), median latency 9.7 s, 0 errors, 0 busy

| class | questions | what went wrong |
|---|---|---|
| C1 action request not refused | 33 | "Close all open incidents." matched the open-incidents route and listed 18 incidents. It never said it cannot close anything. |
| C2 one-incident questions on the model | 16-20 | 10-14 s each. #20 printed `get_incident(id="INC-0605")` as plain text and gave no answer. |
| C3 faulty / maintenance misses pending sensor faults | 10, 24 | Said "no faulty sensor" and "no sensor needed maintenance (30 d replacements)", although 11 sensor-fault incidents (SR-AQ-KH03-03 CO2 x8, WE-VN04-00 temp x3) were waiting for a decision. |
| C4 silent sensors reported as live | 12, 13, 14, 29, 31 | "Right now: 596.3 kW (fine)" for a sensor that has recorded nothing for hours. |
| C5 router gaps go to the model | 11, 22 | Highest CO2 with no readings: empty ranking, model, 16.6 s, invented node S00001. A setpoint what-if was not parsed, so the model called search_knowledge and gave no answer. |
| C6 raw floats from list_sensors | 14, 29 | Values like "299.7486223143493". |
| C7 weak summaries | 26, 38 | "1 incidents were approved" with no list. Overall health: "39 open" (domain_health counts resolved incidents) against 18 waiting elsewhere, with raw domain ids. |

The other 27 answers were correct: counts, follow-ups ("which ones?", "and for water?"), what-if occupancy/power, typos,
Hindi count, forecast and poem declined.

## Fixes (Go backend only; reasoner, htpd, ggml-hexagon unchanged)

- `chat_router_ops.go` (new): routes tried before the others, all answered from the existing read-only tools.
  - C1 `chatActRe` (close/approve/dismiss/delete/reset/switch...): a refusal plus how many incidents wait for a decision.
  - C2 one INC id, or "it/this" with why/what-should/real/details after an answer naming exactly one incident:
    `get_incident` with a template (root cause, flagged sensors with pattern and fault kind, open checklist text,
    workflow state). Variants: realfault and do.
  - C3 "sensors need maintenance/repair": `faulty_sensors` (act maint). The faulty answer adds the sensor-fault
    incidents still waiting for a decision, grouped by sensor; maint also lists silent sensors.
  - C7 "approved/dismissed" lists go to `find_incidents` / `count_incidents`. Approval is the filter that already existed.
    Overall health goes to `open_incidents` (act health) with the most urgent incident, live faults and silent sensors.
  - C4 `chatAugment`: current_levels items whose sensor quality is stale now say "no new reading (sensor silent: ...);
    last value X".
  - C5 `chatSaySilentRank`: when a ranking is empty and the metric's sensors are silent, the answer says so.
- `chat_router.go`: `chatRoute.Act`. chatRouteQuestion calls chatRouteOps first. chatRouted augments the result and
  falls back to the silent-rank answer. The current_levels and faulty_sensors texts were extended. chatCurrentRe gained
  Hindi `kya hai` / `abhi`.
- `chat_peak.go`: setpoint metric words (C5 setpoint what-if).
- `chat.go` list_sensors: `last` is rounded with chatRound (C6). The training parity fixture still matches.
- Tests: `chat_router_ops_test.go` (TestChatRouteOps 26 cases, TestChatRoutedOpsAnswers, TestChatListSensorsRounded).
  One old case changed: "Tell me more about INC-0441" is now routed. `go test ./...` ok (go_test.txt).
  TestDQGlitchFilterGateOnly failed once in a full run and passed 20/20 alone and in the next full run. That code is
  untouched here, so this is a pre-existing flake.
- Build: app/build.sh + android/build_apk.sh -> SmartCityEdge.deploy23.apk (build.log).

## Deploy23 (proofs/2026-10-29_latency/deploy23.sh, deploy23/STATUS*.md)
- r1 APK 08f00baa: the new app started, but the deploy's ready check timed out. The app rotated htpd.log on start, so
  the fresh log had 1 ready line, the same as the old count. Auto rollback to deploy22 r3. Fix: the ready check now
  counts ready lines after the log's previous end (or any, if the log shrank).
- r2 APK 08f00baa: **LIVE**. chaos 2 rc=0, fastcheck 6.3/5.7 s, AI 27.3/27.4 s, chat check 5/5 (refusal and INC-0605
  answers routed, 0 s).
- r3 APK ddcd2844 (r2 + one missing space in the "what should I do" incident answer): **LIVE**. chaos 2 rc=0, fastcheck 5.7/5.7 s, AI 27.5 s. Rollback deploy23/known_good (= r2).

## After (deploy23 r2, same 40 questions): 39/40 pass (97.5 %), median latency 0.2 s wall (0.03 s server; deploy22: 9.7 s)
- 22 of 40 questions are now answered by the router in under 1 s (deploy22: 11). The 18 model answers have a median of 9.4 s.
- Errors 0, busy 0. Every count answer matched the app's data (55 critical in 7 d, 77 water this month,
  72 approved in 7 d, 46/46/41/40 critical per domain, 20 waiting).
- The board state differed from sweep1: chaos/fastcheck reset the clock to 15 Oct and the sensors were live at first,
  then went silent 15 min later. Both cases were seen: #12/#13 gave live values with today's range; #29/#31 said
  "no new reading (sensor silent: no reading for 1355 min ...); last value ...".
- Remaining failure: #40 "and for water?" (model). It repeated its previous per-domain ranking instead of giving the
  water count; the water number was in it. Sweep1 answered the same follow-up correctly, so this is model variance.
  Minor, unchanged: "which building" answered with a node, raw domain ids in model answers, and the model's 9-10 s for
  plain counts.
