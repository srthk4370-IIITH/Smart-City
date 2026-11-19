# rsn_v3 2B on the board: measure-only test (2026-11-02, 04:20-06:05 IST)

Live during the test: APK bad36220 (deploy25 r2), htpd_v9f, `reasoner_model=/data/local/tmp/gpu/rsn_v3_2b_q4_0.gguf`, `chat_think=adaptive` (deploy26).
No code changes, no deploys and no rollback were made. The 4B ran only inside standalone lab windows, as the same-day reference with the same htpd_v9f binary and the live env. One NPU client ran at a time. Every lab request started at ≤55 °C, and every chat question at ≤60 °C. BOARD_LOCK was held as `2b_board_test` and has been released.

## Verdict
- **On the RWH report bench the 2B wins.** Severity 29/30 against the 4B's 27, label 29/30 against 25, parse 30/30. Mean time is 4.6 s against 7.8 s, and the board keeps about 2 GB more free RAM.
- **In the real app it makes errors the 4B does not.** I re-ran the same app prompts on the 4B (A/B below), and the 2B was clearly worse on two of seven:
  - A room-temperature *sensor fault* became a **false critical** with an invented cause ("outdoor heat source, CO2 rising"). It stayed critical through the 1.5 h and 3 h refinements.
  - A pH 9.6 critical became a self-contradicting report: "single bad reading, sensor fault", with severity critical and the action check_sensor. The validator rejected it, so the deterministic fallback stood in.
- **Chat: the router answered 143/160 questions and passed 139 of them. The 2B answered only 5 of its 17 correctly.** On the same sweep1 questions the 4B answered 4/5 (the 5th failed only because of the clock jump) and the 2B 2/5. The 2B invents tool arguments (domain "all", the node "KH level 3", pm25 for water) and often ends with "I could not find an answer".
- **Recommendation: roll back to the 4B (rsn_v1).** This needs the owner's OK: `deploy26_2b.sh --rollback`. The 4B is the accuracy-first choice. Keep the 2B file on the board. Feed the failures below into rsn_v3 r2 (sensor-fault patterns, contradiction between severity and the action, chat tool arguments) and gate it on the host first. The host gate g2b_r1 was still running and was not touched.

## 1. Report accuracy, RWH q10-q39 (q10 = warm-up, 30 scored), same window, same binary/env
`lab/b2b/` (raw outputs, htpd logs, ab.log, telemetry.log), scorer `lab/score_lab.py` (gold agreement + `verify.check_incident`), table `lab/lab_acc.md`, per item `lab/rows.jsonl`.

| model | parse | sev=gold | label=gold | action1 | action set | check recall | check prec | schema err | ungrounded | mean s | max s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B rsn_v3 (today) | 30/30 | **29** | **29** | 24 | 12 | 0.73 | 0.86 | 1 | 1 | **4.6** | 7.2 |
| 4B rsn_v1 (today, same window) | 30/30 | 27 | 25 | 20 | 15 | 0.73 | 0.85 | 3 | 0 | 7.8 | 15.6 |
| 4B reference (2026-10-28 sp3, older binary) | 30/30 | 27 | 25 | 20 | 14 | 0.81 | 0.87 | 3 | 0 | 22.5 | 33.7 |
| host rsn_v1 Q4_0, RWH 150 (FACTS_2026-10-29) | 98.7 % | 91.9 % | 87.8 % | - | - | 0.90 (106-item set) | - | - | 0 % | - | - |

- **2B misses:** q31 (gold sensor_fault, the 2B said normal/unknown "data gaps, not a fault"). q26 has an ungrounded time "21:00" and an evidence-count schema error.
- **4B misses:** q14 and q26 (unknown labelled normal_operation); q23 and q37 (a real tank warning called sensor_fault); **q38: a critical air-pollution event called sensor_fault**. Three schema errors (evidence_count).
- The 4B's numbers today are identical to the 2026-10-28 reference, so the window is comparable.
- Decode: 76.5 ms/step for the 2B against 181.3 ms for the 4B (split-spec kept 29 % against 38 %).
- Free RAM during the window: 2B 6.1-6.3 GB, 4B 4.2-4.3 GB.
- No HEAT or ABORT lines.

