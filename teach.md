# teach.md: the whole project, for a teammate who must answer any question

**Project:** Agentic Edge AI for Smart Cities (team NASA, esw-m26-14). **Board:** Qualcomm QIDK, Snapdragon 8 Gen 3
(SM8650), Hexagon V75 NPU, Adreno 750 GPU, Android 14. **Evaluation:** 2026-11-04, 12:00 IST.

Last rewritten: 2026-11-04 morning. Every number has a source file in brackets. "HANDBOOK 2.xx" means section 2.xx of
`HANDBOOK.md`. If a number is not here or in its source, do not say it. The slide deck is `ppt.md` (28 slides, every
number sourced); this file goes deeper.

Rule for live numbers: incident counts in chat answers change with the live data. Quote the measurements below, not
the counts you see on screen.

---

## 0. Headline numbers to learn by heart

| what | number | source |
|---|---|---|
| Critical breach -> incident open (fast path) | **5.6 s** (2.6 s after a silent gap) | `proofs/2026-11-04_split/deploy32/STATUS.md`; `proofs/2026-10-31_validator/gap_r3.txt` |
| Incident -> AI report on the same incident (warm) | **~28 s** (21.4-33.0 s across deploys 28-32) | `proofs/2026-11-04_split/deploy2*/STATUS.md`, `deploy3*/STATUS.md` |
| Same, first incident after 4 h idle (cold) | **78 s** (fast alert 6.9 s); next run 28.0 s | `proofs/2026-11-04_split/FINAL_CHECK.md` |
| Preliminary report | same second, < 5 ms CPU | HANDBOOK 2.57 |
| Non-critical event -> AI start | 8 readings = **40-55 min of sensor time** | HANDBOOK 2.55 |
| One domain agent request | **2.06 s** (was 2.59 s) | HANDBOOK 2.65 |
| 12-agent incident, agents stage | 46-48 s (Genie, one by one) -> **20.7 s** (htpd batch) | HANDBOOK 2.37; ppt.md slide 18 |
| Reasoner report (lab) | 23.3 s -> **9.1 s** (verified drafts in split) | HANDBOOK 2.63 |
| Reasoner swap (model load) | 3.67 s -> **2.80 s** | HANDBOOK 2.62; ppt slide 16 |
| Reasoner rsn_v1 accuracy (150 held-out, host) | severity **91.9%**, label **87.8%**, valid JSON 98.7%, 0% ungrounded | ppt slide 21; `proofs/2026-10-25_reasoner_final` |
| rsn_v1 vs rsn_v2 (106 RWH ids) | severity 94.7% vs 87.6% -> rsn_v2 rejected | HANDBOOK 2.59 |
| Domain agents v1 vs base vs rules (host) | pattern 94.0% vs 20.0% vs 68.0% | ppt slide 20 |
| Quantisation gap | 94% host vs 67% first device run; prompt (BOS) fix -> 83%; htpd Q4_0 -> 90.7% | ppt slide 20; HANDBOOK 2.7, 2.37 |
| B50 acceptance (gate2) | severity-weighted net **+61**, safety 16/16 | ppt slide 9 |
| Chat router | 143/160 answered < 1 s, **median 0.2 s**, 0 errors (deploy30) | `proofs/2026-11-04_split/CMP_d27_d30.md` |
| Chat model answer, 2B on CPU | **7-14 s** fresh (long list ~28 s); GPU was 10-42 s | HANDBOOK 2.73 |
| Chat gate: 2B r2 vs 4B | chat dev v3 pass **0.737 vs 0.477** | `proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md` |
| Report gate: 2B r2 vs 4B | RWH severity **0.793 vs 0.919**, check recall 0.405 vs 0.848 | same GATE.md |
| 2B decode speed | **~25 tok/s CPU (5-6 threads)** vs ~9-10 tok/s GPU, identical text | `proofs/2026-11-04_split/gpu/tune/TUNE.md` |
| Chat keep-warm fix | re-prefill ~3,100 -> ~290 tokens per new question | `proofs/2026-11-04_split/README.md` step 4 |
| Decode roof | 3B: 49.3 GB/s = ~84% of the 59 GB/s NPU DMA ceiling; 4B: 60 ms/token, ~52 GB/s | ppt slide 17; HANDBOOK 2.53 |
| Threshold breaches in the cleaned data | 20,538 | ppt slide 2 |
| Window study | 4 h best (pattern 64%, 2,416 NPU calls, p < 0.0001) | ppt slide 7 |
| Young events | 42% right at 40 min vs 88% at 3 h (same 208 events) | ppt slide 7 |

---

## 1. The problem and the story

**Problem** (ppt slide 2, PRD.md section 2):
- A campus has thousands of threshold breaches a year (20,538 in our cleaned sensor data, most short). A threshold alarm
  says "CO2 high" and stops.
- The operator needs to know **why**: people in the room, failed ventilation, or a faulty sensor? Causes often cross
  domains (a crowded room raises CO2, power and cooling load together).
- The data is private (room-level occupancy shows where people are). The network can fail; monitoring must not.
- So: explain **on the device**, offline, with evidence, and keep a person in charge of every action.

**Data:** SCRC-IHub IIIT-H campus sensor data, 2025 (PRD.md 5.1). Six domains: air quality, water, power, HVAC,
occupancy, weather. Test months and about 15% of sensors held out (HANDBOOK 2.40).

**The story to tell** (ppt slide 3, numbers from `proofs/2026-11-04_split/deploy32/STATUS.md`):
1. KH building level 3: the CO2 sensor jumps to 2000 ppm.
2. ~5.6 s later the incident is open (critical fast path), with a preliminary report and a live checklist.
3. ~28 s after that, the AI report lands on the same incident: title, severity, root cause, causal chain, evidence
   ids, claim checks on the agents, a checklist.
4. The operator acknowledges ("I'm on it"), ticks steps, closes with an outcome. The AI never switches anything.
5. At 1.5 h and 3 h of sensor time the incident is re-checked (raised, lowered or resolved).
6. The operator can also ask the Campus Assistant in English or Hinglish ("CO2 theek hai KH level 3 pe?").

---

## 2. Hardware and what runs where today

**Board** (HANDBOOK 2.37, `proofs/2026-10-16_hw_grid`): SM8650 (8 Gen 3), Hexagon V75 NPU (HVX + HMX), Adreno 750,
Android 14. NPU and GPU buffers are unmovable memory inside a 7.26 GB zone (ppt slide 17).

**Eval-day split** (`proofs/2026-11-04_split/README.md`, deploy32 is live, APK 9e82675a):

| job | model | engine |
|---|---|---|
| Backend: rules, data-quality gates, event gate, fast path, retrieval, validator, workflow, chat router | Go `edge-agent` | CPU |
| Domain agents | ft_B50, fine-tuned Llama 3.2 3B, Q4_0 | Hexagon V75 NPU, resident in htpd |
| Incident reports (cross-domain reasoner) | rsn_v1, fine-tuned Qwen3.5-4B, Q4_0 | NPU, swapped in per incident |
| NPU daemon | htpd_v9f (our llama.cpp Hexagon server) | CPU + NPU |
| Chat, questions that need a model | rsn_v3 r2, fine-tuned Qwen3.5-2B, Q4_0 | **CPU, 5 threads**, llama-server in `/data/local/tmp/chatgpu/` |
| Chat, router questions (~90%) | no model (deterministic Go router) | CPU, < 1 s |
| Apps | Smart City Edge (dashboard) and Campus Assistant (chat): two launcher icons, one backend | phone UI |

- The 2B chat model never touches the NPU. One NPU client at a time is preserved.
- **This split is for the evaluation only** (owner). The 4B keeps training (rsn_v3 4B) to become the one general model.
- If the chat server fails a call, chat falls back to the 4B on the NPU for that call and skips the 2B for 60 s.

