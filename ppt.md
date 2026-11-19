# Agentic Edge AI for Smart Cities: final evaluation deck

Final evaluation, 2026-11-04, 12:00 IST. Team NASA (esw-m26-14).

How to read this file: one slide per block, separated by `---`. Each slide has a title, 3-6 bullets or a small
table, and **Speaker notes** that name the source file of every number. Numbers are measured on the QIDK board
unless marked "host" (the laptop running the same Q4_0 model file; host and board agree on 207 of 208 rows,
HANDBOOK 2.45).

---

## 1. Agentic Edge AI for Smart Cities

- Building sensors on the IIIT-H campus (air quality, water, power, HVAC, occupancy, weather) watched by an
  agentic AI system that explains what is wrong, cites its evidence and asks a person before anything is done.
- **Everything runs on one Qualcomm QIDK board**: Snapdragon 8 Gen 3 (SM8650), Hexagon V75 NPU, Adreno 750 GPU,
  Android 14. No cloud, no laptop at run time.
- Two fine-tuned language models on the NPU (domain agents and a cross-domain reasoner), plus a chat assistant.
- Every number in this deck has a proof folder in `proofs/`.

**Speaker notes:** We will follow one alarm from the sensor to the person who fixes it, then show how fast
each step is, why it is that fast and not faster, what we tried and threw away, and what the models score.
Board facts: HANDBOOK 2.37 and `proofs/2026-10-16_hw_grid`. Data: SCRC-IHub campus sensor data (PRD.md 5.1).

---

## 2. The problem

- A campus has thousands of threshold breaches a year: **20,538** in our cleaned sensor data, most of them short.
  A threshold alarm says "CO2 high" and stops.
- The operator needs to know **why**: people in the room, failed ventilation, or a faulty sensor? The answer
  often crosses domains (a crowded room raises CO2, power and cooling load together).
- The data is private: room-level occupancy over time shows where people are.
- The network can fail; monitoring must not.
- So: explain on the device, offline, with evidence, and keep a person in charge of every action.

**Speaker notes:** 20,538 breaches: Website collector `rawdata.py` output, logged in Website/HAANDBOOK.md
(2026-10-19 evening, "breaches 19,819 -> 20,538"). Cross-domain motivation: PRD.md section 2. Privacy: decision
G30 on the website (HANDBOOK 2.36). We do not show per-room occupancy anywhere in this deck.

---

## 3. What the system does, in one story

- KH building, level 3: the CO2 sensor jumps to 2000 ppm.
- **~5.6 s later** the incident is open (critical fast path) with a preliminary report and a live checklist.
- **~28 s after that** the AI report lands on the same incident: title, severity, root cause, causal chain,
  evidence ids, claim checks on the agents and a checklist.
- The operator acknowledges ("I'm on it"), ticks steps, closes with an outcome. Nothing is switched by the AI.
- At 1.5 h and 3 h of sensor time the incident is re-checked; it can be raised, lowered or resolved.
- The operator can also ask the **Campus Assistant** in English or Hinglish: "CO2 theek hai KH level 3 pe?"

**Speaker notes:** Latest board fastcheck (deploy27, APK e0ccda2b): fast path 5.6 s, AI update 28.0 s and 32.7 s
on two runs, `proofs/2026-11-03_deploy27/apk/STATUS.md`. The Hinglish question is from the same file's chat check
(routed, answered in 0 s with `current_levels`). Re-checks: HANDBOOK 2.39 and 2.43.

---

## 4. What runs where (evaluation day)

| part | what | where |
|---|---|---|
| backend | Go `edge-agent`: rules, data-quality gates, event gate, workflow, API, retrieval, validator, chat router | CPU |
| domain agents | **ft_B50**: our fine-tuned Llama 3.2 3B, one agent per abnormal sensor, all in one batch | NPU (resident in htpd) |
| reasoner | **rsn_v1**: our fine-tuned Qwen3.5-4B, writes the cross-domain report | NPU (swapped in per incident) |
| NPU daemon | **htpd**: our llama.cpp Hexagon server (batching, split decoding, verified drafts, guards) | CPU + NPU |
| chat model (eval only) | **rsn_v3 r2**: our fine-tuned Qwen3.5-2B, llama.cpp llama-server | **CPU, 5 threads** (GPU measured: 2.7x slower) |
| apps | Smart City Edge (dashboard) and Campus Assistant (chat): two launcher icons, one backend | phone UI |

- One model on the NPU at a time; htpd swaps agents and reasoner. The chat model never touches the NPU.
- If the chat server fails, chat falls back to the 4B on the NPU automatically.

**Speaker notes:** Live stack: `proofs/2026-11-04_split/deploy32/STATUS.md` (split7 APK 9e82675a, htpd_v9f, rsn_v1
Q4_0 for reports, 2B on the CPU for chat). Split design and steps: `proofs/2026-11-04_split/README.md`. We first ran
the 2B on the Adreno GPU (deploy28/29) and measured ~9-10 tok/s: Qwen3.5 is a hybrid model whose recurrent layers run
on the CPU anyway, so every layer synced GPU and CPU. On the CPU alone it decodes ~25 tok/s with identical output
(`proofs/2026-11-04_split/gpu/tune/TUNE.md`, rounds 3-4).

---

## 5. The pipeline

