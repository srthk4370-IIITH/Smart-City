# How the app works right now (2026-10-29, final evaluation day)

This document teaches a teammate exactly what runs on the board today, why, and how well it works. It also
covers how to change it safely and how to answer the evaluators. HANDBOOK.md holds the full history (the
morning's work is section 2.59). The one-page fact sheet with every number and its source is
`proofs/2026-10-28_master/FACTS_2026-10-29.md`. `ppt.md` is the deck, and `teachWeb.md` covers the website.

---

## 0. The headline numbers (learn these by heart)

| what | number | where it was measured |
|---|---|---|
| critical breach → incident open | **5.6 s** | board, through the app (fastcheck, this morning) |
| incident → first report on screen | **0 s**, the same second (retrieval or rules) | board, 4/4 incidents (RAG_STATUS.md) |
| one domain agent on the NPU | **5.9 s** (first token 0.7 s) | board |
| 12 agents of one incident, all together | **20.7 s** (Genie: 46-48 s) | board, HANDBOOK 2.37 |
| reasoner report | **21.6 s** (27.8 s before OPPOLL + split decoding) | board, x2x3_ab.result |
| full AI report from the incident start | **42-54 s** | board, this morning |
| reasoner severity right, 150 held-out incidents | **91.9%** (label 87.8%) | host, same model file |
| reasoner severity right, same 106 incidents as v2 | **94.7%** (v2: 87.6%) | host |
| made-up numbers, unit errors, actuation, injections followed | **0% / 0% / 0% / 0%** | host, 150 incidents |
| report labels after today's contract repairs | **83.2% → 87.6%**, 0 new errors | 386 board answers |
| domain agents B50 vs previous live model | severity-weighted **+61**, safety **16/16** | gate2 |
| severity stable over 5 runs | **97%**, **100%** with the guard | board |
| chat questions answered (Campus Assistant, live today) | **100%** (exact numbers 90%, 0% made up) | host, 100 questions |
| everything on one board | **0** cloud calls, works offline | — |

---

## 1. The whole thing in one paragraph

Sensors send a reading every 5 minutes. The Go backend (`edge-agent`) keeps statistics and rules for every
sensor. If a reading is far past its critical limit twice, an incident opens at once (**fast path**).
Otherwise, when a sensor stays abnormal for 8 readings, all abnormal sensors at that moment become one
incident. The operator immediately sees a **preliminary report**, either retrieved from similar past AI
reports or built from the rules, together with a **live checklist** they can start on. Every abnormal sensor
then gets a domain agent (**B50**, our fine-tuned Llama-3.2-3B blend), and all agents run in one batch on
the NPU inside **htpd**, our llama.cpp Hexagon daemon. Their answers pass post-rules and the policy gate.
htpd then swaps in the cross-domain reasoner **rsn_v1** (our fine-tuned Qwen3.5-4B). It writes the full
report with split decoding, and the report replaces the preliminary on the same incident, with the
checklist merged in. A person acknowledges the incident, ticks steps and closes it. At 1.5 h and 3 h of
sensor time the incident is re-checked.

---

## 2. What is installed on the board right now

- **App:** `com.iiith.smartcityedge`, APK 508697c4, with the backend **edge-agent 12a10c1d** (the chat-queue
  build). It was deployed at 11:15 and passed 2/2 chaos scenarios and the fastcheck (fast path 5.5 s, AI
  report 53.5 s; 42-54 s across the morning's deploys; `proofs/2026-10-28_master/improve6/STATUS.md`). It has two launcher icons: **Smart City Edge** (the
  dashboard) and **Campus Assistant** (chat, §9).
- **Profile** `/data/local/tmp/smart_city_edge/htpd_profile`:
  `bin=/data/local/tmp/llama.cpp/bin/htpd_v8x3`, `model=/data/local/tmp/gpu/ft_B50_q4_0.gguf`,
  `reasoner=v3`, `reasoner_engine=htpd`, `reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf`,
  `reasoner_split=3`, `post_rules=all`, `solo_rerun=runaway`,
  `env=HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_IDLE_MS=3000`.
  Early AI (`ai_early_k`) is off.
- **Retrieval library:** `/data/local/tmp/smart_city_edge/data/rag_seed.json` holds 254 reference reports.
- **Processes:**
  - The Android foreground service starts the backend through the board's own adbd (127.0.0.1:5555),
    because apps on this firmware can't open the NPU and the shell user can.
  - `edge-agent` serves the UI and API on port 8000 and supervises **htpd** on 127.0.0.1:8091.
  - htpd holds **one model at a time**: the agents (10 streams × 1,280 context) or the reasoner (3 streams).
- **Logs** in `/data/local/tmp/smart_city_edge/state/`:
  - `agent.log` is the backend log;
  - `htpd.log` records loads, swaps, split streams and pick statistics;
  - `incidents.jsonl` is the incident store.

---

## 3. What changed this morning

1. **Report contract repairs** (`reasoner_v3.go`, in `checkReportV3`). These are two rules the training
   data follows in every case, now enforced deterministically:
   - if the reasoner says "normal" and "needs more data", the label becomes `unknown`
     (151/151 gold answers do this);
   - a building/level in the title that is not in the input is replaced with one from the input
     (5,761/5,761 gold titles come from the input).
   
   Result: label accuracy on 386 past board answers goes **83.2% → 87.6%**, with no new errors.
2. **Preliminary checklist with smart merge** (`workflow.go`, `reason.go`, `app.js`):
   - the checklist is built from the preliminary report, and the operator can acknowledge, tick and add
     steps while the AI writes;
   - when the AI report arrives, ticked steps the AI repeats stay done and take the AI's reason, open
     steps it drops are withdrawn, and new AI steps are marked "New since you acknowledged";
   - close, dismiss and approve-all still wait for the AI report.
3. **Safety fix:** the rollback scripts could not stop `htpd_v8x3`, so a rollback would have left two NPU
   programs running. They now can.
4. **Campus Assistant (chat), a second app on the same backend** (§9).
5. **Decisions with data:**
   - rsn_v2 was rejected (§7);
   - the GPU was measured and ruled out as a latency path (§8);
   - the split shape "3r" was tested and gave no gain (§8).

---

## 4. From sensor reading to closed incident, step by step (code references)

1. **Reading in.** `/api/ingest` or a replay tick feeds the engine (`engine.go:449 Tick`), which calls
   `engine.go:525 detect` every step: window statistics, rule status and data-quality gates.
2. **Gates.**
   - Fast path: 2 fresh readings past the critical limit (`fastReadings = 2`, `engine.go:728`).
   - AI gate: 8 abnormal readings in a row (`persistReadings = 8`, `engine.go:720`).
   - `engine.go:780 batchEvents` holds a short batch so that sensors which turned abnormal together share
     one incident.
3. **Hand-off.** `main.go:59` connects the engine to `reason.go:263 HandleCandidates`. Fast candidates go to
   `fastpath.go:19 splitFast` → `fastpath.go:42 openFast`, which opens the incident with no NPU at all.
4. **Incident + preliminary.** `reason.go:612 Process` either adopts the fast-path incident
   (`fastpath.go:75 adoptFast`) or builds a new one. `retrieval.go:376 retrievalPreliminary` then builds
   the first report, and `reason.go:1190 preliminary` shows it and builds the checklist
   (`workflow.go:303 mergeSteps`, stage "preliminary").
5. **Domain agents.** `reason.go:661 analyse` sends every abnormal sensor in one htpd batch. Each answer is
   checked by `policy.go:196 checkAgentWin`, which runs `postrules.go:64 applyPostRules`. A runaway answer
   is re-run alone.
6. **Reasoner.** `reasoner_v3.go:1176 reasonV3Fallback` builds the prompt, swaps the reasoner into htpd,
   decodes the head once and the 3 field groups in parallel.
   - The gate: `reasoner_v3.go:417 checkReportV3` checks JSON, enums, ids, that numbers exist in the
     input, and no actuation, then applies the contract repairs.
   - `reasoner_v3.go:1273 severityGuard`: the AI may not say "normal" when the rules say
     warning/critical.
   - If anything fails, the deterministic report stays.
7. **Final.** `severity.go:89 finaliseSeverity` and `title.go:133 retitle` run, the checklist merges in
   (`mergeSteps`, stage "early"), and `retrieval.go:433 retConsistency` logs any disagreement with similar
   past incidents. The re-checks are then scheduled.
8. **Re-checks.** `refine.go:253 RefineTick` / `refine.go:334 runRefine` re-read every sensor at 1.5 h and
   3 h. The severity can rise or fall, or the incident resolves.
9. **Operator.**
   - `workflow.go:604 Ack` and `workflow.go:648 SetStep` work on the preliminary too
     (`workflow.go:574 decidableEarly`).
   - `workflow.go:720 Close` waits for the AI report.
   - Reminders run after 15 min for an unacknowledged critical incident, and auto-close after 24 h.

---

## 5. RAG: the two-stage report, in detail

- **Goal:** the operator never waits for the AI to know what is going on, and the first report is as good
  as past AI work allows.
- **How a match is found** (`retrieval.go`, no extra model, under 5 ms on the CPU):
  - a structured vector (role, metric, pattern, status, value ranges) weighted 0.7;
  - plus TF-IDF over the report text weighted 0.3;
  - only past incidents with the same role and metric qualify;
  - the top 3 matches are kept on the incident.
- **What the preliminary contains:**
  - the rules report built from the **live** values (numbers never come from an old report);
  - the best match's wording;
  - severity = max(rules, retrieved), so it never under-alerts;
  - the banner "Preliminary - based on N similar past incidents (best match X%, INC-…) - full AI report
    coming", or "Preliminary from the rules - full AI report coming".
- **Library:**
  - every validated AI report is added automatically;
  - plus 254 seeds written by rsn_v1 on the training split (320 written, 254 passed the gate), ranked 3%
    below live reports so that real history wins;
  - the seed file is `data/rag_seed.json`.
- **Status:**
  - deploy check 4/4: preliminary at 0 s, the AI report replaced it on the same incident;
  - retrieval matched 2/4 (the rules covered the rest);
  - the seed deploy passed;
  - the consistency check is live, e.g. "AI severity sensor_fault differs from 1 of 3 similar past
    incidents (seed:train-04155=critical)".
- **Why it matters for the UX:** the operator sees "what it probably is", "the AI is working" and "this
  may change" at once. Work done on the preliminary carries over when the AI answers.

---

## 6. The models

| model | role | board file | quality |
|---|---|---|---|
| **B50** | domain agents (Llama-3.2-3B; mixA50 + 0.5·(v2.1 − v2), Q4_0) | `/data/local/tmp/gpu/ft_B50_q4_0.gguf` (md5 bfdca67b…) | gate2 PASS: severity-weighted +61, E1 +4, safety 16/16, no worse slice |
| **rsn_v1** | reasoner (Qwen3.5-4B QLoRA, checkpoint 612, Q4_0) | `/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf` (md5 5ff2e1bc…) | RWH 150: severity 91.9%, label 87.8%, 0% ungrounded; dev 120: severity 93.3%; RW6 label 6/6; chat 100% answered |
| rsn_v2 | reasoner round 2, **not live** | `/data/local/tmp/gpu/rsn_v2_q4_0.gguf` | rejected (§7) |
| htpd_v8x3 | the NPU daemon | `/data/local/tmp/llama.cpp/bin/htpd_v8x3` (md5 ca0a0745) | same speed as v8x2 (21.6 vs 21.7 s), with safety guards |

htpd_v8x3 safety: bounded token picking, a 150 s wall-clock limit per report (after it, the deterministic
report stays), and a heartbeat that names the stalled side. The overnight watchdog saw **0 stalls**.

---

## 7. Why rsn_v2 is not live (the exact reason)

- On the board (10 prompts) v2 looked close: severity 10/10 vs 10/10, label 8 vs 9, and about 10% faster.
- On the bigger set, the same 106 held-out incidents scored on the laptop with the same model files:

  | | rsn_v1 | rsn_v2 |
  |---|---|---|
  | severity right | **94.7%** | 87.6% |
  | label right | **88.4%** | 85.6% |
  | claim checks found | **90%** | 81% |
  | claim checks precise | **83%** | 74% |
  | overall score | **0.938** | 0.913 |

- Reading its board answers also showed:
  - an invented location ("VN building, level 04" for a TH building, level 03 incident);
  - a wrong comparison ("324 ppm is below the 300 ppm floor");
  - 0.82 confidence on a case with too much missing data to judge.
- Its reasoning range is good in places (better cross-domain links on a stuck sensor, consistent
  checklists). But about 7 more wrong severities per 100 incidents is not one mistake. Accuracy comes
  first, so v1 stays.

---

## 8. Latency: where every second goes, and what is left

| step | time |
|---|---|
| fast path (2 readings) → incident | 5.6 s |
| incident → preliminary | 0 s |
| agents (1 sensor / 12 sensors) | 5.9 s / 20.7 s |
| reasoner swap-in | 4.6 s |
| reasoner prefill (1,317 cached prefix tokens + incident) | about 3 s |
| reasoner decode, 3 streams | about 18 s |
| full AI report | 42-47 s |

**Measured and ruled out:**
- **GPU:**
  - the reasoner on the Adreno 750 decodes at 7.35 t/s single (pp3 8.44, tg 8.35), against about
    20 t/s on the NPU split, so it is 2.5× slower;
  - the CPU heat at the first try was a one-time OpenCL kernel compile (now cached).
- **Two models resident on the NPU:** this rebooted the board before, so we keep one model and accept the
  4.6 s swap.
- **Split shapes:**
  - split 4: +1%;
  - split 6: does not fit the HTP session;
  - split 3r (fork after the label): 22.2 vs 22.2 s, because its first group became the longest stream.
- **Speculative decoding** (MTP, n-gram) for the reasoner: slower.

**Next lever:** let htpd write fully determined text (such as the sensor id after "S1 (") as forced tokens.

**The real-world wait:** non-critical events wait for 8 readings (40-55 min of sensor time), because young
windows are read poorly. This is accepted for the prototype. Critical events use the fast path, and every
incident shows a first report at once.

---

## 9. The Campus Assistant (conversational interface, built today)

- **What it is.** A second frontend on the same backend. It has its own launcher icon, "Campus Assistant"
  (`android/.../ChatActivity.java` opens `http://127.0.0.1:8000/chat/`). It is also reachable from any
  browser on the board at `/chat/`. The frontend lives in `device/web/chat/` (index.html, chat.js, chat.css,
  manifest).
- **Backend** (`backend/chat.go`):
  - `POST /api/chat {session, message}` asks a question and returns the whole session;
  - `GET /api/chat/sessions` lists the history; `GET` / `DELETE /api/chat/sessions/<id>` opens or removes one;
  - sessions are stored in `/data/local/tmp/smart_city_edge/state/chats.json` (newest 100).
- **How it answers:**
  - **rsn_v1** runs in its trained chat mode through htpd: the same reasoner slot, with no report schema.
  - The prompt is byte-identical to training:
    - `chat_header.txt` is the 9 chat tools, rendered exactly like the incident header (checked: the incident
      header reproduces byte for byte);
    - `chat_system.txt` is the trained system text, with the device time as its first line, rounded to the
      hour so htpd's prefix cache is reused.
  - The model calls tools (up to 5) and the Go executor answers them from the incident store and the live
    sensors, with the same result shapes as the training executor (`eval/p0/tools_impl.py`). The model then
    writes at most 3 short sentences that quote the tool numbers and cite `[INC-…]`.
  - The last 2 exchanges of the session are kept as context for follow-ups.
- **Tools (all read-only):** `count_incidents`, `find_incidents`, `get_incident`, `sensor_faults`,
  `get_sensor_history` (7 days of 5-min readings), `list_sensors`, `domain_health`, `get_action_history`, and
  `search_knowledge` (says "offline, no documents").
- **Safety:**
  - it can't switch, open or close anything, and it refuses and points to the operator controls;
  - numbers come only from tool results;
  - one chat at a time;
  - **alerts first, then chat**: a question asked while an incident is being analysed waits in a queue
    (`/api/chat/status` names what it waits for, and the UI shows "Queued: the AI is analysing INC-…"). It
    is answered automatically as soon as the NPU is free, after at most 5 minutes; the answer shows how long
    it waited.
- **Quality:**
  - chat test, 100 questions (host, same file): answered 100%, right first tool 100%, exact numbers 90%,
    ungrounded 0%;
  - laptop smoke test today: 5/5 correct, including refusing "close INC-0442" and declining "capital of
    France".
- **On the board:** checked through the real app after the 10:45 deploy (`improve3/STATUS.md`): 3 questions, **9-14 s** each
  (it includes the reasoner swap). "How many incidents were there today?" → `count_incidents` → 89; "Please close them all." →
  refused (read-only). Known weak spot: "Which of them are still open?" reused the plain count, because the trained
  tools have no open-only filter (domain_health has open counts per domain). Open it from the dashboard's
  **✦ Ask AI** button (top bar) or the Campus Assistant icon; ⌂ in the chat goes back to the dashboard.
- **UI:**
  - chat history in a sidebar (a drawer on the phone), grouped Today / Earlier;
  - suggested questions on an empty chat;
  - a typing indicator that shows what is happening ("Loading the reasoner on the NPU…") and the elapsed
    seconds;
  - "How I found this" expands each tool call and its raw result;
  - incident chips open the incident in the dashboard;
  - light and dark follow the system.
- **Next (chat v2):**
  - stream the answer;
  - open the chat from an incident with that incident as context;
  - run the 100-question set on the board;
  - maintenance-log tools.

---

## 10. Deploy, rollback and board tests (scripts in `proofs/2026-10-28_master/`)

| script | what it does |
|---|---|
| `improve.sh` / `deploy2.sh` | this morning's deploy-if-pass: build, snapshot, install, keep the seed file, chaos 2 + fastcheck, reinstall the snapshot on failure |
| `split3r.sh` | board A/B of a split shape, deploys only if faster with identical severity/label |
| `final.sh` / `final_rollback.sh` | the 10-28 final deploy and its known-good rollback |
| `rag_deploy.sh` / `rag_rollback.sh`, `seed_deploy.sh` | the retrieval APK, the seed library |
| `gpu_bench.sh` / `gpu_rerun.sh` | GPU-alone reasoner bench with memory and heat guards |
| `overnight_watch.sh` | status file every 10 min + the stalled-htpd watchdog |

- `proofs/2026-10-27_reasoner_fast/scripts/ab_board.sh` runs standalone htpd A/Bs on the board.
- `chaos2.py` runs scenarios through the real app. `fastcheck.py` checks the fast path, then the AI on the
  same incident.
- `proofs/detach.sh <name> <script>` runs any long job detached in WSL (it survives the Claude session).
  `BOARD_LOCK` makes board jobs take turns.

---

## 11. Safety rules (never break these)

1. One NPU client at a time. Stop the app and wait for exit + 30 s before any standalone htpd.
2. Every board request starts at ≤ 60 °C.
3. Never reboot the board.
4. Copy big files as `.part`, check the md5, then `mv`, with the app stopped. Never stage on /sdcard.
5. Stop htpd with `pidof` + `kill -TERM` (pkill -f through adb kills its own shell).
6. Accuracy first. A new model ships only if it passes gate2 or the board gate.
7. Snapshot before every deploy, and roll back on a failed app check.

---

## 12. FAQ for evaluators

- **Why not the cloud?** Occupancy data is private, answers are needed in seconds, and the monitor must
  work offline. Everything runs on the board.
- **Why the NPU and not the GPU?** We measured both. Agents on the GPU take 8.4 s each with no batching
  gain; the reasoner on the GPU is 2.5× slower. The NPU with htpd runs 12 agents in 20.7 s.
- **What is the RAG doing?** It gives the instant first report from similar past AI reports, with live
  numbers and a never-lower severity, and later checks the AI report against those past cases.
- **What if the AI is wrong?** The policy gate, post-rules, contract repairs, severity guard and the human
  approval step all apply. A rejected report falls back to the deterministic one.
- **Why did you not ship the newer reasoner?** It was 7 points worse on severity on 106 incidents. We ship
  on evidence.
- **Why 40-55 minutes in the real world?** The AI waits for 8 readings because young events are hard to
  read. Critical breaches open in 5.6 s, and every incident shows a first report at once.
- **Can I talk to it?** Yes: open Campus Assistant. It answers from the incident store with exact numbers,
  shows how it found them, and refuses to act (§9).
- **Is it deterministic?** Decoding is greedy, but the HTP numerics vary slightly. Severity agrees 97% over
  5 runs, and 100% with the guard.

---

## 13. Glossary

| term | meaning |
|---|---|
| NPU / HTP / HMX / HVX | the Hexagon AI processor; HMX is the matrix unit (batches), HVX the vector unit |
| htpd | our TCP daemon (llama.cpp Hexagon backend) that batches agents and hosts the reasoner |
| B50 | the live agents model, a weight-space blend of fine-tunes |
| rsn_v1 / rsn_v2 | reasoner round 1 (live) and round 2 (rejected) |
| gate2 | paired acceptance test against the live model, with CIs |
| RWH / RW6 / dev | reasoner held-out incidents (150) / real-world stories (6) / dev set (120) |
| split decoding | decode the report head once, then the field groups as parallel streams |
| OPPOLL | the host polls for HTP completions instead of sleeping (−7%, lossless) |
| fast path | an incident opened after 2 readings past the critical limit, before the AI |
| preliminary / two-stage report | the instant first report, replaced by the AI report on the same incident |
| contract repairs | deterministic fixes for rules the training data always follows (label, title location) |
| severity guard | the AI may not say "normal" when the rules say warning or critical |
| host proxy | the same Q4_0 file on the laptop; it agrees with the board on 207/208 rows |