---

## 3. The full pipeline in detail

### 3.1 Sensor ingest
- Readings every 5 min per sensor through `/api/ingest`; bucketed per 5 min, de-duplicated, late and out-of-order
  readings handled, gaps detected (HANDBOOK 2.46, `dataquality.go`). Replaying 5 real CO2 outages, the old ingest
  invented 91 readings; now 0 (ppt slide 6; `proofs/2026-10-23_realworld/REALWORLD.md`).
- **Inputs:** live sensor posts, the dashboard **sliders** (the user acts as the sensor), and the API. There is a
  **replay clock** for demos: one reading every 2 s instead of every 5 min (ppt slide 16 "design" row).
- Sensors set by slider or API stop recording after 15 min of wall time (`heldStale`); chat then calls them "silent"
  (HANDBOOK 2.68).

### 3.2 Rules and data-quality gates
- Each reading gets a rule status against the sensor's limits (normal / warning / critical).
- A sensor with too many gaps is "insufficient data" with a reason, not a guess. Coverage rule: at most 3 of 48 points
  missing (HANDBOOK 2.67).
- A single glitch does not open an incident; a value chattering at a limit is suppressed (event gate only; the AI still
  sees the raw window) (ppt slide 6).
- Hourly sensors such as TDS stay rules-only (ppt slide 26).

### 3.3 Sensor-fault detection
- Seven fault kinds (stuck, quantised, offset, drift and others) are a separate status `sensor_fault`, never mixed with
  process alarms (HANDBOOK 2.40).
- A physically impossible value (indoor CO2 < 350 ppm) is a fault (HANDBOOK 2.35).
- Maintenance API: mark a sensor out of service or replaced; a fault returning within 30 days of a repair suggests
  replacement (HANDBOOK 2.49).

### 3.4 The 4 h window and the 8-reading gate
- The AI reads a 4 h window: `engine.go` Window = 48 points x 5 min (HANDBOOK 2.38).
- Why 4 h: the window study found 4 h best (pattern 64%; every other length significantly worse; 2,416 NPU calls;
  p < 0.0001) (`proofs/2026-10-16_window_study/RESULTS.md`).
- **8-reading gate:** an abnormal status for 8 readings opens an event; co-occurring sensors are batched into one
  incident (batch window 3 readings). That is 40-55 min of sensor time (HANDBOOK 2.29, 2.55).
- Why accept it: young events are read badly (42% right at 40 min vs 88% at 3 h on the same 208 events)
  (`proofs/2026-10-16_placement_study`, 1,248 calls).

### 3.5 Refinements at 1.5 h and 3 h
- The first report is refined at 1.5 h and 3 h of sensor time, with a window chosen by the event's shape: 3 h 86.3%
  vs 80.8% for the old ladder on a fresh seed of 182 events, McNemar p = 0.021 (HANDBOOK 2.42).
- Re-checks can **elevate** (only if the problem is visible now), **curb** (only if AI and rules both read lower) or
  **resolve** (back at baseline for 30 min); 5/5 cases through the app (HANDBOOK 2.43).

### 3.6 12 h level-shift and drift checks
- CPU checks over 12 h for level shifts and slow drifts: old steps caught 73% -> 93%, drifts 83% -> 95%, no new
  false alarms (p = 0.0005 and p = 0.016) (`proofs/2026-10-16_longrange`, HANDBOOK 2.39).

### 3.7 Critical fast path
- `fastpath.go`, `engine.go` (detect, valueCritical), `reason.go` (buildIncident, adoptFast) (HANDBOOK 2.55).
- A sensor whose **fresh** readings are beyond its **critical** limit for 2 readings in a row (pH < 6.0 or >= 9.0,
  "high" >= Crit, "low" < Crit) opens the incident at once with the rules-only preliminary report, severity critical,
  no NPU. The agents + reasoner still run at 8 readings and update the **same** incident.
- One fast incident per episode (12-reading cooldown). Deadband, maintenance and data-quality gates still apply.
- **Silent-sensor bypass** (deploy22, HANDBOOK 2.67): a fresh critical reading skips the coverage rule for the fast
  incident only. CO2 2000 ppm after a 17-min silence opened in **2.6 s** (deploy21: 44-46 s) (`gap_r3.txt`).
- **Limit:** power, tank level and flow have no fixed critical limits, so no fast path.
- **Early provisional AI** (`earlyai.go`, at 2-4 readings) is built but **off** until proven (HANDBOOK 2.55).

### 3.8 Retrieval preliminary report
- `retrieval.go` (HANDBOOK 2.57, 2.57b; `proofs/2026-10-28_master/RAG_STATUS.md`).
- Every incident gets a preliminary report in < 5 ms CPU: the nearest finished AI reports (70% structured match +
  30% TF-IDF, same role and metric, tuned threshold) rewritten with the **live** values. Severity = max(rules,
  retrieved), so it never under-alerts. No hit -> rules report + "full AI report coming".
- Library: every validated live report + **254 seed reports** (320 generated by rsn_v1 on the laptop, 254 kept after
  validity checks). Live reports rank 3% above seeds.
- It is **not** the AI. Numbers always come from live values; only wording comes from the old report.

### 3.9 Domain agents (ft_B50 3B on the NPU, batched in htpd)
- One QLoRA fine-tune of Llama 3.2 3B plays six roles (one per domain). One agent per abnormal sensor; all agents of
  an incident run in **one NPU batch** in htpd (HANDBOOK 2.37).
- Output: a JSON finding (pattern, status, cause, evidence). **Post-rules** (`postrules.go`) then check limits,
  glitches, chatter and allowed causes (HANDBOOK 2.50). Status 81.5 -> 86.4% (1,148 rows); real-world 60.4 -> 85.2% (318).
- HVAC: an AC on in an empty room -> `switch_off_ac` as a **recommendation only** (ppt slide 9).
- Agent drafts (htpd v9e): 2.59 -> 2.06 s per request, 23/24 identical (HANDBOOK 2.65).

### 3.10 Cross-domain reasoner (rsn_v1, Qwen3.5-4B)
- Reads every agent finding plus related sensors and writes: title, severity, label, root cause, causal chain,
  observations with evidence ids, **claim checks on the agents**, checklist (ppt slide 10).
- **Swapped onto the NPU per incident** (one model at a time). Swap 3.3-4.1 s overall, load 2.80 s after the
  multithreaded repack (HANDBOOK 2.54, 2.62).
