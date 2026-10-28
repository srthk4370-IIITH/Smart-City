# How the system works today (2026-10-29)

This document teaches a teammate the current state of the project: what runs, where it lives, how to
change it safely, and how to answer the evaluators. HANDBOOK.md holds the full history; this file holds
the current picture. Text inside `<<filled from …>>` is filled in by
`proofs/2026-10-28_master/finalize_docs.sh` once the overnight job writes that file.

## 1. The whole thing in one paragraph

Sensors send a reading every 5 minutes. The Go backend (`edge-agent`) keeps statistics and rules for every
sensor. When a sensor stays abnormal for 8 readings, all abnormal sensors at that moment become one incident.
Every abnormal sensor gets a domain agent, which is the fine-tuned Llama-3.2-3B blend **B50**. All agents
of an incident run in one batch on the NPU inside **htpd**, our llama.cpp Hexagon daemon. Their answers pass
post-rules and the policy gate. htpd then swaps in the cross-domain reasoner **rsn_v1** (Qwen3.5-4B QLoRA),
which writes the operator report with split decoding. The operator sees a preliminary report first
(retrieved from past reports, or built from the rules), and the AI report replaces it on the same incident.
At 1.5 h and 3 h of sensor time the incident is re-checked. A critical breach (2 readings past the critical
limit) opens the incident at once, before the AI runs.

## 2. Repository layout

| path | what it is for |
|---|---|
| `HANDBOOK.md` | the full journey: every measurement and decision (2.36-2.58 are the recent work) |
| `PRD.md` | the original requirements and architecture |
| `ppt.md`, `teach.md` | the evaluation deck content and this document |
| `Code/smart-city-edge-agent/app/backend/` | the Go backend: engine, agents, reasoner, workflow, HTTP API |
| `Code/smart-city-edge-agent/app/htpd/` | htpd.cpp (the batched NPU daemon), patches for llama.cpp, build scripts |
| `Code/smart-city-edge-agent/app/android/` | the Android app (EdgeService, AdbLocal, MainActivity) and `build_apk.sh` |
| `Code/smart-city-edge-agent/app/device/web/` | the dashboard UI (app.js, service worker) |
| `Code/smart-city-edge-agent/app/tools/` | app test harnesses (stress_app.py, check_*.py, ladders) |
| `Code/smart-city-edge-agent/training/` | v1 training; `v2/` (domain agents v2, top-ups); `window_study/`; `export/` |
| `Code/models_stage/` | staged GGUFs ready to push to the board (with .md5 sidecars) |
| `Code/platform-tools/adb.exe` | adb used by every script |
| `proofs/` | evidence: one folder per run, `<date>_<topic>/`; `AGENT_REGISTRY.md`; `detach.sh` |
| `Website/` | the evaluation website (owned by another agent; do not edit) |
| `Presentation/`, `Demos/`, `Resources/` | course hand-in folders |

## 3. How the app runs on the board

- **Processes.**
  - The Android app `com.iiith.smartcityedge` runs `EdgeService`, a foreground service that starts on boot.
  - Apps on this firmware cannot open the NPU, but the adb shell user can. So the service connects to the
    board's own adbd at **127.0.0.1:5555** (`AdbLocal.java`). It copies the backend out of the APK into
    `/data/local/tmp/smart_city_edge/` and starts it as the shell user.
  - `edge-agent` (Go) serves the UI and API on **port 8000** (`main.go:21`).
  - It supervises **htpd** on **127.0.0.1:8091** (`htpdclient.go:312 superviseHtpd`). htpd holds one model
    at a time: the agents' model (10 streams × 1280 context) or the reasoner.
- **Profile file:** `/data/local/tmp/smart_city_edge/htpd_profile` has `key=value` lines, read at start
  (`agentversion.go:99`). Live values (`proofs/2026-10-28_master/final/htpd_profile.final`):
  `bin=/data/local/tmp/llama.cpp/bin/htpd_v8x2`, `model=/data/local/tmp/gpu/ft_B50_q4_0.gguf`,
  `reasoner=v3`, `reasoner_engine=htpd`, `reasoner_model=/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf`,
  `reasoner_split=3`, `post_rules=all`, `solo_rerun=runaway`,
  `env=HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1 GGML_HEXAGON_OPPOLL=1 HTPD_REASON_IDLE_MS=3000`.
  The early-AI keys `ai_early_k` and `ai_early_shapes` are empty (off).