1. **Ingest**: readings every 5 min per sensor (`/api/ingest`), bucketed, de-duplicated, gaps detected.
2. **Rules + event gate**: an abnormal status for **8 readings** in a **4 h window** opens an event; co-occurring
   sensors are batched into one incident.
3. **Critical fast path**: 2 fresh readings past a critical limit open the incident at once (no AI wait).
4. **Domain agents** (B50, NPU): one per flagged sensor, all decoded together.
5. **Cross-domain reasoner** (rsn_v1, NPU): one report across all findings.
6. **Validator + policy gate**, then **operator approval**. Re-checks at 1.5 h / 3 h; 12 h drift and level-shift checks.

**Speaker notes:** Gate and window: HANDBOOK 2.29, 2.38 (`engine.go` Window 48 points x 5 min = 4 h). Fast path:
HANDBOOK 2.55. Agents in one batch: 2.37 (htpd). Reasoner: 2.53. Validator: 2.67 and `reasoner_v3.go`.
The chat assistant (slides 13-15) is a second front end on the same backend and tools.

---

## 6. Sensor data you can trust: ingest, data quality, sensor faults

- Timestamped feeds bucketed per 5 min; duplicates, late and out-of-order readings handled. Replaying 5 real
  CO2 outages, the old ingest invented 91 readings; now **0**.
- A sensor with too many gaps is "insufficient data" with a reason, not a guess. Silent sensors are said to be
  silent (chat too: "no new reading, last value X").
- A single glitch does not open an incident; a value chattering at a limit is suppressed (event gate only; the AI
  still sees the raw window).
- **Sensor-fault detection**: seven fault kinds (stuck, quantised, offset, drift and others) are a separate
  status (`sensor_fault`), never mixed with process alarms; a physically impossible value (indoor CO2 < 350 ppm) is a fault.
- Maintenance API: mark a sensor out of service or replaced; a fault returning within 30 days of a repair suggests replacement.

**Speaker notes:** HANDBOOK 2.46 (`dataquality.go`, `proofs/2026-10-23_realworld/REALWORLD.md`), 2.35 (CO2 floor),
2.40 (seven fault kinds in v2 training), 2.49 (30-day repair rule, maintenance buttons), 2.68 (silent sensors in chat).

---

## 7. When to call the AI: the 4 h window, re-checks and 12 h checks

- **4 h is the best single window** for the agents: pattern 64% vs every other length significantly worse
  (2,416 NPU calls; p < 0.0001).
- **Young events are hard**: the same 208 events read right 42% at 40 min after onset and 88% at 3 h. So the
  first report is refined automatically at **1.5 h and 3 h**, with a window chosen by the event's shape.
- Re-checks can **elevate** (only if the problem is visible now), **curb** (only if AI and rules both read lower)
  or **resolve** (back at baseline for 30 min).
- **12 h CPU checks** for level shifts and slow drifts: old steps caught 73% -> 93%, drifts 83% -> 95%, no new false alarms.

**Speaker notes:** Window study: HANDBOOK 2.38, `proofs/2026-10-16_window_study/RESULTS.md`. Placement study:
2.39, `proofs/2026-10-16_placement_study` (1,248 calls). Shape-based window: 2.42 (3 h 86.3% vs 80.8% for the old
ladder on a fresh seed of 182 events, McNemar p = 0.021). 12 h checks: 2.39, `proofs/2026-10-16_longrange`
(p = 0.0005 and p = 0.016). Re-check rules: 2.43, 5/5 cases through the app.

---

## 8. The first seconds: critical fast path and the preliminary report

- **Critical fast path**: 2 fresh readings beyond a critical limit open the incident at once, severity critical,
  no NPU. The AI later updates the **same** incident.
- After a sensor has been silent, a critical reading skips the coverage rule for the fast incident only: CO2 2000 ppm
  after a 17-min silence opened in **2.6 s** (before: 44-46 s).
- **Preliminary report in the same second** (< 5 ms CPU): hybrid retrieval of the most similar past AI reports
  (70% structured match + 30% TF-IDF), rewritten with the live numbers; severity = max(rules, retrieved), so it
  never under-alerts. Library: every validated live report + 254 seed reports.
- The checklist is live at once: acknowledge and tick while the AI writes; the AI report merges in without
  losing ticked steps.

**Speaker notes:** Fast path: HANDBOOK 2.55 (`fastpath.go`, tests in `fastpath_test.go`). Gap bypass: 2.67,
deploy22 r3, `proofs/2026-10-31_validator/gap_r3.txt` (INC-0605). Retrieval: 2.57 and 2.57b
(`retrieval.go`, `proofs/2026-10-28_master/RAG_STATUS.md`; 320 seeds generated, 254 kept). Checklist merge: 2.59.
Power, tank level and flow have no fixed critical limits, so they have no fast path (honest limit).

---

## 9. Domain agents: ft_B50 on the NPU

- One QLoRA fine-tune of **Llama 3.2 3B** plays six roles (air quality, water, power, HVAC, occupancy, weather).
- Trained on **35,946** rows built from real campus windows: windows of 2-12 h, young and old events, seven sensor
  fault kinds, routines that look like alarms but are normal, HVAC faults (AC in an empty room -> `switch_off_ac`,
  a recommendation only).
- **B50** = v2 -> mixA50 (weight blend) -> half of one more LoRA top-up blended in. Chosen by **gate2**, a paired
  acceptance test: severity-weighted net **+61** vs the previous live model, story suite +4, safety 16/16, no slice worse.
