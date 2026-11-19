# Roadmap after the evaluation: review from the ground up (2026-11-09)

Read-only review. No GPU, board or build was used. Every number below cites its source; "estimate" marks a derived
number, "unknown" marks something nobody has measured. Abbreviations: HB = `HANDBOOK.md` section, RW =
`proofs/2026-10-23_realworld/REALWORLD.md`, DEC = `proofs/2026-10-23_reasoner_research/DECISIONS.md`.

State on 2026-11-09:
- **Live on the board (deploy32, HB 2.73):** B50 3B agents (Llama-3.2-3B QLoRA, NPU) and the 4B rsn_v1 reasoner
  (Qwen3.5-4B, NPU) time-share one htpd. Chat runs on the 2B rsn_v3 r2 on the CPU (llama-server). The router answers
  most chat questions without a model.
- **Training:** the 4B rsn_v3 r3 run (step ~2000/4297, gen 0.992 at step 2000, mid-gate pending:
  `proofs/2026-11-06_4b_local/post/mid_gate.sh`) is meant to replace both rsn_v1 and the 2B.
- **Board:** back on Nov 15.

---

## 0. The short answer

| Question | Recommendation | Single next action |
|---|---|---|
| 1. Retrain the domain agents? | **No 3B retrain.** The failures seen on the board are reasoner failures, already targeted by r2/r3 data. Top-ups on the 3B are at the noise floor. The only agent retrain worth doing is **folding the agent role into the 4B (one model)**. Do it after r3, and only behind gate2. | Measure how often an agent error survives into the final report (CPU script over the stored incidents, about 2 h). |
| 2. Latency | The **sensor gate (40-55 min)** is about 99% of the time from event to warning. The compute levers that remain are worth seconds. Ranked: early provisional AI (built, off) > one resident model (−3.3-4 s/incident) > automatic warm-up (removes the 78 s cold outlier) > r3 pruned head + corpora rebuild > repack speed-up. | Run the gate study (k=4 young windows on the host GGUF) when the GPU is free, then turn on `ai_early_k` for the shapes that pass. |
| 3. Reduce the application | Remove the 2B CPU server once r3 passes. Remove the Genie code paths and stale binaries/models. Consolidate the four chat-router layers. If the one-model experiment passes, drop B50 (2.8 GB). | On Nov 15, deploy r3 to the NPU for chat + reports and remove `/data/local/tmp/chatgpu` (keep a copy on the laptop). |
| 4. Real deployment | The two blockers are (a) **adbd with no auth on 127.0.0.1:5555 plus an open LAN HTTP API** and (b) **no off-device alerting and no fog sync**. Real ingestion (MQTT), time sync and OTA with rollback come next. Run in shadow mode before anyone relies on it. | Write the security hardening and the MQTT-to-ingest bridge on the laptop before Nov 15 (no GPU needed). |

---

## 1. Domain agents (B50 on the NPU)