- **Logs** in `/data/local/tmp/smart_city_edge/state/`:
  - `agent.log`: the backend log, including `severity-disagreement` lines;
  - `htpd.log`: model loads, `ready in`, `reasoner loaded`, `agents' model back`, split streams;
  - `incidents.jsonl`: the incident store (last 1,000 plus an archive).

## 4. From sensor event to incident, step by step

Line numbers are for the current working tree.

1. **Reading in.** `/api/ingest` or a replay tick feeds the engine. `main.go:86` calls `eng.Tick()`, and
   `engine.go:449 Tick` runs `detect` on every step.
2. **Detection.** `engine.go:525 detect` updates the window statistics and the rule status. It applies the
   data-quality gates (`dataquality.go`) and counts the abnormal readings in a row.
   - `engine.go:685`: 2 fresh readings past the critical limit (`valueCritical`, `engine.go:700`) mark the
     sensor for the fast path (`fastReadings = 2`).
   - `engine.go:689`: the early-AI hook, off by default.
   - `engine.go:720`: `persistReadings = 8`, the AI gate.
3. **Batching.** `engine.go:780 batchEvents` holds the batch for at least 3 and at most 10 more readings,
   so sensors that turned abnormal together share one incident.
4. **Hand-off.** `main.go:59` sets `eng.onEvent = rsn.HandleCandidates` (`reason.go:263`).
   `fastpath.go:19 splitFast` sends fast candidates to `openFast` (`fastpath.go:42`), which opens the
   incident with a rules or retrieval preliminary and no NPU.
5. **Incident.** `reason.go:612 Process` either adopts the fast-path incident (`fastpath.go:75 adoptFast`)
   or builds a new one. It persists the incident (`store.go:89`) and shows the retrieval preliminary
   (`reason.go:624`, `retrieval.go:376 retrievalPreliminary`).
6. **Domain agents.** `reason.go:661 analyse` sends every abnormal sensor's prompt in one htpd batch
   (`htpdclient.go:266 prefetchViaHtpd`). Each answer is checked at `reason.go:744`
   (`policy.go:196 checkAgentWin`, which runs `postrules.go:64 applyPostRules`). A runaway answer is re-run
   alone.
7. **Reasoner.** `reason.go:878-879` shows the deterministic preliminary and then calls
   `reasoner_v3.go:1162 reasonV3Fallback`. That function builds the prompt, swaps the reasoner into htpd,
   decodes the head once, and then decodes 3 field groups in parallel. The answer goes through
   `checkReportV3` (`reasoner_v3.go:416`, which trims over-long lists) and `severityGuard`
   (`reasoner_v3.go:1259`). If the engine fails or the gate rejects the report, the deterministic report is
   kept.
8. **Final severity and title.** `severity.go:89 finaliseSeverity` sets the final severity and calls
   `retitle` (`title.go:133`). `reason.go:645` then schedules the re-checks (`refine.go:221`).
9. **Re-checks.** `refine.go:253 RefineTick` and `refine.go:334 runRefine` re-read every sensor of the
   incident at 1.5 h and 3 h, using the window from `features_v2.go WindowN`. They can raise or lower the
   severity, or mark the incident resolved.
10. **Operator.** `workflow.go` runs the approval steps: acknowledge (`:576`), checklist steps (`:620`) and
    close (`:692`). `WorkflowTick` handles the reminders and the 24 h auto-close.

## 5. The models

| model | role | laptop | board | md5 |
|---|---|---|---|---|
| B50 | domain agents (mixA50 + 0.5·(v2.1 − v2), Q4_0) | `Code/models_stage/ft_B50_q4_0.gguf` | `/data/local/tmp/gpu/ft_B50_q4_0.gguf` | bfdca67bd2cc582577c48e6728d9fc76 |
| rsn_v1 | reasoner (Qwen3.5-4B QLoRA, checkpoint 612, Q4_0) | `Code/models_stage/rsn_v1_q4_0.gguf` | `/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf` | 5ff2e1bc7f6ae0ae0eb9d76f937f3632 |
| rsn_v2 | reasoner round 2 (Kaggle), not live | `Code/models_stage/rsn_v2_q4_0.gguf` | `/data/local/tmp/gpu/rsn_v2_q4_0.gguf` | b4562c8655cd652d1c15d080a20906fb |
| T30 | rejected agents candidate | `Code/models_stage/ft_T30_q4_0.gguf` | not pushed | a7ce589cd7d0463ae56b0a1a0ea3e9d4 |
| htpd_v8x2 | the daemon binary (llama.cpp 620d222 + patches) | `app/htpd/` | `/data/local/tmp/llama.cpp/bin/htpd_v8x2` | 22ec1278… (HANDBOOK 2.53) |

