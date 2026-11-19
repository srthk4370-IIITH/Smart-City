# Held-out chat sweep and deploy24 (2026-11-01)

**Why.** deploy23 was fixed on 40 questions (sweep1 -> 39/40). To check for overfitting, 40 NEW questions were written
(questions_heldout.json), worded unlike sweep1: follow-ups, Hindi/Hinglish, typos, cross-domain comparisons, time
ranges (48 h, 2 days, 20-25 Oct), unknown sensor/building names, out-of-scope asks, unsafe actions, prompt injection.
They were asked on the board through the app (`/api/chat` via `adb shell curl`, sweep.py, same as sweep1), one at a
time, with the board at 60 C or less before each. Same letter = same chat session.
Truth: incident snapshots taken at the start and end of each run (inc_sweep*_*.json) + the sim time of each question
(truth3.py / truth4.py / truth5.py -> truth*.json). The app's tool results were checked against them.
The sim clock runs at 5 sensor-min per wall second, so "today" / "48 h" move between questions; truth is computed at
each question's sim time.

## Before: deploy23 r3 (APK ddcd2844), sweep3_heldout.jsonl, grades3_heldout.json
**25/40 pass (62.5 %), median latency 10.2 s** (27 of 40 answered by the model, median 10.7 s), 0 errors, 0 busy.
The held-out score is well below sweep1's 39/40, so deploy23 was partly fitted to its 40 questions.

| class | questions | what went wrong |
|---|---|---|
| T time spans | 1, 2, 3, 4, 29 | "past 2 days" -> model tried preset last_2d (does not exist), then said "215 in the past 7 days". "48 hours" -> last_24h. The follow-ups kept the wrong window (truth 8 air-quality incidents, 4 pending; answered 0 / 0). "Kal ... aaye the" (yesterday) -> 7 days, 51 (truth 0). |
| P priority + follow-ups | 15, 16, 17 | "Which incident needs my attention first?" listed 22 incidents by domain and named none, so "explain why" gave 30-day severity counts and "is it a real problem?" gave air-quality domain health. |
| S state without "now" | 6, 10, 30 | "Anything wrong with the feeder power factor?", "wind sped on the roof?", "is the tank about to overflow" -> lists of old incidents, no current reading. |
| W what-if target | 23 | "What if outdoor temperature rises to 42 C?" was declined as out of scope. |
| N sensor described in words | 25 | "KH level 2 AC unit 24" -> invented node KH-AC-002, metric tank level, "no incidents" (SR-AC-KH02-24 has 96 in 30 d). |
| H Hindi faulty | 8 | "kaunse sensors kharab hain" -> "no sensor fault today", while 15 sensor-fault incidents waited for a decision. |
| L list size | 27 | "Show the 3 most recent critical alerts" showed 5. |

Passed: refusals (approve / turn off ACs / disable alarms), out-of-scope (VC, translation), prompt injection (no
secret), unknown sensor and building, INC-9999, dates 20-25 Oct and the follow-up, dismissed this month, compare
weeks, what-if flow halves, Hindi pH, typo TDS, PM2.5 safe, latest weather incident + what to do.