- Prefill 1.6-2.8 s (the 1,317-token static prefix comes from htpd's disk prefix cache) (HANDBOOK 2.54).
- **Split decoding** (`reasoner_split=3`): the head (title, severity, label) is written once, then 3 field groups
  decode in parallel streams. Severity and label are decided before the fork. 25.7 -> 23.7 s (HANDBOOK 2.53).
- **Verified drafts inside the split** (htpd v9): each stream proposes tokens by longest-suffix match in the prompt and
  in a corpus of past reports by the same model; the NPU verifies them greedily. Lab 23.3 -> **9.1 s**, severity +
  label 6/6 (HANDBOOK 2.63).
- **Draft corpora:** started with 463 past board reports; rebuilt to 576 docs with the app's own reports; since v9d
  every finished report is added live (cap 3000). Repeated incidents 4.6-5.1 s (HANDBOOK 2.64).
- **Two-stage report:** the preliminary appears first; the reasoner report replaces it on the same incident.
- **"AI so far":** title, severity, label, root cause and causal chain appear while the reasoner is still writing,
  marked "not yet checked by the safety gate" (HANDBOOK 2.62).

### 3.11 Validator and policy gate
- On every report (`reasoner_v3.go`): valid JSON, allowed labels, real evidence ids, numbers must exist in the input,
  no actuation language, action floors by severity (HANDBOOK 2.7, 2.33).
- **Action floor:** a critical report must start with `inspect_*` or `request_facility_review`, except weather-only
  incidents, which may start with `monitor` or `review_schedule` (`v3ActionFloor`, `weatherOnlyIncident`; came from
  INC-0564, outdoor 45 C) (HANDBOOK 2.67).
- **Contract repairs:** normal + needs_more_data -> label `unknown` (gold 151/151); a title location not in the input is
  replaced (gold 5,761/5,761). Replay on 386 board answers: label 83.2% -> 87.6%, 0 new errors (HANDBOOK 2.59).
- **pH direction** (`phdir.go`, deploy27): pH above 8.5 is "alkaline", below 6.5 "acidic", whatever the model wrote
  (HANDBOOK 2.72; from board INC-0660).
- The gate trims over-long lists instead of rejecting the report (HANDBOOK 2.53).
- A failed report -> deterministic fallback report, marked as such. The operator always gets a report.

### 3.12 Severity guard
- When the rules put a flagged sensor at warning or critical, the reasoner may not report normal; it is kept at warning.
  `sensor_fault` is not a downgrade. The report carries `severity_basis`; every disagreement is logged as
  `severity-disagreement` in agent.log (HANDBOOK 2.53).
- Consistency: same prompt 5 times, same severity 97%; 100% with the guard (ppt slide 21).

### 3.13 Titles
- The reasoner writes the title (with location); a title location not in the input is replaced from the input
  (contract repair). Example live titles: "KH building, level 03: Suspect CO2 readings",
  "CO2 sensor fault (stuck): KH building, level 03" (`deploy32/STATUS.md`, `FINAL_CHECK.md`).

### 3.14 Checklist and steps
- The checklist is built from the preliminary report, so the operator can acknowledge and tick at once. When the AI
  report arrives it merges: ticked steps the AI repeats stay done and take the AI's reason, dropped open steps are
  withdrawn, new ones marked new. Close, dismiss and approve-all wait for the AI (HANDBOOK 2.59).

### 3.15 Approval workflow
- Needs decision -> In progress ("I'm on it", name picker) -> Resolved -> Closed with an outcome. Per-step Done / Not
  needed; append-only event log; re-acknowledge when it gets worse (HANDBOOK 2.49).
- 15-min re-alert for unacknowledged criticals, 24 h auto-close after recovery, Android notification for critical.
- Endpoint example: `POST /api/incidents/{id}/dismiss` (HANDBOOK 2.67, bulk clear of 399 test incidents on 31 Oct).

### 3.16 Operator UI
- Plain-language incident sheet: what is happening, why it matters, what to do, how sure the AI is, what changed at
  re-checks; jargon behind "Technical details"; an Engineering view (off by default) (HANDBOOK 2.43, 2.49).
- Design follows ISA-18.2 / EEMUA 191 / ISA-101 and Microsoft's HAX guidelines (`proofs/2026-10-21_ux/UX_RESEARCH.md`).
- Domain health tiles (worst first), shift summary, grouping of repeats, filters, search, sensor history.

### 3.17 Reports, storage, self-learning data
- Everything is stored on the board under `/data/local/tmp/smart_city_edge/` (incidents, chats in `state/chats.json`,
  corpora such as `reason_corpus.jsonl`, `data/rag_seed.json`) (HANDBOOK 2.57b, 2.60, 2.63).
- **Self-learning capture:** every call stores prompt, raw output, repairs and the operator's verdict; repairs become
  preference pairs with no labelling (`training/feedback/export_feedback.py`, HANDBOOK 2.28).
- Fog/cloud store (free Supabase, board as the only writer) is designed, **not built** (HANDBOOK 2.44).

---

## 4. htpd: our llama.cpp Hexagon daemon

**What it is:** a persistent server on the board that loads GGUF models through llama.cpp's Hexagon (ggml-hexagon)
backend and serves the app's agent, reasoner and chat requests. It replaced Qualcomm Genie because Genie dropped
batching (HANDBOOK 2.37; ppt slide 22). One htpd serves both NPU models, swapping them.

| version | what it added | source |
|---|---|---|
| htpd (first versions) | batched agents on the NPU; 12-agent incident 46-48 s -> 20.7 s; pattern 90.7% on 54 board windows | HANDBOOK 2.37 |
| htpd_v7 | `HTPD_AGENT_MAX_NEW=160`, `HTPD_JSON_ABORT=2`, synthesizer prefix cache; `model=` in htpd_profile swaps the GGUF | HANDBOOK 2.43 |
| v8s | n-gram reasoner speculation (`HTPD_REASON_SPEC`): slower, rejected | HANDBOOK 2.53 |
| v8p | vocabulary-pruned lm_head (first try; board rebooted mid-run, held) | HANDBOOK 2.53 |
| **v8x2** | split decoding (3 streams), OPPOLL (`GGML_HEXAGON_OPPOLL=1`, 27.8 -> 25.8 s), early release 20 -> 3 s idle | HANDBOOK 2.53 |
| **v8x3** | bounded constrained pick (top-64, top-1024, forced token, full scan last); **150 s wall-clock guard** per reason request; heartbeat; same speed as v8x2 (21.7 vs 21.6 s) | HANDBOOK 2.58, 2.58b |
| v8x4 | decode row padding: +11-15% slower, rejected | HANDBOOK 2.61 |
| v8x5 / v8x5p | per-step and load timers; disk prefix cache LRU 4 files/model; pruned head 22.6 -> 20.2 s, load 3.67 -> 2.82 s | HANDBOOK 2.62 |
| **v9 / v9b / v9c** | verified speculative drafts inside split (K=8 + ALIGN), deploy15-18; v9b gated with the wrong variable, v9c fixed (`NS > 1`) | HANDBOOK 2.63 |
| **v9d** | live draft corpus (`HTPD_REASON_CORPUS_LIVE`, cap 3000), `SPEC_KLONG=16`; reasoner 11.83 -> 8.89 s | HANDBOOK 2.64 |
| **v9e** | agent draft index (n-grams to 8, last 500 outputs, seeded with 1,134); agents -21% | HANDBOOK 2.65 |
| **v9f** (live) | chat drafts from a chat corpus (`HTPD_CHAT_SPEC=8`, `MIN=4`); chat request 2864 -> 2383 ms, 10/10 identical | HANDBOOK 2.66 |

Key ideas:
- **Batching:** all agents of an incident decode together, so a step with several rows costs little more than one.
  Bench step costs: 1 row 66 ms, 2 rows 82, 3 rows 113, 4 rows 133, 6 rows 106, 8 rows 109, 16 rows 120 (HANDBOOK 2.54).
- **Split-spec decoding:** split streams already carry 2-4 rows (the costliest range); extra draft rows push the step
  onto the HMX path at a flat 106-120 ms, so drafts are nearly free and every kept draft saves a step. ALIGN pads
  streams to equal rows so a step is one ubatch (~150 ms vs 240-319 ms) (HANDBOOK 2.63).
- **Why single-stream speculation lost:** its baseline was a 66 ms 1-row step (HANDBOOK 2.63).
- **Guards:** 150 s per reasoner request -> deterministic report; requests start at <= 60 C; thermal pacing; heartbeat.
- **One-NPU-client rule:** only one process may use the NPU. Stop the app's htpd and wait for exit before any lab run.
- **Swap timings:** swap 3.3-4.1 s; model load 3.67 s (ggml-hexagon repacks every weight single-threaded) -> 2.80 s with
  the multithreaded repack (HANDBOOK 2.54, 2.62; `proofs/2026-10-29_latency/repack/VERDICT.md`).
- **Why two resident NPU models rebooted the board:** NPU buffers are unmovable memory in a 7.26 GB zone; loading a
  second model alongside the first exhausted it and the board rebooted (HANDBOOK 2.27, 2.37). Hence swap per incident.
- Run-to-run: NPU float sums are not bit-reproducible (base vs itself 2/6 identical text, 21-24 of 25 identical agent
  outputs) (HANDBOOK 2.37, 2.63).

---

## 5. Campus Assistant chat

**What:** a second app on the same backend (launcher icon "Campus Assistant", `/chat/`, and "Ask AI" in the dashboard).
History in `state/chats.json`. Every answer has "How I found this" (tool calls and raw results) (HANDBOOK 2.60).

### 5.1 Router (deterministic Go, runs first)
- `chat_router.go`, `chat_router_ops.go` (deploy23), `chat_router_v24.go` (deploy24), `chat_router_v25.go` (deploy25).
- **Question-type layer** (v25): intent classes action, injection, out of scope, future, scenario, reading, sensor
  health, incidents, for English, Hinglish and typos. Sensor and place resolution, metric chosen per node (a
  temperature on an AC is `room_temp`). Grouping, longest-waiting / worst, co-occurrence, glossary, what-if against
  limits, "normal or high" against the sensor's own 7 days (HANDBOOK 2.70).
- **Time-span parser** (`chat_time.go`): N min/h/days/weeks, ghante/din, "since Monday 8 am", between, overnight,
  this morning, dates and ranges, N weeks ago, future. A period it cannot read is never widened. "This week" = since
  Monday (HANDBOOK 2.70, 2.72).
- **Referents:** follow-ups ("which ones?", "explain why", "it") use the previous answer's tool args (incident set, one
  incident, sensors).
