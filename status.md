# Project status: Agentic Edge AI for Smart Cities (honest, 2026-11-20, 14:40 IST)

Written by Claude Opus 5 from the repo, proofs/ and the live board. "Verified" means read from the board or from a stored proof today. Anything not verified is marked as such.

## 1. What runs today (verified on the board)
| Part | State |
|---|---|
| Hardware | Qualcomm QIDK (SM8650, Hexagon V75 NPU), Android, 11.6 GB RAM, 45 GB /data (66% used) |
| AI server | `htpd_v9h` (custom llama.cpp, Hexagon backend): `--agents 10 --agent-ctx 1280 --synth-ctx 4096 --reason-streams 3 --reason-ctx 8192` |
| Domain agent | `agt3_s0450_q4_0.gguf`: Llama-3.2-3B, LoRA fine-tune agt_v3 plus two top-ups, Q4_0. Laptop host eval (Q4_0): val 0.813, hard 0.918. Tool calls on (max 2), JSON abort on |
| Reasoner | `rsn_v3_4b_p2_q4_0.gguf`: Qwen3.5-4B with edited weights, v3 fine-tune (step 400) plus p2 top-up (step 220). Profile `reasoner=v3`, prompt r3, split decoding 3 |
| App | APK phase1t (backend Go plus web UI plus Android shell). Live campus replay data over a USB relay to the laptop |
| Website | https://smart-city-esw.pages.dev: home page, signed QR report viewer (camera scan), fleet dashboard (Supabase sign-in) |
| Fog | Supabase cloud, reports only (incident reports, decisions, board health). The board posts directly over Wi-Fi, falls back to the laptop relay, and otherwise keeps rows in an on-disk queue. Raw readings never leave campus |

## 2. Pipeline (code as deployed)
1. **Rules gate.** The AI is called when 4 of the last 8 readings are abnormal (editable). Criticals take a fast path after 2 readings and get an early AI pass on the sensor's past readings.
2. **Orchestrator.** Groups related sensors across domains; event mode makes one incident per building when 5 or more alarms arrive within 10 min.
3. **Domain agents** on the NPU (up to 10 parallel streams), with tool calls and "more data" requests. CPU context agents (rules) cover the linked sensors.
4. **Reasoner** (only when 2 or more domains are involved; otherwise an `isolatedReport` with no LLM). Then retrieval of past incidents, a coverage check and retry, the severity guard (trend-only rule warnings can be downgraded by the AI), a sensor_fault guard (a fault needs a second piece of evidence), the policy gate and a rules fallback.
5. **Refinement** at 1.5 h and 3 h.
6. **Operator workflow:** I'm on it / dismiss (critical dismissals need a second confirm, and single-person dismissals stay out of AI memory until confirmed), undo, reopen, snooze. Alerts go by ntfy, re-sent at 15, 30 and 60 min, then by backup email.
7. **Chat** (on-board, using the same reasoner): lookup templates plus LLM for open questions, push-to-talk voice (whisper tiny.en on the CPU, about 2.7 s per question), Clear history.

## 3. In progress
- **Reasoner "big" top-up** on Kaggle (kernel `rsn-big-train` v2, running since 07:02 UTC).
  - Data: ~4k rows from a 16k pool (replay 37.5% plus holes, tool use, fog, chat, 4.5k new agent-output rows).
  - Ends about 16:30 UTC (22:00 IST). The gate then runs automatically on the laptop and scores go to the owner. **No automatic deploy.**
- **First attempt failed.** The launcher passed the trainer flags one character at a time, so the trainer exited after about 4 min and 8 h were lost. That is fixed, and the run is confirmed in the RUNNING state.

## 4. Known weaknesses (honest)
- **Reasoner quality.** Hole inspection on a laptop sample (p2):
  - severity is wrong on 20–26% of incident rows, and on 5 of 10 of the new families;
  - it makes almost no second-evidence tool calls inside reports;
  - chat tool sequence is correct 89% of the time, but holes remain: wrong tool for unknown rooms, ignored format requests, invented ids in a few probes.
- **p2 may not have trained on its own new data.** The p2 trainer log and data hashes show it re-trained on the earlier stage-2 pack, not on the p2 families (found while building the dataset zip). This would explain why p2 barely moved behaviour (its gate result was FAIL; deployed by owner decision with the sensor_fault guard).
- **Chat on the board** was 3/10 correct before the router fixes. The router fixes (11 items) are deployed but not re-scored on the board. The LLM path for open questions has only been tested with a fake model.
- **Evaluation evidence is thin.**
  - No frozen, hashed end-to-end test set run on the board.
  - The planned 600-incident Mode 1/2/3 grid (HANDBOOK, ~line 1263) was **never run**.
  - Mode 2 was only ever run on 1–2-domain incidents (October stress, 10 paired scenarios, policy gate only).
  - Accuracy numbers come from laptop host evals and gate sets, and are partly synthetic or self-distilled.
- **Latency.** The PRD target was under 15 s end-to-end. The October measurement was 42–47 s for a full multi-domain report, and that is **not recorded anywhere as a missed target**. Sensor time (20–40 min for 4 of 8 readings) dominates in practice.
- **Host vs device gap.** The memory notes record 94% on the host vs 67% on the device for an earlier quantisation. Not re-measured for the current models.
- **Reproducibility of October numbers.**
  - The October GGUFs (ft_B50, rsn_v1, qwen35_reasoner) were **deleted** from the board and the laptop to free space (owner-approved).
  - Their adapters may survive on Kaggle or in run folders. Not verified.
- **Board stability.**
  - One unexplained software reboot (2026-11-19); the cause can't be read without root. Boots are now recorded and counted.
  - Thermal peaks of 95–96 °C in October chaos runs.
- **Laptop relay.** MQTT has been down since a WSL restart. Campus data, Supabase and adb all go through the USB relay to the laptop, so the board isn't standalone on a network yet.
- **Not done:** a styled page for setting a new password, warming-up text on Home, the reasoner and chat fog-up answers (fog-down only so far), the Mode 2/3 settling experiment (planned after the gate), and hashed frozen test sets.

## 5. Data
- **Training data of the two deployed models:** `Desktop/SmartCity_Training_Datasets_2026-11-20.zip`, 111 MB.
  - 163,567 rows: 13,037 real, 140,690 synthetic, 604 mixed, 9,236 unclassified.
  - The zip contains real campus-derived rows, so it is private.
- **Real campus data:** replayed from the campus API (synthetic 2026 replay of recorded data).
  - 20,538 threshold breaches in the cleaned data.
  - Archived board incidents (2026-11-17, 433 real, not injected): one flagged sensor in 85% of cases, 2–4 in 5%, 6 or more in 11%. The 6+ incidents mostly come from replay start-up and batching bursts.

## 6. Decisions log
- `proofs/POLISH.md`: all owner decisions.
- `proofs/POLISH_PLAN.md`: the polish plan.
- `proofs/AGENT_REGISTRY.md`: every change.
- `proofs/2026-11-19_prod_audit/`: audits and the hands-on checks.
- `proofs/2026-11-20_rsn_holes/HOLES.md`: reasoner holes.
- `proofs/2026-11-20_reviewer_modes/ANSWER.md`: Mode 2/3 answers.

## 7. Next (owner order)
1. Big-reasoner gate scores, then an owner decision on deploying.
2. The Mode 2/3 settling experiment (ANSWER.md section D).
3. Remaining polish items.
4. Push the decided code to GitHub main.