- Training runs live in WSL under `~/smartcity_runs/`: `agents_v2`, `agents_v2_topup3f` (where the B50
  build happens) and `reasoner_v1`.
- B50 provenance: `proofs/2026-10-25_domain_plan/B50_STAGED.json`.
- rsn_v1 evaluation: `proofs/2026-10-25_reasoner_final/eval/results/summary_v3.json` (`ft612`).
- rsn_v2 retry status: DEPLOYED htpd_v8x3 + rsn_v1: app check PASS (chaos 3 3 3, fastcheck {"fast_incident": "INC-0433", "fast_s": 5.6, "ai_update_s": 47.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true})

## 6. Deploy and rollback (scripts in `proofs/2026-10-28_master/`)

| script | what it does |
|---|---|
| `final.sh` | snapshots the known-good state, then deploys the APK, models and profile, runs chaos2 (6 scenarios) and fastcheck, and rolls back on any failure. Writes FINAL_STATUS.md and HANDBOOK 2.56. |
| `final_rollback.sh` | puts back the known-good state from 2026-10-28 (`final/known_good`: profile, APK 9d066495, edge-agent 8e1ae828) |
| `rag_deploy.sh` / `rag_rollback.sh` | installs the retrieval-preliminary APK (4baf7f79 / edge-agent ebd08e13) or puts back the snapshot APK; models are unchanged |
| `split_post.sh` | split-4/6 A/B, then sets `reasoner_split` only if the new value passes |
| `deploy_model.sh`, `deploy_b50.sh` | push a GGUF (.part + md5 + mv) and set `model=` |
| `overnight_watch.sh` | rewrites OVERNIGHT_STATUS.md every 10 minutes and runs the stalled-htpd watchdog |