- **Typo normaliser** (`chatNormalize`) and **Hinglish**: kitne, aaj, kal, kharab, theek hai, kya hai, abhi, ghante/din.
- **Safety refusals:** close / approve / dismiss / delete / reset / switch and prompt injections are refused: "I can't
  do that: my tools only read the device's data..." (`deploy32/STATUS.md`).

### 5.2 Tool-calling model and the 15 tools
- If the router does not answer, a model runs a tool loop of up to 5 read-only calls (HANDBOOK 2.60).
- The 15 tools (`backend/chat_header15.txt`): `count_incidents`, `current_levels`, `domain_health`, `faulty_sensors`,
  `find_incidents`, `get_action_history`, `get_incident`, `get_sensor_history`, `list_sensors`, `open_incidents`,
  `rank_readings`, `recent_incidents`, `search_knowledge`, `sensor_faults`, `what_if`. (The first version had 9.)
- Model today: 2B rsn_v3 r2 on the CPU (eval only); fallback the 4B rsn_v1 on the NPU.

### 5.3 Chat guard (`chat_guard.go`)
- The model gets the period and sensors as a hint; tool time is held to the question (since deploy27 also for
  `rank_readings`, `faulty_sensors`, `what_if`).
- Invented incident ids and nodes return errors; a failed tool is stated in the answer; unverified ids are removed.
- pH direction words are corrected (`phdir.go`).
- **Repeated-tool-call guard** (deploy31): an identical repeated tool call in one question is dropped; a round of only
  repeats ends the question (the 2B had looped 63 s in d30 blind2) (HANDBOOK 2.73).

### 5.4 Keep-warm and queueing
- **On the 4B/NPU (deploy pre-split):** while chat is in use, a 1-token call every 2 s keeps the reasoner and the hour's
  chat prefix loaded; warm 5 s vs cold 8-14 s; skipped during incident analysis (HANDBOOK 2.61).
- **Queueing:** alerts first. On the NPU, a question asked during an incident analysis is queued and answered when the
  NPU is free (5 min cap); `/api/chat/status` says what it waits for (HANDBOOK 2.60). With the 2B on the CPU, chat no
  longer waits for the NPU.
- **On the 2B (today):** checkpoint-aware keep-warm every 30 s, see section 8.6.

### 5.5 Sweeps and scores
| sweep (40 questions each) | before | after | source |
|---|---|---|---|
| sweep 1 (deploy22 -> 23) | 27/40, median 9.7 s | 39/40, median 0.2 s | `proofs/2026-11-01_chat/VERDICT.md` |
| held-out (deploy23 -> 24) | 25/40, median 10.2 s | 39/40, median 0.02 s | `VERDICT_heldout.md` |
| blind (deploy24) | 20/40 | question-type layer (deploy25), no phrase patches | `VERDICT_blind.md` |
| blind2 | written 1 Nov 18:21 before any coding | run on d27, d30, d31 | HANDBOOK 2.70, 2.73 |

- **160-question runs** = sweep1 + held-out + blind + blind2. Deploy27 (4B): 142/160 router < 1 s, median 0.2 s, 0
  errors, 0 busy (HANDBOOK 2.72). Deploy30 (2B): see section 8.10.
- Honest note: the "after" scores reuse the questions the fixes were designed from; that is why blind sets exist.
- 2B r1 on the board (deploy26, 2 Nov): router 139/143 but 2B model answers 5/17 -> rolled back (HANDBOOK 2.71).

---

## 6. Models and training

### 6.1 Domain agents
| step | result | source |
|---|---|---|
| v1 fine-tune vs base vs rules (host, 150 windows) | pattern 94.0% vs 20.0% vs 68.0% | HANDBOOK 2.7 |
| first NPU export (w4a16, Genie) | 54.3% (46 windows) | ppt slide 20 |
| GPTQ int4 + Genie double-BOS fix | 82.6%; 85.2% on 54 windows | HANDBOOK 2.7 |
| htpd final (Q4_0) | 90.7% pattern, 100% JSON/policy (54 windows) | HANDBOOK 2.37 |
| v2 (35,946 rows, 6 roles, 7 fault kinds, 2-12 h windows) | 40 min 73.8% vs 42%; false alarms 18% vs 31%; 3 h 82.5% vs 88% (a miss, p = 0.09) | HANDBOOK 2.40, 2.42 |
| mixA50 | weight blend (WiSE-FT style) | HANDBOOK 2.51 |
| **B50** (live) | v2 -> mixA50 -> half of one more LoRA top-up blended; gate2 +61, story +4, safety 16/16 | `proofs/2026-10-25_domain_plan/B50_STAGED.json` |
| rejected | 3d, 3e (DPO+NLL), v2.1, P3b blends, T30 (dev +7 CI [-19,+35], severity -13) | HANDBOOK 2.48, 2.54b |

- **Quantisation gap 94% host vs 67% device:** mostly a prompt mismatch (Genie adds its own BOS -> double BOS): 67% ->
  83% from that fix alone; GPTQ recovered most int4 rounding loss (74% -> 89% on host). Activation recalibration on
  Kaggle did not beat the published ranges once BOS was fixed (ppt slide 20).
- **gate2:** paired acceptance test on the same rows; also a permutation test showed the old test rejected two identical
  models 71-82% of the time, so we fixed our own test (ppt slide 24).