## Fixes (Go only: app/backend; reasoner model, htpd, ggml-hexagon unchanged)
- `chat_router_v24.go` (new):
  - `chatTimeOf`: "last/past N hours/days/weeks" (digits or words) -> a relative span. It becomes from/to at the
    device's time. 24 h / 7 d / 30 d map to the existing presets. Hindi `aaj` = today; `kal` + past verb = yesterday
    (also added to chatPeriods).
  - Plain counts over a period ("how many [domain/severity/metric] incidents <period>", English or `kitne`) are
    routed to count_incidents. The answer gives the window: "0 HVAC incidents in the last 2 days (2026-10-15 01:30 to
    2026-10-17 01:30)". Groupings, comparisons, "most", real-vs-fault and decision words still go to the model.
  - Follow-ups after a routed count ("and air quality?", "which of those are still pending?", "how many of them were
    critical?") reuse the previous filters and change what the new question names. Pending = workflow needs_decision
    (new optional `workflow` filter in chat.go filter()).
  - "summary / overview / recap of <period>": totals by severity and by domain, the newest incident, and how many
    incidents wait for a decision.
  - "which incident first / most urgent / priority": names exactly one incident (worst severity, then oldest), so
    "explain why" / "is it real?" follow up on it. Short follow-ups without a pronoun ("explain why") now count.
  - What-if with a target ("rises to 42 C"): change_abs = target - the driver's latest reading. It needs exactly one
    matching sensor; "outdoor" = weather. Occupancy (0/1) targets stay with the model.
  - `chatWithNode`: "KH level 2 AC unit 24" -> "(sensor SR-AC-KH02-24)" when exactly one node matches the building,
    level, unit number and domain. The level/unit words are dropped from the text the router and model see.
- `chat_router.go`: state questions about a metric without "now" (state words or 5 words or fewer; not
  faulty/limits/replaced) -> current_levels. "the 3 most recent" limit. Hindi `kharab` -> faulty_sensors.
- Tests: `chat_router_v24_test.go` (TestChatRouteV24 35 cases, TestChatWithNode, TestChatRoutedV24Answers).
  Changed tests: "How many incidents were there today?" is now routed. The queue test uses a question the router does
  not take. `go vet` + `go test ./...` ok (go_test24.txt).

## Deploy24 (proofs/2026-10-29_latency/deploy24.sh, deploy24/STATUS*.md; auto-rollback on chaos/fastcheck only)
- r1 APK 48820db3: LIVE 13:33 IST. chaos 2 rc=0, fastcheck x2 pass (fast 5.8/5.7 s, AI 27.6/27.4 s), chat check 5/5.
- r2 APK 75d0f758 = r1 + "still pending" means waiting for a decision (r1 used approval=pending: 24 vs 14 truly
  waiting) + node hint drops the level/unit words. **LIVE 14:14 IST.** chaos 2 rc=0, fastcheck pass (fast 6.5 s,
  AI 28.0 s), chat 5/5. Rollback: deploy24/known_good (= r1); deploy23/known_good holds the deploy23 r2 APK.

## After
| run | build | questions | pass | median latency | model-answered |
|---|---|---|---|---|---|
| sweep3_heldout | deploy23 r3 | held-out 40 | 25/40 (62.5 %) | 10.2 s | 27 (median 10.7 s) |
| sweep4_heldout_after | deploy24 r1 | held-out 40 | 39/40 (97.5 %) | 0.02 s | 14 (median 10.8 s) |
| sweep5_heldout_r2 | deploy24 r2 | held-out 40 | 39/40 (97.5 %) | 0.02 s | 14 (median 10.1 s) |
| sweep6_d24 (regression) | deploy24 r2 | sweep1's 40 | 40/40 (100 %) | 0.02 s | 12 (median 10.2 s) |

- Counts checked against truth at each question's sim time (truth5.json): summary 56 in 48 h (56); air quality 46
  (46), waiting for a decision 16 (16); HVAC 48 h 0 (0); HVAC yesterday 0 (0); top-3 critical = 3 shown.
- Regression: sweep1's 40 questions still pass on deploy24 (sweep2 on deploy23: 39/40). "and for water?" is now
  right. Minor, unchanged: "which building" answered with a sensor; raw domain ids in model rankings.
- Remaining failure, #25: the node is now right (SR-AC-KH02-24), but the model filtered metric `ac_on` while its
  incidents are `room_temp`, so it said "none". This is the model's own choice of argument, seen once. Not fixed.
- Caveat: the "after" held-out score uses the same 40 questions the fixes were designed from, so it is not a held-out
  score any more. The regression run on sweep1's 40 is the independent check (no regressions). A new held-out set is
  needed to measure generalisation again.
- Errors 0, busy 0 in all runs. Real sensor data stays local (incident/sensor snapshots in this folder only).