The live state: PASS: chaos 6/6 done+valid, fast path then AI on the same incident: {"fast_incident": "INC-0418", "fast_s": 6.3, "ai_update_s": 55.2, "final_model": "qwen3.5-4b (htpd)", "valid": true, "severity": "sensor_fault", "title": "KH building, level 03: Suspect CO2 readings", "pass": true}. Retrieval: PASS: 4/4 incidents had a preliminary within 2 s and the AI report on the same incident; fastcheck {"fast_incident": "INC-0427", "fast_s": 5.5, "ai_update_s": 47.5, "final_model": "deterministic (related domains verified steady)", "valid": true, "severity": "sensor_fault", "title": "CO2 step incr....

## 7. Board tests

- **`proofs/2026-10-27_reasoner_fast/scripts/ab_board.sh`** (runs on the board, detached). It stops the app,
  waits for exit + 30 s, and starts one standalone htpd per config with the app's own command line. Each
  config gets an agents request, the reason requests (`REQS="10 10 11 …"`, the first is a warm-up), and the
  agents request again. Telemetry goes to `ab/telemetry.log`. Score with `split_acc.py` / `ab_table.py`.
- **`chaos2.py`** (WSL, through the running app): `python3 -I chaos2.py chaos 6 210` runs 6 scenarios,
  210 s apart. Before each scenario it clears, resets and waits for the board to cool below 60 °C. It saves
  the incident JSON, screenshots and the htpd log lines, and stops with exit 9 if the agents' model did not
  come back.
- **`fastcheck.py`**: holds CO2 at 2000 ppm and expects the fast-path incident first, then the AI on the
  same incident.

## 8. Standalone jobs and guards

- **`proofs/detach.sh <name> <script>`** (in WSL): runs the script with setsid + nohup, so it survives the
  end of any Claude session. The log goes to `~/detached/<name>.log` and the pid to `~/detached/<name>.pid`.
- **`BOARD_LOCK`** (`proofs/2026-10-28_master/BOARD_LOCK`): holds the name of the job that owns the board.
  Jobs wait for it, touch it every 5 minutes while they hold it, and treat it as stale after 3 h.
- **`PAUSE_GPU`** (`proofs/2026-10-25_reasoner_final/PAUSE_GPU.cmd`): makes the laptop GPU jobs pause or
  exit so the owner gets the GPU back.
- **Guards** inside the scripts: laptop RAM below 1.5 GB → wait; board offline → wait; step markers
  (`final/.fN`) make every script resumable.

## 9. Safety rules (never break these)

1. One NPU client at a time. Stop the app and wait for exit + 30 s before any standalone htpd.
2. Every board request starts at ≤ 60 °C.
3. Never reboot the board.
4. Copy big files as `.part`, check the md5, then `mv`, with the app stopped. Never stage on /sdcard.
5. Stop htpd with `pidof` + `kill -TERM`. `pkill -f "[b]in/htpd"` sent through adb killed its own shell.
6. Accuracy first: never trade accuracy for latency. A new model ships only if it passes gate2 or the
   board gate.
7. Snapshot the known-good state before every deploy, and roll back on a failed app check.

## 10. How to read a proof folder

- `RESULTS.md` or `*_STATUS.md` comes first. It has the tables and the decision.
- `raw/` holds the board outputs, `bench/` the exact requests, `scripts/` the code that produced them, and
  `logs/` the run logs. `manifest.json` (where present) has the hashes and the commands.
- Every number in HANDBOOK and ppt.md names its folder. Check the n and the CI before quoting a number.
- The HTP is not bit-deterministic. "Identical" is judged against the run-to-run floor (RESULTS §0).

## 11. Glossary

| term | meaning |
|---|---|
| NPU / HTP / HMX / HVX | the Hexagon AI processor. HMX is its matrix unit, used for batches of 5 or more rows; HVX is its vector unit, used for 1-4 rows. |
| htpd | our TCP daemon (llama.cpp Hexagon backend) that batches agents and hosts the reasoner |
| B50 | the live agents model: mixA50 + 0.5·(v2.1 − v2) |
| mixA50 | v2 + 0.5·(c49 − v2), the previous live agents model |
| WiSE | weight-space ensembling: a linear blend of fine-tuned weights, which keeps old skills |
| rsn_v1 / rsn_v2 | reasoner round 1 (checkpoint 612, live) and round 2 (Kaggle, under test) |
| gate2 | paired acceptance test against the live model: dev3f net > 0, severity-weighted net ≥ 0, E1 net ≥ 0, safety not lower, no Holm-worse slice |
| dev3f | the 2,010-row domain-agent dev set used by gate2 |
| E1 | 184 realistic sensor stories (real test-month windows, teacher gold, safety stories) |
| RW6 / RWH | reasoner held-out sets: 6 real-world stories; 150 held-out realistic incidents |
| P0 | the host benchmark that chose Qwen3.5-4B (127 incidents, 65 chat questions, 15 reading items) |
| split decoding | decode the report head once, then the field groups as parallel streams |
| OPPOLL | `GGML_HEXAGON_OPPOLL=1`: the host polls for HTP completions instead of sleeping (−7%, lossless) |
| post-rules | deterministic corrections after the agent's answer (`postrules.go`) |
| policy gate | JSON, enum, evidence-id and no-actuation checks on every AI answer |
| fast path | an incident opened after 2 readings past the critical limit, before the AI |
| two-stage report | a preliminary report at once, then the AI report on the same incident |
| retrieval preliminary | a preliminary built from the most similar past AI reports, with live numbers |
| severity guard | the reasoner may not report "normal" when the rules say warning or critical |
| host proxy | the same Q4_0 GGUF on the laptop (llama.cpp); it agrees with the board on 207/208 rows |

## 12. FAQ for evaluators

- **Why not the cloud?** Occupancy data is private, the answer is needed in seconds, and the monitor must
  keep working offline. Everything runs on the board.
- **Why the NPU and not the GPU?** On the GPU we measured about 8.4 s per agent with no batching gain. The
  NPU with htpd runs a 12-agent incident in 20.7 s (HANDBOOK 2.37).
- **Why two models?** A separate reasoner cannot degrade the agents. Qwen3.5-4B won the P0 benchmark, and
  only one model is resident at a time (a swap takes about 3.6 s).
- **How do you know the accuracy is real?** Faults are injected into real calm windows. The tests use
  paired comparisons on the same rows, with CIs and sign tests (gate2), and decisions are confirmed on the
  board. Occupancy labels are circular with the rules, and we say so.
- **What if the AI is wrong?** Post-rules, the policy gate, the severity guard and the human approval step
  all apply. A rejected report falls back to the deterministic one.
- **Why does the AI take 40-55 minutes in the real world?** It waits for 8 readings at 5-minute intervals,
  because the agents read young events poorly. Critical breaches use the fast path instead (6.3 s on the
  board tonight).
- **Is it deterministic?** Decoding is greedy, but HTP prefill numerics differ run to run. Severity agrees
  97% of the time over 5 runs, and 100% with the guard.
- **What would make it faster?** Decode is at the bandwidth roof (about 17-20 tok/s per stream). The
  remaining levers are parallel streams, fewer bytes per token (pruned lm_head) or a GPU-resident
  reasoner. All are measured or planned in RESULTS.md and GPU_RESEARCH.md.