### 6.2 Reasoner
| model | result | source |
|---|---|---|
| P0 benchmark | Qwen3.5-4B best total (+0.16 vs 2B) vs 2B and our 3B | `proofs/2026-10-23_reasoner_research/P0/host_bench/RESULTS.md` |
| **rsn_v1** (QLoRA r32, ~21 h laptop) | severity 91.9%, label 87.8%, JSON 98.7%, 0% ungrounded / unit errors / actuation / injection | `proofs/2026-10-25_reasoner_final` |
| rsn_v2 | 106 RWH: severity 87.6 vs 94.7, label 85.6 vs 88.4, check recall 0.81 vs 0.90; on board invented a title location and misread 324 > 300 ppm -> rejected | HANDBOOK 2.59 |
| rsn_v3 2B r1 | board RWH 29/30 sev, 29/30 label, 4.6 s; but a false critical and a self-contradicting pH report in app stories; chat model 5/17 -> rolled back | HANDBOOK 2.71 |
| **rsn_v3 2B r2** | gate FAIL on reports, win on chat (table below); stopped at step 1234 for the eval | `GATE.md` g2b_r2; `kaggle/STATUS.md` |
| rsn_v3 4B | training continues (Kaggle/laptop chain); a first 4B adapter import (g4b_1) failed in merge on 31 Oct; no 4B gate result yet | `kaggle/STATUS.md` |

**The gate** (`proofs/2026-10-29_rsn_v3/kaggle/local/gate_eval.sh`; rule in GATE.md): RWH and RWH-2 every report metric
>= rsn_v1 (schema_err <=); dev within 1 item; strict JSON; chat dev v3 pass rate > rsn_v1. Suites: **RWH** (150
real-world held-out reports), **RWH-2** (150), **dev** (120), **P0** regression (informational), **chat dev v3** (300).

2B r2 vs rsn_v1:
| suite | metric | 2B r2 | 4B rsn_v1 |
|---|---|---|---|
| RWH | severity / label / check recall / schema_err | 0.793 / 0.907 / 0.405 / 0.147 | 0.919 / 0.874 / 0.848 / 0.081 |
| RWH-2 | severity / label / check recall | 0.793 / 0.92 / 0.467 | 0.928 / 0.968 / 0.675 |
| dev | severity / label / check recall | 0.833 / 0.833 / 0.419 | 0.923 / 0.894 / 0.8 |
| chat dev v3 | pass / calls_ok / facts_ok / grounded / refusal_ok | **0.737 / 0.827 / 0.79 / 0.983 / 0.909** | 0.477 / 0.65 / 0.61 / 0.973 / 0.864 |
| chat dev v3 | wall s mean | 2.6 | 4.82 |
| P0 total | | 0.765 | 0.763 |

- **Why it failed reports but won chat:** it misses checklist items (check recall 0.405) and has more schema errors,
  but chat improved because r2 fixed a tokenization bug that left the "close the think block" token unlabelled in r1
  (`proofs/2026-11-02_2b_r2/DIAG.md`), and it was trained with adaptive chat thinking (memory "rsn_v3 plan").
- **Training chain:** Kaggle notebooks (2 GPUs, nf4, ~420 tok/s) plus user-started 6-8 h laptop sessions with heartbeat
  and stop prompt; `laptop_chain.sh`, `laptop_train.sh`, `train_ctl.sh`, `export_gguf.sh`, `gate_eval.sh` in
  `proofs/2026-10-29_rsn_v3/kaggle/local/`; start/stop from `start.ps1` / `stop.ps1` (HANDBOOK 2.67;
  `kaggle/STATUS.md`). Laptop disk rule: keep >= 20 GB free on C: (the 4B import filled it on 31 Oct and crashed WSL).
- Methods: QLoRA, verified self-distillation (STaR-style), contrastive heatwave pairs (commit 79455c6), WiSE-FT blends.

---

## 7. Latency in depth

### 7.1 Every stage today
| stage | time | why | source |
|---|---|---|---|
| reading -> rule status | every 5 min (demo replay 2 s) | sensor rate | design |
| non-critical event -> AI start | 40-55 min | 8-reading gate + batch window | HANDBOOK 2.55 |
| critical breach -> incident | 5.6 s (2.6 s after silence) | 2 fresh readings, no NPU | deploy32; gap_r3 |
| preliminary report | same second | CPU retrieval | 2.57 |
| one agent request | 2.06 s | bandwidth roof, drafts | 2.65 |
| reasoner swap | 2.80 s load; 3.3-4.1 s overall | weight repack on CPU | 2.62 |
| reasoner prefill | 1.6-2.8 s | static prefix from disk cache | 2.54 |
| reasoner decode | 8.9-9.1 s lab | split + verified drafts | 2.63, 2.64 |
| incident -> AI report (app) | ~28 s warm; 78 s cold after 4 h idle | waits for AI gate, batch window, swaps | deploy32; FINAL_CHECK |
| chat router answer | median 0.2 s | no model | CMP_d27_d30 |
| chat model answer (2B CPU) | 7-14 s; ~28 s long list | prefill of tool results ~100 t/s when hot | 2.73 |

The end-to-end AI number is larger than agents + swap + reasoner because the fastcheck also waits for the AI gate, the
batch window and the swap back (ppt slide 16).

### 7.2 Why it is that fast and not faster
- **Memory-bandwidth roof:** every token reads all weights from DDR. 3B agents ~2.2 GB/token at 22.4 tok/s = 49.3 GB/s,
  ~84% of the measured 59 GB/s NPU DMA ceiling. 4B: 60 ms/token, ~52 GB/s over 2.6 GB. So we cut sequential steps
  (batching, split, drafts), not per-step cost (HANDBOOK 2.15, 2.53). Even a perfect kernel gives about 20 tok/s for a
  4B Q4 on 8 Gen 3 (`proofs/2026-10-27_reasoner_fast/RESEARCH.md` row 8).
- **Per-step time is inside `llama_decode`** (97-123 ms/step); CPU pick + emit < 0.4 ms (HANDBOOK 2.62).
- **Swap:** one model at a time costs a reload per incident.
- **Sensor time dominates:** 8 x 5 min; accepted for the prototype; fast path for criticals.

### 7.3 Ladder: what made it faster (ppt slide 18)
| step | before -> after | source |
|---|---|---|
| context 4096 -> 2048 | -721 ms per agent call, 14/14 identical | 2.22 |
| early batch-window close | -4 s per isolated incident | 2.29 |
| persistent daemon (genied) | agent 3.64 -> 2.54 s | 2.24 |
| htpd one NPU batch | 12 agents 46-48 -> 20.7 s | 2.37 |
| OPPOLL + split | 27.8 -> 21.6 s | 2.53, 2.58b |
| verified drafts + live corpus | 23.3 -> 9.1 s; app AI 52.6 -> 27.0 s | 2.63, 2.64 |
| agent draft index | -21%; app AI 21.7 s | 2.65 |
| multithreaded repack | load 3.67 -> 2.80 s | repack VERDICT |
| chat router + keep-warm | 9-14 s -> 0.2 s router / ~5 s warm | 2.61, 2.68 |
| 2B checkpoint-aware keep-warm | re-prefill 3,100 -> 290 tokens | 2.73 |
| 2B GPU -> CPU | 9-10 -> ~25 tok/s; answers 10-42 -> 7-28 s | 2.73, TUNE.md |

### 7.4 Measured and rejected
| idea | result | source |
|---|---|---|
| LADE lookahead (Genie) | -14% but changed answers ("flatline/sensor_fault" -> "flat78/normal") | 2.14 |
| grammar-constrained decoding | +440 ms init, 0 tokens saved | 2.16 |
| continuous batching (QAIRT 2.50) | truncated answers | 2.25 |
| two resident NPU models | board rebooted | 2.27, 2.37 |
| reasoner on GPU | pp1 7.35, pp3 8.44, tg 8.35 t/s, ~2.5x slower | 2.59 |
| single-stream MTP / n-gram | slower | 2.53 |
| Q4_0 lm_head | -4% but moved an RWH label | 2.53 |
| v8x4 row padding | +11-15% | 2.61 |
| split 4 / 6 / 3r | +1% / does not fit (HTP0 mapping failed) / 0% | 2.56b, 2.59 |
| Hexagon SDK kernel / upstream llama.cpp | net about zero | 2.54 |
| 2B on GPU | 9-10 tok/s | TUNE.md |
| 2B CPU decode + GPU prefill | cold 27 s, no warm gain | TUNE.md N, P |
| 2B MTP / n-gram | 6.4-7.3 / ~7.9 vs 8.0 tok/s | TUNE.md E, F |
| 2B `-ub 256/512` | 260-520 tokens re-prefilled | TUNE.md O, P |
| 2B `-t 8`, `-tb 7/8` | slower / no gain (little cores) | TUNE.md K, Q, R |