- All agents of an incident run in **one NPU batch** in htpd; post-rules check limits, glitches, chatter and allowed causes after the model.
- Agent request time with verified drafts from an index of 500 recent agent outputs: **2.59 -> 2.06 s** (-21%), 23/24 identical.

**Speaker notes:** Data: HANDBOOK 2.40, `training/RETRAIN_V2_SPEC.md`. B50: `proofs/2026-10-25_domain_plan/B50_STAGED.json`,
HANDBOOK 2.54/2.54b. Post-rules: 2.50 (`postrules.go`). Agent drafts: 2.65, `proofs/2026-10-31_agents_latency/VERDICT.md`
(the one changed output was a reworded observation with identical verdict fields; the owner accepted it).

---

## 10. The cross-domain reasoner: rsn_v1 (Qwen3.5-4B) on the NPU

- Reads every agent's finding plus the related sensors; writes title, severity, label, root cause, causal chain,
  observations with evidence ids, **claim checks on the agents**, and a checklist.
- Chosen in the P0 benchmark (Qwen3.5-4B vs 2B vs our 3B): best total score, +0.16 over the 2B. Then QLoRA r32 on
  the laptop (about 21 h).
- **Split decoding**: the head (title, severity, label) is written once, then 3 field groups decode in parallel.
- **Verified speculative drafts inside the split**: each stream proposes tokens from the prompt and from a corpus of past
  reports by the same model; the NPU verifies them greedily. Reasoner 23.3 s -> **9.1 s** in the lab, severity + label 6/6.
- The draft corpus learns from the app: every finished report is added (repeated incidents 4.6-5.1 s).

**Speaker notes:** P0: `proofs/2026-10-23_reasoner_research/P0/host_bench/RESULTS.md`. Split: HANDBOOK 2.53.
Spec drafts: 2.63, `proofs/2026-10-30_spec_split/SIM.md`, lab `proofs/2026-10-29_latency/spec_ab`, `tune_ab`
(K=8 + ALIGN). Live corpus: 2.64, `proofs/2026-10-31_latency/VERDICT.md` (11.83 -> 8.89 s, 8/8 severity + label).
Text differences appear only in late list fields and match the board's run-to-run noise (base vs itself 2/6 identical).

---

## 11. Safety: validator, policy gate and guards

- **Validator / policy gate** on every answer: valid JSON, allowed labels, real evidence ids, no actuation language,
  action floors by severity (a critical report must start with an inspection or facility review, except weather-only).
- **Contract repairs**: "normal + needs more data" -> label `unknown`; a title location not in the input is replaced;
  pH wording follows the measured direction. Label 83.2% -> 87.6% on 386 board answers, 0 new errors.
- **Severity guard**: the AI may not call it "normal" when the rules say warning or critical; disagreements are logged.
- Failed report -> deterministic fallback report, marked as such. The operator always gets a report.
- **Board guards**: one NPU client at a time; 150 s wall-clock limit per reasoner request; requests start at <= 60 C;
  thermal pacing; the 2B chat server has `oom_score_adj 1000` and is killed below 700 MB free (restarted only at >= 1.5 GB and < 80 C); big files pushed as `.part` + md5 + `mv`.

**Speaker notes:** Gate: HANDBOOK 2.7, 2.33. Validator floor: 2.67 (`v3ActionFloor`). Repairs: 2.59 (gold rules 151/151
and 5,761/5,761). pH fix: `proofs/2026-11-03_fixes/README.md` (from board INC-0660). Severity guard: 2.53.
Guards: 2.53, 2.58 (htpd_v8x3 150 s), 2.35, 2.43 and the memory file "QIDK safety". Chat-server guard: `deploy28_split.sh`
counts `GUARD KILL` lines; `chat_gpu.sh` in `proofs/2026-11-04_split/gpu`.

---

## 12. The operator's side: UI, approval workflow, reports

- Plain-language incident sheet: what is happening, why it matters, what to do, how sure the AI is, what changed at re-checks;
  jargon behind "Technical details"; an Engineering view for evaluators (off by default).
- **Approval workflow**: Needs decision -> In progress ("I'm on it", name picker) -> Resolved -> Closed with an outcome.
  Per-step checklist (Done / Not needed), append-only event log, re-acknowledge when it gets worse.
- 15-min re-alert for unacknowledged criticals, 24 h auto-close after recovery, Android notification for critical.
- "AI so far": title, severity and root cause appear while the reasoner is still writing, marked "not yet checked".
- Domain health tiles (worst first), shift summary, grouping of repeat incidents, filters and search, sensor history.
- **Self-learning data capture**: every call stores prompt, raw output, repairs and the operator's verdict; repairs become
  preference pairs with no labelling.