### 1.1 What is measured
| Measure | Value | Source |
|---|---|---|
| host400, mixA50 + rules (B50's parent) | pattern 87.7%, status 86.5%, JSON 100% | HB 2.51 |
| Status with post-rules, test 1,148 rows | 81.5 → 86.4% (57 wins / 1 loss) | HB 2.50 |
| Status with post-rules, real-world test 318 rows | 60.4 → 85.2% | HB 2.50 |
| Clean-window false alarms (seed 24) | 22% (v2) → 18% (mixA50) | HB 2.51 |
| E1 safety stories (mixA50) | rules 71%, safety 6/14 → with P1 rules 75%, 12/14 | domain_research/PLAN.md "Status" |
| Water status (mixA50) | 72.7% | HB 2.51 (v2.1 line) |
| unseen Sep-Oct sensors, pattern | 73.9% (mixA50); fell to 47.8 in v2.1 | PLAN.md §1 |
| Window stage (v2) | 40 min 73.8%, 3 h 82.5-85.8%, WindowN 3 h 86.3% | HB 2.42 |
| B50 vs mixA50 (gate2, dev 2,010) | net +1 (CI −37..+39), severity-weighted +61, E1 +4; **calm/routine 10 wins/27 losses (p 0.008)**; stage 3 h 1/8 (p 0.039); no Holm-worse slice | `domain_plan/diag/B50.json` |
| T30 vs B50 head to head | FAIL (dev +7 n.s., severity −13, E1 −4) | HB 2.54b |
| Through the app | chaos2 6/6 valid | HB 2.54 |

**Honest reading.** B50 is statistically tied with mixA50. Its gain is on severity-weighted rows. It is
nominally worse on calm/routine windows (more false alarms) and at 3 h. No absolute per-domain table exists
for B50 itself: every B50 number is relative to mixA50. That is a gap in the evidence.

### 1.2 Known failures, and which model owns each one
| Failure | Owner | Evidence | Status |
|---|---|---|---|
| Room-temp sensor fault reported as a false critical "outdoor heat" | **Reasoner (2B)**: the agent said sensor_fault 0.97 | `2026-11-02_2b_board/VERDICT.md` l.38 | 4B rsn_v1 got it right; contrastive pairs are in r2, hence in r3 (DIAG.md item 4) |
| pH 9.6 held 40 min described as a "single bad reading" | **Reasoner (2B)** | `2026-11-02_2b_r2/DIAG.md` l.42 | Same. `phdir.go` fixes the direction words (HB 2.72) |
| AC no-cooling read as stable/normal; daytime tank drain read as normal | **Agent** | PLAN.md §2 | Covered by deterministic P1 rules (`hvac_rule`, leak routine), proven on the board (HB 2.52) |
| Collapse to flatline/sensor_fault on compound/water/unseen rows | Agent training data | PLAN.md §1 | Avoided by keeping B50; not "fixed" |
| Not fixable by rules: erratic, unseen Sep-Oct sensors, water-cause pattern, holidays | Agent | HB 2.50 | Open |
| Hourly TDS is always insufficient_data | Pipeline | RW §2 open item 1 | Owner decision pending |

### 1.3 Does the agent need retraining?
**No, not the 3B.** Reasons:
- Six top-up attempts (topup2, topup3, 3d, 3e, v2.1, P3/P3b) either failed or tied. HB 2.48 states that top-ups
  "have reached the noise floor".
- The remaining agent errors are mostly caught by post-rules (+5 to +25 status points, HB 2.50), the severity guard
  (HB 2.53), the validator, and the reasoner, which sees all agents.
- The board failures from the last two weeks are reasoner failures.

**What is not known:** how often an agent error reaches the final report. This is the first thing to measure.
The store holds about 2,978 incidents (`DATASET.md`). Each one carries the agent outputs and the final report.
- Script (CPU only, about 2 h): re-label each agent window with the deterministic teacher (Go `rules.go`/`hvac_v2.go`
  parity exists), then count agent wrong → final right, agent wrong → final wrong, and agent right → final wrong.
- If "agent wrong → final wrong" is under about 2% of incidents, close the agent-accuracy topic for good.
- If not, the pairs it finds are exactly the "cleaner teacher labels on confused pairs" that HB 2.48 asks for.

### 1.4 One model (4B does the agents too) vs two models
| | Two models (today) | One 4B for agents + reasoner + chat |
|---|---|---|
| NPU swap per incident | 3.3-4.0 s agents→reasoner (HB 2.54); the next incident reloads the agents (2.5 s avoided only by early release, HB 2.53) | 0 |
| Chat then alert | +2.6 s agents reload (HB 2.61) | 0 |
| Cold first incident | 78 s seen (HB 2.73) | Lower (one load); not measured |
| Disk / RAM | B50 2.80 GB + 4B 2.61 GB (`Code/models_stage`) | 2.6 GB |
| One-client rule, reboot risk (HB 2.27, 2.43) | Two big loads per incident cycle | One resident model |
| Decode speed | 3B 2.8 GB and 4B 2.6 GB Q4_0 both sit on the bandwidth roof (HB 2.15/2.53); about equal per token | Same |
| Agent accuracy | B50, known | **Unknown. History says high regression risk** |
| Multi-stream agent batches | 13-14 streams work with Llama | 4B: split-6 × 4096 failed buffer mapping (HB 2.56b). Qwen3.5 hybrid KV is smaller, but **feasibility is unknown** |

**Recommendation.** Make it the next training job after r3 (call it r4). Do it only if:
- (a) a 1-2 h board feasibility test passes: the 4B base runs a 13-agent batch through htpd with the agent layout,
  timing only; and
- (b) the result passes gate2 vs B50 + P1 rules (`domain_plan/scripts/gate2.py`, the E1 stories, safety 16/16 as for
  B50) on the host GGUF proxy (host Q4_0 matches the board on 207/208 rows, HB 2.45).

Recipe:
- Multi-task: v2 agent rows (35,946, HB 2.40) + P3 rows (`train_p3.jsonl`), plus r3 replay so chat and reports do
  not forget.
- Use B50's own correct outputs as replay targets. This is the P3b lesson: raw v2 gold pulls the model back to v2,
  PLAN.md "P3 root cause".

Cost:
- Estimate: agent rows are short (1-2k tokens), so about 50 M tokens, roughly 20-30 h on the laptop at the r3
  shared-prefix speed (EQUIV.md). This is unverified.
- Gate: about 6 h.

Gain: −3.3-4 s per incident, −2.8 GB, one model to ship and roll back.

If it fails: keep two models, and use the repack speed-up (§2.3 L5) to reduce the swap instead.

---

## 2. Latency end to end

### 2.1 Where the time goes today
| Stage | Time | Source |
|---|---|---|
| Sensor gate, warning-level | 8 abnormal readings × 5 min = 40 min, plus a batch window of 1-3 readings → **40-55 min** | HB 2.55, 2.29 |
| Critical fast path | 2 readings (5-10 min of sensor time) + **5.6 s** compute; 2.6 s after a silence (r3 gap fix) | HB 2.67 |
| Retrieval preliminary | < 5 ms CPU | HB 2.57 |
| AI report after the gate (warm) | **21.5-33 s** (deploy20-32 fastchecks) | HB 2.65-2.73 |
| · agents | about 2.1 s per request with drafts (2,594 → 2,058 ms) | HB 2.65 |
| · swap agents→reasoner | 3.3-4.0 s (model load 3.67 s; 2.82 s with the pruned head) | HB 2.54, 2.62 |
| · reasoner prefill | 1.6-2.8 s (1,317-token prefix from the disk cache) | HB 2.54 |
| · reasoner decode | about 9 s (11.8 → 8.9 s lab with the live corpus; 4.6-5.1 s on repeats) | HB 2.64 |
| Cold first incident after 4 h idle | **78 s** (agents + reasoner 23.5 s; the rest waited before the AI started) | HB 2.73 |
| Chat, router | median 0.02-0.2 s for 143/160 questions | HB 2.73, 2.69 |
| Chat, model | 2B CPU 8.4-13.4 s mean; 4B NPU 9.2-12.4 s; 4B warm with keep-warm 5 s; a 1k-token tool result costs 7-13 s on the hot CPU (~100 t/s prefill) | HB 2.73, 2.61 |

So for a non-critical event, the sensor gate is about 2,400 s against about 25 s of compute. Compute work cannot
move the user-visible number much. Only gate work can.

### 2.2 The r3 prompt risk (must test on Nov 15)
- The r3 chat header is **4,579 tokens** (HB 2.74), and the mean training chat row is 5,420 tokens.
- htpd's reasoner context defaults to **4096** (`board/build_r3.sh`: `reason_ctx` unset = 4096). So r3 chat
  **cannot run at the default**. `reason_ctx` must go to about 8192.
- Risk: if the context is per stream, 3 split streams × 8192 = 24,576 tokens. That equals the 6 × 4096 that failed
  with `HTP0 buffer mapping failed` (HB 2.56b).
  - Test in this order: a single chat stream at 8192; split-3 reports at 4096 next to it; then split-3 at 8192.
  - If the shared setting fails, chat and reports need different contexts per request. That is an htpd change of
    about 0.5-1 day.
- Prefill: a cold 4.6k-token header is unmeasured on the NPU. The old chat hour prefix cost +5.7 s (HB 2.61).
  - Keep the header in the disk prefix cache (`HTPD_REASON_DISK_KEEP`), and pre-warm it after each start (as
    `chat_gpu.sh` does for the CPU server, HB 2.73).
  - Check that the live fog line and the "records since D" line come **after** the cached prefix, or that both fog
    states get cached. Otherwise every fog flip re-prefills about 4.6k tokens.

### 2.3 Levers, ranked by user-visible gain per cost
| # | Lever | Gain | Cost / risk | Evidence | Do it? |
|---|---|---|---|---|---|
| L1 | **Early provisional AI** (`earlyai.go`, `ai_early_k=4`, shape whitelist): built and tested, default OFF | Warning-level AI at about 20 min instead of 40-55 min (estimate: 4 readings) | Gate study on host GGUF, about 4-8 h GPU. The 40-min stage pattern is 73.8% (HB 2.42), so wrong provisional reports are likely for some shapes. The young-window top-up (690 rows) never ran (`young_window/yw_queue.log`: stopped by owner) | HB 2.55 | **Must**, gated per shape |
| L2 | Re-evaluate the gate over backfilled buckets | A backlog burst alerts at once instead of 40 more min | Go only, about 0.5 day | RW §2 open item 2 | Should |
| L3 | **One resident model** (§1.4) | −3.3-4 s per incident, −2.6 s chat→alert, a smaller cold start | r4 training + gate; high accuracy risk | HB 2.54, 2.61 | Should, after r3 |
| L4 | **Automatic warm-up** at boot and after more than N min of NPU idle (one synthetic incident or a 1-token reasoner + agents ping) | Removes the 78 s cold outlier | Go, about 0.5 day; heat and power cost of idle pings | HB 2.73 cold start | **Must** (cheap) |
| L5 | Repack speed-up: multithread ggml-hexagon's CPU weight repack, or cache the repacked layout on disk | Swap 3.67 s → about 1 s (estimate, unmeasured) | The repack is host-side CPU code (HB 2.62). The host lib may build with the NDK alone; whether the Hexagon SDK is needed depends on rebuilding the DSP skel (**unknown**, check first). Pointless if L3 lands | HB 2.62 | Could; only if two models stay |
| L6 | Rebuild the **pruned lm_head** keep-ids for r3 | −11% per report, load −0.85 s | About 2 h + a 6-prompt board A/B; near-tie text flips expected | HB 2.62 | Must with r3 |
| L7 | Rebuild the draft corpora (reason, agent, chat) from r3 outputs | Keeps the −25 to −61% decode gains; acceptance falls if the corpora come from rsn_v1 | Drafts are verified, so there is no accuracy risk; about 2 h | HB 2.63-2.66 | Must with r3 |
| L8 | Chat back on the NPU (r3) | Hot-CPU prefill of tool results (7-13 s per 1k tokens) disappears; NPU prefill is much faster (1.3k tokens in under 2.8 s including the cache) | Contends with alerts (alerts first is already implemented) | HB 2.73, 2.54 | Must with r3 |
| L9 | Output length / field trimming | Small | | HB 2.62: only 4/96 reports trimmed | No |

**Closed. Do not retry without new evidence:**
- Adreno GPU (2.5× slower, HB 2.59; 8-10 t/s, HB 2.73);
- LADE (HB 2.14);
- grammar decoding (HB 2.16);
- MTP and single-stream n-gram speculation (HB 2.53);
- continuous batching on QAIRT (HB 2.25);
- row padding v8x4 (HB 2.61);
- split-6 (buffer limit) and split 3r (HB 2.56b, 2.59);
- Hexagon SDK upstream and the 32x4 kernel (HB 2.54);
- role drafts (HB 2.47);
- GPU prefill offload (HB 2.73).

---

## 3. Reducing the application

### 3.1 What is there now
| Item | Size | Source |
|---|---|---|
| APK | 12.2 MB (split7) | `2026-11-04_split/apk7` |
| Go backend | 47 non-test files, 23,130 lines (+ 55 test files); edge-agent 15 MB RSS | file count; HB 2.35 |
| Models on the board | B50 2.80 GB, rsn_v1 2.61 GB, 2B 1.24 GB (+ the pruned-head GGUF) | `Code/models_stage` |
| CPU chat server | own libs in `/data/local/tmp/chatgpu`; kill guard below 700 MB free | HB 2.73 |
| Board storage | /data hit 100% once; 17 GB free after cleanup | HB 2.62 |

### 3.2 What to drop or simplify (ordered)
1. **The 2B CPU server** (`chat_gpu.go`, `split_on/off.sh`, chatgpu dir, 1.24 GB model).
   - Do this once r3 passes its gate and the §2.2 context test.
   - It removes the RAM-pressure guard and a second inference engine. The 2B left about 2 GB more RAM free only
     when it replaced the 4B (HB 2.71).
   - Keep `split_off`-style fallback logic only as "router-only chat" if the NPU is busy.
2. **Genie path:** `genie.go`, `genieapp.go`, `genieclient.go` and the Genie bundles.
   - htpd has been the live path since HB 2.37.
   - Verify first that no fallback still calls genied (grep in `main.go`/`server.go`).
   - Remove after a chaos2 + fastcheck run. This takes away a whole class of two-clients-on-the-NPU bugs (HB 2.35).
3. **Stale htpd binaries** (v7, v8x2, v8x4 "on the board, unused", v9 to v9e) and old prefix states.
   - Keep live, N-1 and known-good only. Same rule for models.
4. **Chat router layers:** `chat_router.go` (720), `_ops`, `_v24`, `_v25` (2,060), plus `chat_time`/`chat_guard`.
   - Merge into one intent → resolver → tool pipeline. Keep the behaviour; `chat_replay_test.go` and the 160-question
     sweeps are the safety net.
   - Do not remove the router. It answers about 89% of questions in about 0.2 s, and the model takes 5-14 s.
5. **If L3 passes:** drop B50, the agent htpd role, the swap and early-release logic, and `HTPD_AGENT_*` corpora.
6. **Unbounded files:** `incidents.archive.jsonl` grows forever.
   - Rotate it monthly once the fog sync exists. The fog then holds the history, and the device index keeps counts
     exact (DEC "Device store").
7. **Keep:** post-rules, the validator, retrieval, the fast path, workflow and data quality. They are cheap (< 5 ms)
   and they are where most of the measured accuracy comes from (HB 2.50, 2.52, 2.59).

Expected after 1-5: about 4 GB less on disk, one inference engine, about 1/3 of the chat code gone. RAM headroom
after this is **unknown**: the board's total RAM is not recorded anywhere in the proofs. Record MemTotal and
MemAvailable on Nov 15.

---

## 4. Real-world deployment, from the ground up

Severity: **B** = blocker before anyone relies on it, **H** = high, **M** = medium.

| Area | Today (evidence) | Gap | Recommendation | Cost |
|---|---|---|---|---|
| **Security: device** (B) | The app reaches NPU access through the board's own adbd on 127.0.0.1:5555 with no auth (`AdbLocal.java`, memory note). adbd in tcpip mode usually listens on all interfaces | Anyone on the Wi-Fi may get a shell | Short term: confirm the adbd bind address; firewall 5555 to loopback (iptables needs root), or keep the board off shared Wi-Fi. Production: a system service with a SELinux/fastrpc policy in the device image (a dev kit cannot ship like this), or a Qualcomm IoT SKU (QCS-class, Linux) where the NPU service is native | 1 day (short term); weeks (production image) |
| **Security: API** (B) | HTTP 0.0.0.0:8000. Writes off-device need `X-API-Token`; **reads are open on the LAN**; plaintext (`auth.go`, HB 2.35) | Incidents and per-room occupancy readable by anyone on the LAN; the token travels in clear | Token or mTLS for off-device reads too; TLS (self-signed + pinning for the gateway); bind loopback unless `ingest_lan=1` | 1-2 days |
| **Operators / audit** (H) | Name picker, no password; append-only event log (HB 2.49, DEC) | No accountability | PIN per operator (already planned, DEC); log the operator id in each event; export the audit log to the fog | 1 day |
| **Sensor ingestion** (B) | HTTP POST `/api/ingest`, measured feed with ts/quality, dedupe, late/out-of-order merge, backfill ≤ 5000 (RW §3) | No real gateway is connected | **MQTT subscriber** in Go to the same ingest path (QoS1; dedupe by ts already exists). Modbus TCP/RTU for energy meters and LoRaWAN (network server → MQTT) on a gateway, not on the board. Bring the feed metadata (unit, firmware, replaced) in from day 1 (RW open item 3) | 2-3 days for MQTT; gateway work depends on the site |
| **Cadence** (H) | Engine assumes 5-min buckets; hourly TDS is always insufficient_data (RW open item 1) | | Decide: rules-only for sparse sensors now; sparse-window training later | Decision |
| **Time sync** (H) | RTC resets to 2023 at boot; the app restores a saved offset (HB 2.34) | A long power-off leaves a wrong clock and wrong windows | NTP when online; otherwise take time from the gateway's message timestamps (UTC epoch, RW §3); flag an incident "clock uncertain" until synced | 0.5 day |
| **Data quality** (M) | Strong layer already (RW §0) | UI chip not rendered; no holiday calendar; no flood guard | Quality chip; holiday calendar file; EEMUA flood guard (≥ 10 alarms in 10 min) (RW §6) | 1-2 days |
| **Persistence** (M) | JSONL + fsync + rename; torn-line recovery; 1,000 kept + archive (HB 2.35) | DEC's SQLite outbox does not exist | Keep JSONL on the device. Add an outbox file (append-only, cursor) for sync; SQLite only if queries need it | 1 day |
| **Fog / cloud sync** (B for multi-site) | Contract `POST {fog_url}/v1/tool` + device fallback built and tested (HB 2.74); **the Supabase side and the uploader are not built** | No history off the board, no remote view | Build the uploader as DEC specifies: derived data only, idempotent upserts keyed (incident id, version) every 60 s, 50 MB offline queue, board is the only writer, dashboard approvals as requests the board applies (no conflicts by design), per-board Auth user + RLS. Free tier pauses after about 7 idle days (FOG_OPTIONS §2.2): the 60 s sync keeps it alive; plan Pro ($25/month) for production | 3-5 days |
| **Alert delivery** (B) | Android notification on the board itself; 15-min critical reminder (HB 2.49) | Nobody gets alerted unless they are looking at the board | Fog relay → push / email / WhatsApp Business / SMS, chosen per severity. Escalation ladder (on-call → supervisor at 15/30 min). Ack by link writes back as a request. Local fallback when the fog is down: a GSM modem or LAN siren for critical only. WhatsApp templates and SMS cost depend on the provider; not priced here | 3-5 days + provider setup |
| **Multi-site / multi-board** (M) | Single board; node ids per campus building | | `site_id`/`board_id` on every synced row; one Supabase project, RLS per board; models identical across boards | 1 day (schema) |
| **OTA app + models** (H) | `deployNN.sh` over adb: `.part` + md5 + mv, app stopped, chaos2 + fastcheck, automatic rollback to known_good (HB 2.67-2.73) | Needs a laptop and USB; no signing | Signed bundle (APK + profile + model sha256 + manifest) pulled from the fog. Install into an inactive slot, run a self-test (fastcheck-style synthetic incident), switch, auto-rollback on failure. Same .part/md5 rule; app stopped for big files (memory: QIDK safety) | 3-4 days |
| **Monitoring** (H) | EdgeService watchdog restarts the backend in 8 s; domain health; logs on the device (HB 2.35, 2.43) | Nobody notices a dead board | Heartbeat to the fog every 60 s (uptime, temp, queue depth, stage latencies, validator rejects, garbage reruns, silent sensors). Dead-man alert in the fog after 5 min of silence | 1-2 days |
| **Power** (H) | USB brownout reboots; DC adapter advised; BOOT_COMPLETED autostart present (HB 2.34, manifest) | | DC supply + small UPS; record boot reason each boot; after an unclean boot, re-run the incidents that were in flight (already marked "interrupted", HB 2.35) | Hardware |
| **Thermal** (H) | NPU peaks 93-97 °C; throttle trip 100 °C; pacing at ≥ 88 °C (HB 2.35, 2.62, 2.71) | Indian summer ambient was never tested | Heatsink + fan + ventilated enclosure; a soak test at 40 °C ambient; one incident at a time stays the design | Hardware + 1 day test |
| **Privacy** (M) | Per-room occupancy and CO2; operator ids not names in the cloud (DEC) | Occupancy can identify people in small rooms | Aggregate occupancy per zone/hour in the cloud; raw stays on the board (already DEC); a DPDP Act 2023 notice and retention policy (e.g. raw 90 days on the device; owner to set) | 0.5 day + policy |
| **Testing in production** (H) | Self-learning capture exists (HB 2.28); operator edits become training data only after owner review (DEC) | No shadow phase | **Shadow mode for 2-4 weeks:** rules + fast path alert people; AI reports are logged and shown but not paged. Compare against operator outcomes. Canary new models on one board first | Process |
| **Regulatory thresholds** (M) | `phdir.go` uses pH 6.5/8.5 | Check that `sensors.go` limits match the standards | IS 10500:2012 (pH 6.5-8.5; TDS acceptable 500, permissible 2000 mg/L); CPCB NAAQS (PM2.5 60 µg/m³ 24 h); indoor CO2 per ASHRAE 62.1/ISHRAE guidance. Store the standard name next to each limit | 0.5 day |
| **Docs / handover** (M) | HANDBOOK is a lab log of about 3,000 lines | No operator manual or runbook | Three short docs: operator guide, install/runbook (power, network, token, rollback), incident-response SOP | 2 days |

---

## 5. Dated plan

### Nov 9-14: laptop only (the GPU belongs to r3 training; RAM is tight; CPU tasks are light)
**Must**
1. r3 mid-gate verdict (`mid_gate.sh`, owner-started). Pass → resume to the end. Fail → read the failing suite
   before any data change.
2. Agent → final error-propagation script over the stored incidents (§1.3). CPU, about 2 h.
3. Security code:
   - token/mTLS for off-device reads;
   - bind loopback unless `ingest_lan=1`;
   - operator PIN;
   - `go test`.
4. **MQTT → ingest bridge** + tests with a replayed SCRC series (RW §1 data). Add the metadata fields.
5. **Automatic warm-up** (L4) + a heartbeat endpoint/payload (Go).
6. Prepare the r3 deploy kit:
   - pruned-head keep-ids (needs r3 token usage over the training outputs: CPU);
   - corpora rebuild script;
   - `reason_ctx` test script (§2.2);
   - known_good snapshot; rollback.

**Should**
7. Genie-path removal on a branch, ready to verify on the board.
8. Fog uploader + Supabase schema from `store_schema.sql` (test against `FogHandler`; no real project needed).

### Nov 15: the board returns
1. Health first:
   - boot reason, clock, `/data` free;
   - **MemTotal/MemAvailable**;
   - thermals idle;
   - redeploy deploy32 known-good if anything drifted;
   - chaos2 + fastcheck baseline.
2. If r3 has passed its gate:
   - `reason_ctx` test (§2.2);
   - r3 on the NPU for reports + chat;
   - pruned head + rebuilt corpora;
   - chaos2, fastcheck, the 4 chat sweeps (sweep1, held-out, blind, blind2);
   - the two contrastive stories (room-temp fault vs AC failure; pH single vs held);
   - one cold-start incident.
   - Gate: severity/label not worse than rsn_v1 on RWH q10-39 (rsn_v1 board baseline 27/25 of 30, HB 2.71); chat
     model answers better than the 2B (HB 2.72: 2B 0.737).
3. Then **remove the 2B server** (§3.2-1). Re-measure free RAM and the chat latency of long tool results.
4. Deploy the security + warm-up + MQTT build (APK only), chaos2 + fastcheck.

### Nov 16 - Dec 13 (2-4 weeks)
**Must**
- Gate study for early AI (L1) on the host GGUF. Then `ai_early_k=4` for the shapes that pass, on the board, in
  shadow first.
- Fog uploader live on Supabase + heartbeat + dead-man alert.
- One off-device alert channel (email or push) with ack.
- Shadow-mode pilot with real sensors on one floor, through MQTT.
- OTA bundle with signing and self-test rollback.

**Should**
- 4B feasibility test for agent batches. Then r4 multi-task (one model) behind gate2 (§1.4).
- Router consolidation.
- Thermal soak at 40 °C.
- Backfill gate re-evaluation (L2).
- Operator guide + runbook.

**Could**
- Repack speed-up (L5), only if two models stay.
- Sparse-cadence (TDS) training.
- A holiday calendar.
- WhatsApp/SMS escalation.
- A fog LLM for "analyse deeper" (DEC priority 3).
- Sensor-name independence (deferred by the owner).

---

## 6. Weak evidence and unknowns (read before acting)
- B50 has no absolute per-domain accuracy table, only deltas vs mixA50 (§1.1).
- r3 report accuracy is unknown until the gate. Gen 0.992 at step 2000 is a chat-generation score, not a report gate.
- The 4B with multi-stream agent batches on the NPU, the NPU prefill of 4.6k tokens, and `reason_ctx` 8192 next to
  split-3 are all **unmeasured**.
- Swap after a repack speed-up (≈1 s) and r4 training hours (20-30 h) are estimates.
- Board RAM total, adbd bind address, and whether the Hexagon SDK is needed for a host-only lib rebuild are unknown.
- The early-AI benefit (about 20 min) assumes 4 readings at a 5-min cadence. Its accuracy at k=4 is not measured
  (the 40-min stage is 73.8% for v2, HB 2.42).
- The thermal and power behaviour comes from a lab bench, not an enclosure in the field.