---

## 8. Evaluation day (2026-11-04) in full

Source unless stated: `proofs/2026-11-04_split/README.md`, HANDBOOK 2.73.

### 8.1 The chat split (decision)
- The 2B r2 won chat (0.737 vs 0.477) and lost reports (severity 0.793 vs 0.919). Owner decision: **for the evaluation
  only**, chat on the 2B; reports and agents stay on the NPU (4B, 3B). The 4B keeps training to become the single model.
- Website decision D133 / group G35.

### 8.2 Building llama-server
- The Docker toolchain image pull stalled at ~10 MB/min (`gpu/pull.log`). `gpu/native_build.sh` built llama-server
  natively in **3 min**: NDK r29, upstream llama.cpp 338fce6, OpenCL on, Hexagon off. It ships its own libs to
  `/data/local/tmp/chatgpu/lib`, so the NPU libs are untouched. Model file `/data/local/tmp/gpu/rsn_v3_2b_r2_q4_0.gguf`
  (`gpu/STAGE.md`, md5s listed there).

### 8.3 GPU stage 1 (02:30 IST, `gpu/STAGE.md`)
- 2B on the GPU next to the live app. Chat cold 13.99 s (prefill 2,865 tokens at 330 t/s, gen 8.0 t/s); warm 6.5 s
  (520 tokens re-prefilled). During an incident 6.7 s.
- Fastcheck with the 2B resident: fast alert 5.8 s, AI report 28.0 s, valid (baseline 5.6 / 28 s). Guard kills 0.

### 8.4 Flag sweep, rounds A-R (`gpu/tune/TUNE.md`)
5 warm questions per config, greedy; **every config gave text identical to config A**.

| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s |
|---|---|---|---|---|
| A (stage-1 GPU flags) | 13.0 | 6.8 7.1 10.1 4.0 | 520 | 8.0 |
| B `-cms 0` | 13.1 | 6.9 7.1 10.3 4.1 | 520 | 7.9 |
| C `-cms 0 -ub 128` | 14.7 | 5.6 6.0 9.2 3.0 | ~136 | 8.0 |
| D `-t 4` | 12.5 | 6.2 6.4 9.2 3.8 | 520 | 9.1 |
| E MTP | 15.5 | 7.6 8.2 11.9 4.8 | 520 | 6.4-7.3 |
| F n-gram | 13.2 | 6.8 7.1 10.2 4.1 | 520 | 7.9 |
| G `-t 4 -ub 128` | 14.3 | 5.1 5.3 8.1 2.7 | 136 | 9.0 |
| H `-t 6 -ub 128` | 13.8 | 4.7 5.0 7.6 2.5 | 136 | 10.0 |
| I `-t 4 -ub 64` | 17.7 | 4.9 5.2 7.9 2.5 | 72 | 9.1 |
| **J CPU `-t 6`** | 18.0 | 2.5 2.7 3.7 1.7 | 136 | **25-26** |
| K CPU `-t 8` | 22.6 | 4.5 4.1 5.4 2.8 | 136 | 11.6-20.3 |
| L CPU `-t 4` | 21.7 | 2.7 2.9 3.9 1.9 | 136 | 24-25 |
| **M CPU `-t 5`** | 20.3 | 2.6 2.8 3.8 1.9 | 136 | 25 |
| N CPU + GPU prefill | 27.4 | 2.9 3.0 4.1 2.0 | 136 | 23.7 |
| O CPU `-ub 256` | 20.1 | 3.7 3.9 4.9 2.9 | 264 | 24.3 |
| P CPU + GPU prefill `-ub 512` | 20.0 | 5.6 5.8 6.8 4.9 | 520 | 24.8 |
| Q CPU `-t 5 -tb 8` | 20.6 | 2.6 2.8 3.7 1.9 | 136 | 26.3 |
| R CPU `-t 5 -tb 7` | 23.0 | 2.8 2.9 3.8 1.8 | 136 | 25.5 |

Deployed: **CPU `-t 5 -tb 5 -cms 0 -ub 128`** (round 6 note in TUNE.md).

### 8.5 Why the 2B moved GPU -> CPU
- Qwen3.5 is a **hybrid** model: some layers are recurrent (gated delta-net style). In llama.cpp's OpenCL backend those
  recurrent ops run on the CPU, so every layer syncs GPU and CPU. Result: ~9-10 tok/s on the GPU vs ~25 on 5-6 CPU
  cores with identical text. 8 threads is slower because the little cores join.
- The GPU was 2.7x slower in the answer path (ppt slide 4); the same four questions took 10.2 / 18.8 / 26 / 42.3 s on the
  GPU build vs 7.0 / 11.6 / 13.8 s and ~28 s on the CPU (ppt slide 16 notes).

### 8.6 The checkpoint / keep-warm fix
- llama-server can resume a Qwen3.5 (hybrid) prompt only from a **checkpoint**, which sits about one micro-batch before
  the end of each prompt (it cannot trim recurrent state token by token). The hourly time line in the prompt comes right
  after the 15-tool header, so before the fix every new question re-prefilled **~3,100 tokens** (11.8-14 s on the GPU).
- Fix (APK split3 onward): keep-warm sends the header alone, then the hour's prefix, every 30 s, ~4 tokens per ping once
  warm, so a checkpoint sits exactly at the shared prefix. A new question re-prefills **~290 tokens** (1.7 s on the GPU).
  `-cms 0 -ub 128` keeps the checkpoint close to the end (~130 tokens instead of ~520 re-prefilled for a warm question).

### 8.7 Deploys 28-32
Every deploy: snapshot known_good, install APK with the split off (chaos 2 + fastcheck), then split on, fastcheck again
with the 2B resident, 6 chat checks, guard-kill count (`deployNN/STATUS.md`).

| deploy | time | APK | what changed | checks |
|---|---|---|---|---|
| 28 | 03:35 | split2 46c14b58 (from e0ccda2b) | split on, 2B on GPU; chat timeout 2 min -> 60 s | fastcheck 5.7 / 27.8 s both phases; kills 0 |
| 29 | 03:49 | split3 b619e7a1 | header-only checkpoint keep-warm (GPU) | 5.6 / 27.8 s; with 2B 5.6 / 33.0 s |
| 30 | 04:07 | split5 7427684d | 2B on **CPU**; badge from `chat_device`; chat never waits for NPU; fallback to htpd + 60 s skip | 5.6 / 21.4 s; with 2B 5.6 / 27.7 s |
| 31 | 04:43 | split6 0957f89f | repeated-tool-call guard; header pre-warm (`warm.json`) after each server (re)start | 5.7 / 28.0 s; with 2B 5.6 / 27.7 s |
| 32 (live) | 05:24 | split7 9e82675a | chat UI names the engine | 5.6 / 22.6 s; with 2B 5.6 / 27.9 s; chat during incident 6 s |

### 8.8 Repeated-tool-call guard (deploy31)
An identical repeated tool call within one question is dropped; a round of only repeats ends the question. Before it,
the 2B looped once for 62.9 s ("pm25 sensr on KH lvl 3 kharab hai kya?", d30 blind2); on deploy31 that question took 13.5 s.