## 2. Through the app: sensor stories (`app/stories.py`, `app/stories.jsonl`, `app/raw/`)
The sliders go through /api/ingest after a reset. AI time = from the first injection until the incident is done with a final, non-preliminary report from Reasoner v3.

| story (intent) | incident | first seen | AI report | 2B early report | later refinements |
|---|---|---|---|---|---|
| normal drift (CO2 450→780 ppm, occupied) | INC-0655 | 147 s | 153 s | warning, occupancy_driven_load (limit not crossed: a false warning) | warning, resolved |
| real CO2 rise (700→1700 ppm, occupied) | INC-0657 / 0658 | 58 s | 58 s | sensor_fault ×2. The agent said step_increase/sensor_fault (+259 ppm jump). Root cause cites "indoor CO2 below 300 ppm" (ungrounded) | 0658 → **critical "CO2 rising with the AC on"** at 3 h; 0657 stays sensor_fault |
| sensor fault (room temp 25→44 C, AC sensors 24 C, room empty) | INC-0659 (fast path) | 9.5 s | 25.5 s | **critical, weather_driven, "Outdoor heat source, CO2 rising"**. The agent said sensor_fault 0.97 | still critical at 3 h ("Outdoor heat, indoor 43.8 C") |
| critical spike (water pH 7.2→9.6) | INC-0660 (fast path) | 3.6 s | 22.9 s | 2B report **rejected by the validator** (critical + check_sensor first; text "single bad reading"). The final came from the deterministic fallback | critical at 1.5 h / 3 h (the deterministic root cause says "turning acidic (pH below 6.5)" for pH 9.6: a fallback text bug) |
| weather-only heat (outdoor 34→46 C) | INC-0661 / 0662 | 42 s | 42 s | the 2B said normal; the severity guard kept the rules' warning. Titles quote 33.7 / 41.0 C | warning at 46 C (above the 42 C critical limit, but held at warning) |

- **A/B on the identical app prompts** (`app/make_rreq.py` → `app/rreq/q100-106`; lab `app/b2s/`; the 4B in the same window). The 2B gave identical answers on the repeated runs of pH and temp.
  - CO2 rise: both sensor_fault (they follow the agent).
  - Drift: both warning.
  - **pH: 4B correct** (critical, request_facility_review + inspect_water_system); the 2B is contradictory.
  - **Temp fault: 4B correct** (sensor_fault); the 2B gives the false critical.
  - Heat: the 4B said sensor_fault (bias step) and the 2B said normal weather_driven. Here the 2B is closer to the intent.
  - Reasoner time on these prompts: 2B 5.1-8.1 s, 4B 7.9-22.3 s.
- **AI update time in the app with the 2B:** about 23-26 s on the fast path (deploy26 fastcheck 21.6 / 17.1 s; 4B deploy25 22.1 / 27.5 s). The 2B reasoner itself takes 5.6-9.8 s. The ~25 s is mostly gating, the agents and the model swap (reasoner load 1.3-1.8 s).
- **Cosmetic:** final.model still says "qwen3.5-4b (htpd)" (hard-coded, known). htpd.log shows the 2B loaded for every story.

## 3. Chat (deploy25 r2 router + model = 2B) (`proofs/2026-11-01_chat/`)
- Partial pre-2B files were renamed `*_partial_4b_mixed*` (held-out Q1-11 on the 4B, Q28-40 already on the 2B). The 4B sweep1 run is now `sweep10_s1_d25_4b*`.
- The 2B re-run is in `sweep10_s1_d25`, `sweep11_heldout_d25`, `sweep12_blind_d25` and `sweep9_blind2` (`.jsonl`/`.log` + snapshots).
- Grades are in `grades1{0,3,4,5,6}_*.json`. They were judged per answer against the snapshots and the earlier truth files. Router counts were not re-derived one by one.