**Speaker notes:** UI: HANDBOOK 2.43 (`proofs/2026-10-21_ux/UX_RESEARCH.md`, design follows ISA-18.2 / EEMUA 191 /
ISA-101 and Microsoft's HAX guidelines), 2.49 (UX v34, `proofs/2026-10-23_ux_v34/`), 2.62 ("AI so far").
Self-learning: 2.28 (`training/feedback/export_feedback.py`).

---

## 13. Campus Assistant: ask the system

- A second app on the same backend (own launcher icon, and "Ask AI" on the dashboard). History kept on the board.
- **Router first**: a Go question-type layer answers most questions directly from read-only tools (counts, lists,
  current levels, faulty sensors, rankings, what-if against limits, period summaries, follow-ups like "which ones?").
- **Tool-calling model** for the rest: up to 5 read-only tool calls; every answer shows "How I found this" (tools and raw results).
- **Hindi / Hinglish and typos**: "kitne", "aaj", "kal", "kharab", "theek hai", "ghante/din" are understood.
- **Safety refusals**: close / approve / dismiss / delete / reset requests and prompt injections are refused
  ("my tools only read the device's data"). Invented incident ids and nodes are rejected by a guard.
- Alerts first: on the NPU, a question asked during an incident analysis is queued and answered when the NPU is free.

**Speaker notes:** HANDBOOK 2.60 (first version), 2.61 (keep-warm: about 5 s warm vs 8-14 s cold), 2.68 (`chat_router_ops.go`,
refusals), 2.69 (`chat_router_v24.go`, Hindi day words), 2.70 (`chat_router_v25.go`, `chat_time.go`, `chat_guard.go`),
`proofs/2026-11-03_fixes/README.md` (time-span guard on more tools). Refusal text: `proofs/2026-11-03_deploy27/apk/STATUS.md`.

---

## 14. Chat quality: measured on the board, question by question

| set (40 questions each) | before fixes | after fixes |
|---|---|---|
| sweep 1 (deploy22 -> 23) | 27/40, median 9.7 s | **39/40, median 0.2 s** |
| held-out (deploy23 -> 24) | 25/40, median 10.2 s | **39/40, median 0.02 s** |
| blind (deploy24) | 20/40 | fixed by the question-type layer (deploy25), no phrase patches |

- Latest 160-question run on the 4B build (deploy27): **142/160 answered by the router in < 1 s, median 0.2 s,
  0 errors, 0 busy**; the 18 model-routed answers took 8.8-17.2 s (one 1.4 s).
- Unsafe actions 3/3 refused and the injection refused on the blind set.
- Evaluation-day sweep: deploy30 (2B on the CPU), same 160 questions as deploy27: **160/160 answered, 0 errors, 0 busy**; router 143/160 (median 0.2 s, as before); 17 model answers: mean 8.4-13.4 s per set vs 9.2-12.4 s on the 4B, except one 63 s loop (the 2B repeated a tool call; repeats are now dropped, deploy31). Read side by side (not yet graded against ground truth): the 2B is better on about 6 of 17 (e.g. "show me critical alerts": it lists them, the 4B said "no critical incidents"), worse on 1-2 (power spike), the rest equal or weak for both. `proofs/2026-11-04_split/CMP_d27_d30.md`

**Speaker notes:** `proofs/2026-11-01_chat/VERDICT.md`, `VERDICT_heldout.md`, `VERDICT_blind.md`; HANDBOOK 2.68-2.70.
The 160-question numbers are computed from `proofs/2026-11-01_chat/sweep20_s1_d27.jsonl`, `sweep21_heldout_d27.jsonl`,
`sweep22_blind_d27.jsonl`, `sweep23_blind2_d27.jsonl` (wall_s per answer; these runs are not graded yet).
Honest note: the "after" scores reuse the questions the fixes were designed from; that is why the blind sets exist.

---

## 15. Evaluation day: chat on the 2B (CPU), reports on the 4B (NPU)

| model | chat dev v3 pass rate (300 q) | RWH severity | RWH check recall |
|---|---|---|---|
| rsn_v3 r2, Qwen3.5-2B | **0.737** | 0.793 | 0.405 |
| rsn_v1, Qwen3.5-4B | 0.477 | **0.919** | **0.848** |

- The 2B is better at chat, the 4B is better at reports. So **for this evaluation only**: chat runs on the 2B
  (llama-server on 5 CPU cores), reports and agents stay on the NPU.
- Bonus: a chat question no longer waits for an incident analysis on the NPU; reports are unchanged with chat
  running during an incident (fastcheck 5.6 s alert / 27.9 s AI report; the chat question asked mid-incident answered in 6 s). If the chat server fails, chat falls back to the 4B; each answer shows which engine produced it.
- **The 4B is being trained further (rsn_v3 4B) and will be the one general model on the device** (chat + reports).
- Measured on the board: 2B decode **~25 tok/s on the CPU vs ~9-10 on the GPU**; model answers 7-14 s fresh
  (long lists up to ~28 s); GPU placement was 10-42 s for the same questions.

**Speaker notes:** Gate: `proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md` (the 2B fails the report gate: RWH
severity 0.793 vs 0.919, check recall 0.405 vs 0.848, schema errors 0.147 vs 0.081; chat calls_ok 0.827 vs 0.65,
facts_ok 0.79 vs 0.61). Why r2 fixed chat: `proofs/2026-11-02_2b_r2/DIAG.md` (a tokenization bug left the
"close the think block" token unlabelled in r1). Split: `proofs/2026-11-04_split/apk/README.md`,
`deploy28_split.sh`. 2B r2 training was stopped at step 1234 for the evaluation (`kaggle/STATUS.md`).

---

## 16. Latency today, stage by stage

| stage | time | where measured |
|---|---|---|
| reading -> rule status | every 5 min per sensor (demo replay: every 2 s) | design |
| non-critical event -> AI start | 8 readings = **40-55 min of sensor time** | HANDBOOK 2.55 |
| critical breach -> incident open | **5.6 s** (2.6 s after a silent gap) | deploy27 fastcheck; deploy22 r3 |
| incident -> preliminary report | same second (< 5 ms CPU) | 2.57 |
| one domain agent request | **2.06 s** (lab, 24 real requests) | 2.65 |
| reasoner swap (model load) | **2.80 s** (was 3.67 s); swap 3.3-4.1 s overall | 2.62, repack VERDICT |
| reasoner report | **8.9-9.1 s** lab (was 23.3 s) | 2.63, 2.64 |
| incident open -> AI report on it | **28.0 / 32.7 s** | deploy27 fastcheck |
| chat, router answer | **median 0.2 s** (142/160 < 1 s) | d27 sweeps |
| chat, model answer (4B, NPU) | 8.8-17.2 s; about 5 s when warm | d27 sweeps; 2.61 |
| chat, model answer (2B, CPU, eval day) | **7.0 / 11.6 / 13.8 s**; 28 s for a long list (GPU: 10-42 s) | deploy30-32, TUNE.md |

**Speaker notes:** The end-to-end AI number is larger than agents + swap + reasoner because the fastcheck waits for the
AI gate, the batch window and the swap back. Sources: `proofs/2026-11-03_deploy27/apk/STATUS.md`,
`proofs/2026-10-31_validator/gap_r3.txt`, `proofs/2026-10-31_agents_latency/VERDICT.md`,
`proofs/2026-10-29_latency/repack/VERDICT.md` (rp29 load 2.80 s vs 3.70 s, deployed as deploy14),
`proofs/2026-10-31_latency/VERDICT.md`, `proofs/2026-11-01_chat/sweep2*_d27.jsonl`. 2B chat numbers: fresh sessions
after a warm-up on deploy30 (questions: HVAC problems / power spike in 4 h / AC unit 24 history / everything critical
this morning); the same four on the GPU build took 10.2 / 18.8 / 26 / 42.3 s. Prompt-cache fix for the hybrid model:
`proofs/2026-11-04_split/README.md` step 4 (a new question re-prefilled ~3,100 tokens before, ~290 after).

---

## 17. Why the latency is what it is

- **Decode is at the memory-bandwidth roof.** Every token reads all weights from DDR: 3B agents ~2.2 GB/token at
  22.4 tok/s = 49.3 GB/s, ~84% of the measured 59 GB/s NPU DMA ceiling. The 4B reasoner: 60 ms/token, ~52 GB/s over 2.6 GB.
  So we cut **sequential steps** (batching, split streams, verified drafts), not per-step cost.
- **One NPU client at a time.** A second resident model rebooted the board (HANDBOOK 2.27, 2.37); NPU and GPU buffers are
  unmovable memory in a 7.26 GB zone. So the reasoner is swapped in per incident (2.8 s load).
- **Per-step time is all inside `llama_decode`** (97-123 ms per step; CPU pick + emit < 0.4 ms). No host overhead left.
- **Sensor time dominates real-world latency**: 8 readings x 5 min. Accepted for the prototype (young windows are read
  badly, 42% at 40 min); the critical fast path bypasses it, and every incident gets a report in the same second.

**Speaker notes:** HANDBOOK 2.15 (roof, Genie 3B), 2.53 (4B: 60 ms/token, RESEARCH.md), 2.62 (per-step profile with htpd
v8x5 timers), 2.27 and 2.37 (reboots, Normal zone), 2.55 and memory "Real-world latency" (gate accepted, fast path chosen).
`proofs/2026-10-27_reasoner_fast/RESEARCH.md` row 8: even a perfect kernel gives about 20 tok/s for a 4B Q4 model on 8 Gen 3.

---

## 18. The latency ladder: what made it faster

| step | before -> after | source |
|---|---|---|
| context 4096 -> 2048 (KV cache moved per token) | -721 ms per agent call, 14/14 identical | 2.22 |
| batch window closes early when no other sensor is young | -4 s per isolated incident | 2.29 |
| persistent daemon (genied) | agent call 3.64 -> 2.54 s | 2.24 |
| htpd: all agents in one NPU batch | 12-agent incident 46-48 s -> **20.7 s** | 2.37 |
| reasoner OPPOLL + split decoding | 27.8 -> 21.6 s | 2.53, 2.58b |
| verified drafts in split (htpd v9) + live corpus (v9d) | 23.3 -> 9.1 s; app AI update 52.6 -> 27.0 s | 2.63, 2.64 |
| agent draft index (v9e) | agents -21%; app AI update 21.7 s | 2.65 |
| chat router + keep-warm | chat 9-14 s -> median 0.2 s (router) / ~5 s warm (model) | 2.61, 2.68 |
| 2B chat: checkpoint-aware keep-warm (hybrid model) | new question re-prefill ~3,100 -> ~290 tokens (12 s -> 1.7 s on GPU) | 2.73 |
| 2B chat: GPU -> 5 CPU cores | decode 9-10 -> ~25 tok/s, same text; answers 10-42 s -> 7-28 s | 2.73, TUNE.md |

**Speaker notes:** Every row was checked for unchanged answers before it shipped (byte-identical where the NPU allows it,
otherwise severity + label against gold and the board's own run-to-run floor). The app AI-update numbers come from the
fastcheck after each deploy (HANDBOOK 2.63-2.66). Rule we follow: accuracy first, then bring latency back down (memory
"Accuracy then latency").

---

## 19. Latency ideas we measured and rejected

| idea | result | why it is out |
|---|---|---|
| LADE lookahead decoding (Genie) | -14% end to end, but "flatline/sensor_fault" became "flat78/normal" | changes answers (2.14) |
| grammar-constrained decoding | +440 ms init, 0 tokens saved | only masks logits on V75 (2.16) |
| continuous batching (QAIRT 2.50) | answers truncated | not shippable (2.25) |
| two models resident on the NPU | board rebooted | one model at a time (2.27, 2.37) |
| reasoner on the Adreno GPU | 7-8 tok/s, ~2.5x slower than the NPU | not a latency path (2.59) |
| single-stream MTP / n-gram speculation | slower (66 ms 1-row step baseline) | drafts pay only inside split (2.53, 2.63) |
| 2B chat on the Adreno GPU (deploy28/29) | ~9-10 tok/s vs ~25 on 5 CPU cores, same text | GPU<->CPU sync every layer (TUNE.md) |
| 2B chat: CPU decode + GPU prefill offload | cold 27 s, warm no better | weights copied per batch (TUNE.md N, P) |
| MTP / n-gram speculation for the 2B chat server | 6.4-7.3 / ~7.9 tok/s vs 8.0 baseline | slower or no gain (TUNE.md E, F) |
| decode row padding (htpd v8x4) | +11-15% slower | real steps do not follow the bench table (2.61) |
| split 4 / 6 / 3r | +1% / does not fit / 0% | longest stream sets the time (2.56b, 2.59) |
| Hexagon SDK kernel / upstream llama.cpp | net about zero | one htpd serves both models (2.54) |

**Speaker notes:** The LADE lesson shaped our process: the first test used one prompt repeated and looked like a clean
14% win; corruption only showed on different prompts (HANDBOOK 2.14). Since then every decode change is gated on a
multi-prompt set. GPU: `proofs/2026-10-28_master/gpu_bench_out/out.md` (pp1 7.35, pp3 8.44, tg 8.35 t/s).

---

## 20. Model results: domain agents

| step | result | set |
|---|---|---|
| v1 fine-tune vs base vs rules (host) | pattern **94.0%** vs 20.0% vs 68.0% | 150 held-out windows |
| first NPU export (w4a16) | 54.3% | 46 windows, board |
| GPTQ int4 + Genie double-BOS fix | **82.6%**; 85.2% on 54 windows | board |
| htpd final (llama.cpp Hexagon, Q4_0) | **90.7%** pattern, 100% JSON / policy | 54 windows, board |
| v2 (35,946 rows, 6 roles) | 40 min: **73.8%** vs 42%; false alarms **18%** vs 31%; 3 h 82.5% vs 88% (miss) | test months, board |
| v2 + post-rules | status 81.5 -> **86.4%** (1,148 rows); real-world 60.4 -> **85.2%** (318) | host |

- The quantisation gap was mostly a **prompt mismatch** (Genie adds its own BOS token): 67% -> 83% from that fix alone;
  GPTQ recovered most of the int4 rounding loss (74% -> 89% on host).

**Speaker notes:** HANDBOOK 2.7 (table "The quantisation gap"; `training/results/agents_20261006_2101/eval.md`), 2.37
(`proofs/2026-10-16_htpd_accuracy`, n = 54 so a few points are noise), 2.42 (v2 deploy decision, p = 0.09 on the 3 h miss),
2.50 (`proofs/2026-10-24_trackB/RESULTS.md`). Activation recalibration on Kaggle did not beat the published ranges once
BOS was fixed.

---

## 21. Model results: the reasoner

| model | severity | label | other |
|---|---|---|---|
| rsn_v1 (4B), 150 held-out (host) | **91.9%** | 87.8% | valid JSON 98.7%; 0% ungrounded numbers, unit errors, actuation, injections followed |
| rsn_v1 vs rsn_v2, same 106 RWH ids | **94.7%** vs 87.6% | 88.4% vs 85.6% | check recall 0.90 vs 0.81 -> rsn_v2 rejected |
| rsn_v3 2B r1, board RWH q10-39 | 29/30 (4B 27/30) | 29/30 (4B 25/30) | but a false critical and a self-contradicting pH report in app stories -> rolled back |
| rsn_v3 2B r2 gate vs rsn_v1 | 0.793 vs **0.919** | 0.907 vs 0.874 | chat 0.737 vs 0.477 -> chat only, eval day |

- Consistency on the board: same prompt 5 times, same severity 97%; 100% with the severity guard.
- Real-world stories: label right 6/6 (rsn_v1).

**Speaker notes:** `proofs/2026-10-25_reasoner_final` (`summary_v3.json`), HANDBOOK 2.59 (rsn_v2 rejection; on the board it also
invented a title location and misread 324 > 300 ppm), 2.71 and `proofs/2026-11-02_2b_board/VERDICT.md` (2B r1 on the board),
`proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md`. The 2B r1 table row is a 30-prompt board bench, not the 150-item gate.

---

## 22. Decision log (1/2): what we chose and why

| decision | why |
|---|---|
| Everything on the board's NPU, no cloud | privacy, offline, seconds; cloud cannot see the data (G01) |
| Fine-tune one 3B for all domain roles | pattern 20% -> 94%; two resident models reboot the board (2.7, 2.27) |
| Run on llama.cpp's Hexagon backend (our htpd), not Genie | Genie dropped batching; GPU 8.4 s/agent with no batch gain (2.37) |
| Alert after 8 abnormal readings, 4 h window | 4 h best window; young events misread; false alarms down (2.38, 2.39) |
| Ship v2 despite the 3 h miss | 40 min 42% -> 73.8%, false alarms 31% -> 18%; v1 kept as rollback (2.42) |
| v2 is the final domain retrain; later gains by blends + rules | top-ups hit the noise floor (3d, 3e, v2.1, T30 all rejected) (2.48, 2.54b) |
| Reasoner model chosen only after the P0 benchmark | Qwen3.5-4B best total score (+0.16 vs 2B) (P0 RESULTS.md) |

**Speaker notes:** Decision groups G01-G30 on the website (`Website/build/collect/decision_groups.py`), HANDBOOK sections in
brackets, owner decisions from the project memory ("v2 final", "Reasoner decisions": model after P0).

---

## 23. Decision log (2/2): what we chose and why

| decision | why |
|---|---|
| Accuracy first, then latency | rsn_v2 (10% faster) and T30 rejected on accuracy; every speed-up gated on unchanged answers |
| Screen candidates on the host GGUF first | host matches the board on 207/208 rows; board time only for winners (2.45) |
| Accept the 40-55 min gate; build the critical fast path | early AI is unreliable; a critical breach cannot wait (2.55) |
| Human approval for every action, read-only chat tools | operators decide; no actuation path exists (2.44) |
| Fix forward with automatic rollback | every deploy: snapshot, chaos 2 + fastcheck through the app, roll back on failure (deploy8-28) |
| Router before the model for chat | 0.2 s median and exact numbers; the model handles the rest (2.68-2.70) |
| Eval-day split: 2B chat, 4B reports on NPU | each model where it scores best; 4B trained further as the single model |
| 2B chat on the CPU, not the GPU | measured 25 vs 9-10 tok/s, identical text: hybrid Qwen3.5 recurrent ops run on the CPU anyway |
| Private data, public evidence | aggregates on an encrypted site; raw data and room-level occupancy stay local (2.36) |

**Speaker notes:** Deploy scripts: `proofs/2026-10-29_latency/deploy*.sh`, `proofs/2026-11-04_split/deploy28_split.sh`
("chat problems = fix forward", owner). Split rationale: `GATE.md` g2b_r2. Approval design: `proofs/2026-10-23_reasoner_research/DECISIONS.md`.

---

## 24. How we know the numbers are real

- **Paired tests on the same rows** (gate2, sign tests, CIs); a candidate ships only if no slice that matters gets worse.
  We also fixed our own test: a permutation test showed the old one rejected two identical models 71-82% of the time.
- **Through the real app on the board**: chaos scenarios, a critical-breach fastcheck after every deploy, 40-question chat
  sweeps graded against the incident store, fault injection (kill the daemon, the backend, torn writes).
- **Host proxy**: same Q4_0 file on the laptop agrees with the board on 207/208 rows; big sets run there.
- **Run-to-run floor**: NPU float sums are not bit-reproducible; "identical" is judged against the board vs itself.
- Every result has a folder: raw data, scripts, status, verdict (`proofs/`).

**Speaker notes:** gate2 and the permutation finding: Website Journey step 8 (`proofs/2026-10-25_domain_plan`). Fault
injection: HANDBOOK 2.35. Host proxy: 2.45. Run-to-run: 2.37 (21-24 of 25 identical), 2.62/2.63 (base vs itself 2/6 text).

---

## 25. Why this is worth it

- **Fully on-device multi-agent LLM pipeline on a phone-class NPU**: a 3B multi-role agent model and a 4B reasoner on one
  Hexagon V75, plus a chat assistant, with our own batched NPU daemon.
- **Edge vs cloud**: no sensor data leaves the board (privacy); it keeps working without a network; a critical breach is an
  incident in seconds; no per-call API cost.
- **Evidence-cited and validated**: every claim points to a sensor evidence id; a validator, a severity guard and a
  deterministic fallback stand between the model and the operator; the reasoner checks the agents' claims.
- **Measured on real hardware, with proofs**: latency, accuracy, heat and failures, including what failed.
- Honest framing: we did not compare against a cloud LLM on the same data; the claim is feasibility and measured quality on the edge.

**Speaker notes:** The bandwidth facts (slide 17) are why few systems run two LLMs of this size on one phone NPU: each extra
token costs a full weight read. HeteroInfer/HeteroLLM (arXiv 2501.14794) reports that naive GPU + NPU parallelism on 8 Gen 3
can be slower, which matches our GPU numbers (HANDBOOK 2.36 notes, `proofs/2026-10-28_master/GPU_RESEARCH.md`).

---

## 26. Honest limits

- **Sensor time**: non-critical events reach the AI after 40-55 min; power, tank level and flow have no fast path.
- **Heat**: heavy NPU work reaches 84-97 C on the hottest zone; back-to-back chaos trips the thermal guard. Needs a heatsink.
- **The NPU is not bit-for-bit repeatable**: near-ties can flip wording; severity agrees 97% across repeats (100% with the guard).
- **Model weaknesses**: recurring small spikes, pump cycling, erratic shapes at 3 h; hourly sensors (TDS) stay rules-only.
- **Chat**: blind questions still expose gaps (blind set 20/40 before the question-type layer); the eval-day split uses two models.
- **Data**: one campus; test months and ~15% of sensors held out; the fog/cloud store is designed but not built.

**Speaker notes:** HANDBOOK 2.62 (heat ranges), 2.37 and 2.53 (repeatability), 2.39/2.42 (weak shapes), 2.46 (TDS), 2.70
(blind 20/40), 2.40 (holdouts), 2.44 (fog = Supabase plan; chat tool results say "fog offline").

---

## 27. What comes next

- **One general model**: rsn_v3 4B (Kaggle) must beat rsn_v1 on reports and the 2B on chat; then the split goes away.
- **Earlier AI**: young-window training; the early provisional AI is built and off until 2-4 readings are proven.
- **Reasoner swap**: multithreaded repack is done (3.67 -> 2.80 s); next, keep both models' weights cheaper to reload.
- **Chat**: a fresh blind set after every fix; streaming answers; chat about the open incident.
- **Fog layer**: derived data to a free Supabase project with the board as the only writer.

**Speaker notes:** rsn_v3 plan: `proofs/2026-10-29_rsn_v3/PLAN_V2.md`, `kaggle/KAGGLE.md`. Early AI: HANDBOOK 2.55
(`earlyai.go`, default off). Repack: 2.62 and repack VERDICT. Fog: 2.44.

---

## 27b. From prototype to production

- **Security (documented, not built):** adbd on 127.0.0.1:5555 has no auth; the port-8000 API serves reads, including
  per-room occupancy, in plaintext on the LAN. Production: no adb, auth + TLS, per-device keys, signed updates.
- **Being built now:** MQTT sensor bridge, time sync, off-board alerts + escalation, heartbeat, fog uploader,
  early provisional AI + warm-up, OTA with rollback.
- **Hardware:** DC supply + UPS, heatsink + enclosure, 40 C soak test.
- **Rollout:** shadow mode 2-4 weeks (rules page people, AI is logged), canary board, one-floor pilot.

**Speaker notes:** Full table in `PRODUCTION_GAP.md` (today / need / why skipped / effort / priority), HANDBOOK 2.75,
from `proofs/2026-11-09_roadmap/ROADMAP.md` section 4. Hardening was skipped because the prototype is a dev kit on a lab
bench with replayed data; the two blockers before anyone relies on it are the open adb/API and no off-board alerts.

---

## 28. References

Explicitly referenced in the repo (file in brackets):
- Frantar et al., *GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers*, ICLR 2023 [QUANT_RESEARCH.md; used for the agents].
- Hu et al., *LoRA*, ICLR 2022 (arXiv 2021); Dettmers et al., *QLoRA*, NeurIPS 2023 [REASONER_DESIGN.md; all our fine-tunes].
- Leviathan, Kalman, Matias, *Fast Inference from Transformers via Speculative Decoding*, ICML 2023 [reasoner_fast/RESEARCH.md].
- Saxena, *Prompt Lookup Decoding* (GitHub) [RESEARCH.md]; SuffixDecoding-style corpus drafts [HANDBOOK 2.63].
- Yao et al., *ReAct*, ICLR 2023; Schick et al., *Toolformer*, NeurIPS 2023; Kim et al., *LLMCompiler*, ICML 2024 [REASONER_DESIGN.md].
- Lewis et al., *Retrieval-Augmented Generation*, NeurIPS 2020 [REASONER_DESIGN.md, FOG_OPTIONS.md].
- Rafailov et al., *Direct Preference Optimization*, NeurIPS 2023 [PLAN_V2.md, 3e top-up]; Zelikman et al., *STaR*, NeurIPS 2022 [rsn_v3 PLAN.md].
- Wortsman et al., *Robust fine-tuning of zero-shot models* (WiSE-FT), CVPR 2022, and *Model soups*, ICML 2022; Ilharco et al., *Editing Models with Task Arithmetic*, ICLR 2023 [domain_research/PLAN.md, v2t3f/RESEARCH.md; mixA50/B50 blends].
- Greshake et al., *Not what you've signed up for* (indirect prompt injection), 2023; Liu et al., *Lost in the Middle*, TACL 2024 [REASONER_DESIGN.md].
- Qwen Team, *Qwen3 Technical Report*, 2025; Dubey et al., *The Llama 3 Herd of Models*, 2024 [REASONER_DESIGN.md].
- Amershi et al., *Guidelines for Human-AI Interaction*, CHI 2019 [UX_RESEARCH.md]; HeteroInfer, arXiv 2501.14794 [GPU_RESEARCH.md].

Well-known and directly relevant, not cited in the repo: Fu et al., *Break the Sequential Dependency of LLM Inference
Using Lookahead Decoding*, ICML 2024 (the method behind the LADE test in HANDBOOK 2.14).

**Speaker notes:** Full lists with links: `Code/smart-city-edge-agent/training/export/QUANT_RESEARCH.md` (GPTQ, AWQ, SmoothQuant,
QuaRot, SpinQuant, QA-LoRA, LoftQ and more), `proofs/2026-10-23_reasoner_research/REASONER_DESIGN.md`,
`proofs/2026-10-25_domain_research/PLAN.md` (TIES, DARE, Model Stock, ORPO), `proofs/2026-10-27_reasoner_fast/RESEARCH.md`.