### 8.9 Pre-warm and the engine label
- `chat_gpu.sh` pre-warms the header after every server start (`gpu/warm.json`). `split_on.sh` waits for the pre-warm
  before adding the profile keys, so the first answer is warm.
- Chat UI label (deploy32): model badge "· qwen3.5-2b rsn_v3 (cpu)" when `chat_url` is set; nothing for a fast router
  answer; "on the NPU" only for a slow answer without a badge (before: always "on the NPU").

### 8.10 160-question comparison, d27 (4B NPU) vs d30 (2B CPU) (`CMP_d27_d30.md`)
| set | run | answers | errors | router < 1 s | median s | model answers | model mean s | model max s |
|---|---|---|---|---|---|---|---|---|
| s1 | d27 4B | 40 | 0 | 34 | 0.2 | 5 | 9.2 | 9.6 |
| s1 | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 10.9 | 14.3 |
| heldout | d27 4B | 40 | 0 | 35 | 0.2 | 5 | 12.4 | 17.2 |
| heldout | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 8.4 | 11.5 |
| blind | d27 4B | 40 | 0 | 38 | 0.2 | 2 | 10.1 | 10.7 |
| blind | d30 2B | 40 | 0 | 38 | 0.2 | 2 | 13.4 | 18.7 |
| blind2 | d27 4B | 40 | 0 | 35 | 0.2 | 5 | 11.4 | 14.9 |
| blind2 | d30 2B | 40 | 0 | 35 | 0.2 | 5 | 21.4 | 62.9 |

- d30: 160/160 answered, 0 errors, router 143/160. Read side by side (not graded against ground truth): the 2B was
  better on about 6 of 17 (e.g. "shw me critcal alrts": it lists them; the 4B said "no critical incidents"), worse on 1-2
  (power spike), the rest equal or weak for both.

### 8.11 blind2 re-run (deploy31)
40/40 answered, 0 errors, model mean 10.2 s (4B: 11.4 s); the looping question 13.5 s instead of 62.9 s (HANDBOOK 2.73).

### 8.12 Fallback rehearsal (`fallback_rehearsal.txt`)
- `split_off.sh`: 3.8 s; the 4B answered next in 6.1 s ("Open HVAC incidents: 15; worst status: warning").
- First `split_on.sh`: 6 s, but the first 2B answer queued 45.3 s (no pre-warm wait). After the fix, `split_on.sh`
  takes ~43.6 s (waits for pre-warm) and the first answer took **5.7 s**.