| set | before | 2B now | router | model (2B) | model median |
|---|---|---|---|---|---|
| sweep1 | d24 40/40; 4B d25 37/40 (3 clock-jump fails) | **37/40** | 35/35 | **2/5** (Q25, Q28 "could not find"; Q32 lists 1 of 4 open criticals) | 7.2 s (4B 9.7 s) |
| held-out | d24 r2 39/40 | **35/40** | 35/35 | **0/5** (Q5, Q11, Q25, Q32, Q40) | 10.2 s |
| blind | d24 r2 20/40 (router rewritten since) | **39/40** | 38/38 | 1/2 (Q15 window) | 6.5 s |
| blind2 | none (first run) | **33/40** | 31/35 (Q17 fewest, Q30 pH missed, Q32, Q37 approved count) | 2/5 (Q4, Q21, Q35 fail) | 12.3 s |

Flagged issues:
- **sweep1 Q9 / Q39-40.** On the 4B run the sim clock had jumped to 5-7 Dec, so "this week" and "last 30 days" windows held no data: 0 faults, 0 criticals. That is a replay-clock artefact, not the model. Today the clock is back in October: Q39-40 are correct (59 critical, water 47), and Q9 is now answered by the 2B with "1 sensor (WE-VN04-00)", which is plausible.
- **held-out Q5.** On the 4B (December clock) it gave AQ counts only and ignored water. On the 2B it tried pm25/pm10 × air/water and gave up with "could not find an answer".
- **held-out Q40.** The 2B merged faults and criticals into one number (partial run), and on the re-run made no tool call ("could not find"). This is a model failure in both runs.
- Router regressions to fix forward (not model): blind2 Q17, Q30, Q32, Q37.

## 4. Telemetry (`telemetry/zones_2b.log`: top-4 zones with names every ~6 s; `lab/b2b/telemetry.log`)
- **The 95 °C is the NSP HVX/HMX zones and the CPU prime cluster.** It is not the battery or the skin.
  - Over the whole run, the hottest zone was ≥90 °C in: cpu-1-2-1 181 samples (max 95), nsphvx-1 35 (max 97), nsphvx-0 18 (max 96), nsphmx-1 13 (max 96).
  - It happens only while htpd decodes (reasoner or chat) or loads a model. Between requests the board drops to 46-60 °C within about 10 s.
  - The deploy26 95 °C samples (18:08-18:15 UTC) fall inside its chaos 2 and fastcheck incidents.
- **The 4B reaches the same peak and stays hot longer.** In the RWH window the 2B half peaked at 95 °C (cpu-1-2-1), ≥90 °C in 23/103 samples. The 4B half peaked at 96 °C (nsphvx-0), ≥90 °C in 62/151 samples.
  - The 4B soak (2026-10-31 night, soak.csv) also logged 93-95 °C after incidents.
  - Nothing reached the 105 °C kill guard.
- Lowest MemAvailable across the run: 4.16 GB (while the 4B was loaded in the lab). With the 2B live it was 4.4-6.4 GB.

## Housekeeping
- Board files added: `/data/local/tmp/rfast/{zones.sh,zones_2b*.log}` and `lab/{b2b,b2s,run_lab_2b.sh,run_lab_stories.sh,b2*_live_*.jsonl}`.
- The board's `rfast/lab/lab_ab.sh` was updated to the laptop copy (it now adds htpd_v9e/v9f to the stop lists).
- `rfast/rreq_split/q100-105` were overwritten by mistake and then **restored** from `proofs/2026-10-31_latency/corpus/rreq_real` (md5 checked). q106 was removed.
- The story incidents INC-0655..0663 remain in the app (needs_decision). Dismiss them on the Incidents page if they are not wanted.
- The app is back up on the 2B profile.