### 8.13 Cold-start finding (`FINAL_CHECK.md`, 09:34 IST)
- First incident after 4 h idle: fast alert 6.9 s, AI update **77.9 s** (valid, sensor_fault, "CO2 sensor fault (stuck):
  KH building, level 03"). Agents and reasoner themselves took 23.5 s; the rest was waiting before the AI started.
- Next run at 09:37: fast 5.6 s, AI 28.0 s.
- So: **warm up 10-15 min before the evaluation** (trigger one incident or run `fastcheck.py`, then open the chat once)
  (`DEMO.md`).

### 8.14 Guards for the 2B server
- `oom_score_adj 1000` (killed first under memory pressure); killed when MemAvailable < 700 MB; restarted only at
  >= 1.5 GB free and < 80 C. 0 guard kills across deploys 28-32 (HANDBOOK 2.73; `chat_gpu.sh`).
- Memory seen: ~2.3-3.3 GB available with the 2B resident after chat (`deploy3*/STATUS.md`).
- Temperature: 61-95 C seen during deploys (e.g. 93 C before the 2B started in deploy32).

### 8.15 Website
Rebuilt and deployed at ~09:40 IST (`proofs/2026-11-04_split/website_1104.log`, verify ok). See `teachWeb.md`.

---

## 9. Operations

- **Deploy pattern** (`proofs/2026-10-29_latency/deploy*.sh`, `proofs/2026-11-04_split/deploy*_split*.sh`):
  1. snapshot `known_good` (APK + htpd_profile);
  2. stop app, push files as `.part` + md5 + `mv`, start;
  3. **chaos 2** (scenarios through the app) + **fastcheck** (critical breach -> fast incident -> AI update);
  4. any failure -> automatic rollback to known_good; chat problems -> fix forward (owner).
- **Split control (WSL):** `bash proofs/2026-11-04_split/split_off.sh` (~4-10 s, no app restart; removes `chat_url`,
  `chat_think`, `chat_device` from htpd_profile, which the app reads each call; stops llama-server).
  `split_on.sh` (~45 s, waits for health + pre-warm). Full revert: `deploy28/known_good/` (APK e0ccda2b + profile).
- **Safety rules:** never reboot the board; one NPU client at a time (stop and wait for exit); big files `.part` + md5 +
  `mv` with the app stopped; requests start at <= 60 C; never touch personal config.
- **Logs and proofs:** board `htpd.log`, `agent.log` (severity disagreements) under the app dir; everything measured
  lives in `proofs/<date>_<topic>/` with raw data, scripts, STATUS/VERDICT. Agent registry: `proofs/AGENT_REGISTRY.md`.
- Warm-up command: `cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast/scripts && python3 -I fastcheck.py`.

---

## 10. Decision log

| decision | why | source |
|---|---|---|
| Everything on the board, no cloud | privacy, offline, seconds | G01; ppt 22 |
| One fine-tuned 3B for all 6 domain roles | 20% -> 94%; two resident models reboot the board | 2.7, 2.27 |
| llama.cpp Hexagon (htpd), not Genie | Genie dropped batching; GPU 8.4 s/agent with no batch gain | 2.37 |
| 4 h window, 8-reading gate | best window; young events misread | 2.38, 2.39 |
| Ship v2 despite the 3 h miss | 40 min 42 -> 73.8%; false alarms 31 -> 18% | 2.42 |
| v2 is the final domain retrain; gains by blends + post-rules | top-ups at noise floor | 2.48, 2.54b |
| B50 over T30 | T30 failed gate2 head to head | 2.54b |
| Reasoner chosen after P0 (Qwen3.5-4B) | best total score | D126 |
| Reject rsn_v2 | accuracy before latency | D127 |
| Split decoding; verified drafts | cut sequential steps, same answers | D128, D129 |
| Critical fast path, accept 8-reading gate otherwise | early AI unreliable; criticals cannot wait | D130 |
| Reasoner stays on the NPU (not GPU) | GPU 2.5x slower | D131 |
| Chat: Go router first, read-only tools | 0.2 s, exact numbers, safety | D132 |
| Eval-day split: 2B chat CPU, 4B reports NPU | each model where it scores best | D133 |
| 2B on CPU, not GPU | 25 vs 9-10 tok/s, same text | TUNE.md |
| Fix forward with automatic rollback | every deploy proven through the app | D134 |
| Human approval for every action | operators decide; no actuation path | 2.44 |
| Accuracy first, then latency | rsn_v2 and T30 rejected | memory rule |
| Host GGUF as proxy | 207/208 rows agree with the board | 2.45 |
| Private data, public evidence | encrypted site with aggregates only | 2.36 |

---

## 11. Honest limits and what comes next

**Limits** (ppt slide 26):
- Non-critical events reach the AI after 40-55 min; power, tank level and flow have no fast path.
- Heat: heavy NPU work reaches 84-97 C on the hottest zone; needs a heatsink (HANDBOOK 2.62).
- NPU not bit-for-bit repeatable (severity 97%, 100% with the guard).
- Weak shapes: recurring small spikes, pump cycling, erratic at 3 h; TDS rules-only.
- Chat: blind questions still expose gaps; two models on eval day; the 2B's report quality is worse.
- Cold start: first incident after hours idle ~78 s.
- One campus; fog/cloud store not built.

**Next** (ppt slide 27): one general model (rsn_v3 4B must beat rsn_v1 on reports and the 2B on chat, then the split
goes away); earlier AI (young-window training; provisional AI built, off); cheaper reasoner reload; chat: fresh blind set
after every fix, streaming, chat about the open incident; fog layer on free Supabase.

### 11.1 Prototype vs production (`PRODUCTION_GAP.md`, HANDBOOK 2.75)

If asked "what would it take to deploy this for real?":
- **Security is documented, not built.** The app reaches the NPU through adbd on 127.0.0.1:5555 with no auth (it may
  listen on the LAN in tcpip mode; bind address unknown). The API on port 8000 is plaintext and its reads (incidents,
  per-room occupancy) are open on the LAN; only off-device writes need `X-API-Token`. Production: no adb (system service
  or QCS-class IoT SKU), auth + TLS for reads, per-device keys, operator PIN + audit log, signed updates, isolated network.
  Why skipped: a dev kit on a lab bench with replayed data; hardening changes nothing the evaluation measured.
- **In progress now (not done):** MQTT ingest bridge, time sync (the RTC resets to 2023 at boot), off-board alerts with
  escalation, heartbeat + dead-man alert, fog uploader (Supabase), early provisional AI + automatic warm-up, OTA with
  signing and self-test rollback.
- **Hardware / process:** DC supply + UPS, heatsink + enclosure + 40 C soak, shadow mode for 2-4 weeks, canary board,
  one-floor pilot with real sensors, IS 10500 / CPCB limits check, DPDP notice + retention policy.

---

## 12. Likely evaluator questions

**Does everything run on the board?** Yes. Agents and reports on the NPU, chat on the CPU, all on the QIDK, offline.

**Why two different models for chat and reports today?** Measured: the 2B scores 0.737 vs 0.477 on 300 chat questions
but 0.793 vs 0.919 severity on 150 real-world reports. For the evaluation each runs where it is best. The 4B is being
trained to do both, then the split goes away.

**Why is the chat model on the CPU and not the GPU?** Qwen3.5 is hybrid; its recurrent layers run on the CPU in llama.cpp,
so the GPU path syncs every layer. Measured 9-10 vs 25 tok/s, identical text (TUNE.md).

**How fast?** Critical breach -> incident 5.6 s; AI report ~28 s later; preliminary at once. Router chat 0.2 s median;
model chat 7-14 s.

**Why 40-55 minutes for normal events?** One reading every 5 min, 8 readings needed; young windows read 42% vs 88% at 3 h.
Criticals use the fast path.

**Why not two models on the NPU?** It rebooted the board (unmovable NPU memory). We swap in 2.8 s.

**How accurate?** rsn_v1 severity 91.9%, label 87.8% on 150 held-out; agents 90.7% pattern on the board (htpd).

**Can the AI act?** No. Validator, severity guard, human approval; chat tools are read-only and refuse actions.

**What if the chat server dies?** Per call fallback to the 4B on the NPU; `split_off.sh` in ~4 s.

**Is the NPU deterministic?** No; near-ties flip wording; severity 97% / 100% with the guard.

**What did you reject?** rsn_v2, GPU (reasoner and 2B), LADE, grammar decoding, continuous batching, row padding, split
4/6/3r, MTP/n-gram outside split, T30, Hexagon SDK kernel.

**Why the first incident slow?** Cold start after 4 h idle: 78 s once, then 28 s; we warm up before demos.

**Why your own daemon?** Genie dropped batching; htpd batches agents, splits the reasoner, verifies drafts, guards.

**How do you know numbers are real?** Paired tests on the same rows, app-level checks after every deploy, host proxy
207/208, proofs folders with raw data.

---

## 13. Glossary

| term | meaning |
|---|---|
| QIDK | Qualcomm Innovators Development Kit (the board) |
| SM8650 | Snapdragon 8 Gen 3 SoC |
| NPU / HTP / Hexagon V75 | the neural processor; HVX = vector units, HMX = matrix units |
| Adreno 750 | the GPU; OpenCL backend in llama.cpp |
| GGUF, Q4_0 | llama.cpp model file; 4-bit weight format |
| Genie / QAIRT | Qualcomm's own LLM runtime / AI runtime SDK |
| htpd | our llama.cpp Hexagon daemon |
| llama-server | llama.cpp's HTTP server (used for the 2B chat) |
| ft_B50 / mixA50 / v2 | domain-agent model versions (B50 live) |
| rsn_v1 / v2 / v3 | reasoner versions (v1 live for reports; v3 2B r2 for chat today) |
| RWH, RWH-2 | real-world held-out report suites (150 each) |
| P0 | the reasoner model-choice benchmark |
| chat dev v3 | 300-question chat gate set |
| gate2 | paired acceptance test for agents |
| QLoRA, LoRA | parameter-efficient fine-tuning |
| GPTQ | post-training int4 quantisation |
| BOS | beginning-of-sequence token (double BOS caused the quant gap) |
| WiSE-FT / blend | weight interpolation between models |
| DPO | direct preference optimisation (3e top-up, rejected) |
| split decoding | head once, then parallel field streams |
| verified drafts / speculative decoding | proposed tokens checked by the model; kept only if equal to greedy |
| ALIGN | pad streams to equal rows per step |
| MTP | multi-token prediction head |
| OPPOLL | Hexagon op polling flag |
| prefill / decode | processing the prompt / generating tokens |
| checkpoint (hybrid) | saved recurrent state llama-server can resume from |
| `-cms`, `-ub`, `-t`, `-tb` | llama-server cache-min-size, micro-batch, threads, batch threads |
| fast path | critical incident opened without the AI |
| preliminary report | rules + retrieved wording, before the AI |
| validator / policy gate | checks every AI report |
| severity guard | AI may not say normal when rules say warning/critical |
| chaos 2 / fastcheck | post-deploy app tests |
| known_good | rollback snapshot |
| fog | intermediate storage layer (Supabase, not built) |
| Hinglish | Hindi-English mix |
| replay clock | demo time: one reading every 2 s |

---

## 14. File map

| what | where |
|---|---|
| Backend (Go) | `Code/smart-city-edge-agent/app/backend/` (`engine.go`, `fastpath.go`, `reason.go`, `retrieval.go`, `reasoner_v3.go`, `postrules.go`, `dataquality.go`, `earlyai.go`, `workflow.go`, `phdir.go`, `chat*.go`, `chat_header15.txt`) |
| Chat UI | `Code/smart-city-edge-agent/app/device/web/chat/` |
| Training | `Code/smart-city-edge-agent/training/` ; rsn_v3 chain `proofs/2026-10-29_rsn_v3/kaggle/` |
| Eval-day split | `proofs/2026-11-04_split/` (README, DEMO, FINAL_CHECK, CMP_d27_d30, deploy28-32, gpu/, split_on/off.sh) |
| Gate results | `proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r1`, `g2b_r2` |
| Chat sweeps | `proofs/2026-11-01_chat/` (VERDICT*.md, sweep*.jsonl) |
| Latency deploys 8-27 | `proofs/2026-10-29_latency/`, `proofs/2026-11-03_deploy27/` |
| Fixes 3 Nov | `proofs/2026-11-03_fixes/README.md` |
| History | `HANDBOOK.md` (2.x), deck `ppt.md`, `app.md`, `PRD.md`, `plan.md`, `latency_roadmap.md`, `training_plan.md` |
| Website | `Website/` (src/pages, build/collect, HAANDBOOK.md); guide `teachWeb.md` |
| Agent registry | `proofs/AGENT_REGISTRY.md` |
