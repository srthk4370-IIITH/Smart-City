# Reasoner fast: board results (2026-10-27)

All runs are on the QIDK (Hexagon V75) with the reasoner rsn_v1 (Qwen3.5-4B Q4_0 + LoRA merged).

Test conditions:
- Every A/B is a self-contained, temperature-paced board script.
  - The app and htpd are stopped and we wait for exit + 30 s.
  - Each config runs one standalone htpd with the same command line and env as the app.
  - The sequence per config: agents request, warm-up reason request, then 3 or 10 reason requests (keep=true, frozen §9 prompts, forced schema), then the agents request again.
  - The app restarts at the end.
- Prompts (`bench/prompts.jsonl`): q0/q1 are tonight's two real board incidents (INC-0361/0362); q2-q9 are 8 held-out RWH incidents with gold answers.
- Tables come from `scripts/ab_table.py`.
  - **total** = htpd `total_ms` with the reasoner already resident; the swap is measured separately.
  - **vs ref** = byte-identical text / same severity+label+checklist actions / DIFF.
  - **gold** = severity/label/first action vs the RWH gold.

## 0. Determinism: read this first
**The HTP is not run-to-run deterministic.** The code path is greedy argmax (`pick_forced`), with no sampler, temperature or seed. Yet the same binary and the same prompt give different text:
- v8r vs v8s with SPEC=0 (identical code path): q1 (INC-0362) is 453 vs 414 tokens, warning/weather_driven vs normal/normal_operation.
- Inside one config, the warm-up and the repeat of q0 differ in v8s0.

So "byte-identical" can only be asked of prompts that are not near a decision boundary. INC-0362 is one: a +6 kW step in an occupied room, where power has no fixed limit. In the normal variant, the reasoner lists the agent's warning as `corrected` in agent_checks, so that report is internally consistent. Across all A/Bs, 7 of 10 prompts are byte-identical between repeated base runs.

**Recommendation (owner decision, not implemented):**
- A blanket "floor at the agents' severity" contradicts SPEC §3: severity is decided from the evidence, not the agents' status, and correcting agents is the reasoner's job.
- A consistency floor fits the contract. If the reasoner lowers severity below a validated agent's without an `agent_checks` entry (corrected/contradicted) for that sensor, raise it back. No board output tonight would have triggered it.

### 0.1 Decision consistency, 6 prompts × 5 runs (deployed config: v8r path + OPPOLL; htpd_v8t trace; requests start at ≤ 60 °C; `raw/consist/`)
| prompt | runs | severity | label | actions | checks | guarded severity | first divergence: step, margin (top1-top2) |
|---|---|---|---|---|---|---|---|
| q0 INC-0361 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | step 55, margins 0.003-0.128; logits bitwise differ from step 0 |
| q1 INC-0362 | 5 | 80% ({'warning': 4, 'normal': 1}) | 80% | 60% | 80% | 100% | step 7, margins 0.005-0.164; logits bitwise differ from step 0 |
| q4 rwh:rwh-00142 | 5 | 100% ({'critical': 5}) | 100% | 60% | 100% | 100% | step 33, margins 0.027-0.478; logits bitwise differ from step 0 |
| q7 rwh:rwh-00100 | 5 | 100% ({'sensor_fault': 5}) | 100% | 80% | 100% | 100% | step 34, margins 0.009-0.046; logits bitwise differ from step 26 |
| q8 rwh:rwh-00063 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | none (identical picks); logits bitwise identical |
| q9 rwh:rwh-00117 | 5 | 100% ({'normal': 5}) | 100% | 100% | 100% | 100% | none (identical picks); logits bitwise differ from step 194 |
| **all** | 30 | **97%** | **97%** | 83% | 97% | **100%** | |

- The prompt bytes are identical (same request file) and decoding is argmax.
- The logits differ **bit for bit from the first generated token** on 3/6 prompts. This is HTP prefill numerics (fp16 accumulation order), not the prompt, the sampler or the cache.
- Divergence only matters at near-ties: margins of 0.003-0.16 logits.
- INC-0362's severity is decided inside the title, at token 7: "…, warning" vs "…, no fault".
- Owner target: 92-95% severity consistency. Measured: raw 97%, and 100% with the light guard (§4).

## 1. Speculative decoding (research #4/#5): measured, rejected

| run | decode tokens/step | reasoner s (mean) | vs base |
|---|---|---|---|
| llama-server base (`raw/bench_server`) | 1 | 32.3 / 32.4 / 28.0 | — |
| llama-server MTP K=2 | 2.43-2.56 (acceptance 72-78%) | 32.7 / 33.7 / 28.6 | +1-4% |
| llama-server MTP K=3 | 2.90-3.00 (acceptance 63-67%) | 38.8 / 35.5 / 31.5 | +10-20% |
| llama-server ngram-simple | acceptance 7-23% | 33.8 / 33.4 / 28.1 | +0-5% |
| htpd v8r (ref), A/B1 `raw/ab1` | 1.4 (forced batches) | **26.8** | — |
| htpd_v8s n-gram K=8 (`HTPD_REASON_SPEC=8`) | 1.9 steps saved, 17% of drafts kept | 29.7 | **+11%** |
| htpd_v8s n-gram K=4 | 26% of drafts kept | 28.8 | **+7%** |
| htpd_v8s SPEC=0 (= v8r path) | — | 25.8 | noise |

Why it loses:
- Verify batches of 2-4 tokens cost 82-133 ms on HVX, and 5+ tokens cost a fixed ~106 ms on HMX, vs 66 ms for 1 token.
- The recurrent rollback snapshots (`n_rs_seq`) turn off the GDN HMX path, so prefill doubles: 2.8 → 6.2 s.
- Each MTP draft runs the full 248k-vocab Q6_K lm_head.

htpd_v8s keeps the feature, default off (`HTPD_REASON_SPEC`), for a future HTP kernel that makes small batches cheap.

## 2. Bytes per token (bandwidth roof): A/B2 `raw/ab2/table.md`, 10 prompts each

| config | mean total s | old → new | outputs vs base | RWH gold matches (8) | agents before/after = ref |
|---|---|---|---|---|---|
| base (v8r, Q6_K tied lm_head) | **27.8** | — | — | 5/8 | yes |
| `GGML_HEXAGON_OPPOLL=1` (poll for HTP completions) | **25.8** | 27.8 → 25.8 (−7%) | 8/10 byte-identical; q1 = INC-0362 boundary, q4 = 684-token case | 5/8 (same) | **yes (identical)** |
| output.weight Q4_0 (untied lm_head 497 → 357 MB) | 26.7 | 27.8 → 26.7 (−4%) | 0/10 bytes, 7/10 fields | 5/8, but q8 label unknown → normal_operation | yes |
| Q4_0 lm_head + poll | 25.5 | 27.8 → 25.5 (−8%) | — | as above | yes |

- OPPOLL is lossless (the HTP kernels are unchanged; only the host waits by polling instead of sleeping). It is adopted.
- The Q4_0 lm_head changes logits and moved one RWH label away from gold, so it is **not adopted**. The pruned head (§3) removes the same bytes without touching any kept logit.

## 3. Pruned lm_head: A/B3 `raw/ab3/table.md`
See the section added below (filled from the run).

## 4. Integration fixes (Go, `go test ./...` passes)

| fix | what | evidence |
|---|---|---|
| (a) single-domain through the reasoner | `reason.go`: when `reasoner=v3`, an isolated event goes to `reasonV3Fallback` with `isolatedReport` as the fallback only (engine error or gate reject) | `reasoner_v3.go reasonV3Fallback`; latency see §5 |
| (b) chaos incident 1 (566 s, "Occupancy off hours presence") | **Test-script mismatch, not a stall.** chaos.py injected ventilation_failure 3 min after crowded_room without a clear. crowded_room had fallen back to the same CO2 node (SR-AQ-KH03-03) and was holding it, so the held ramp read as a flatline and the open, reported CO2 episode absorbed the rise. By design, the escalation then belongs to the open incident's refinements. The script took the *first new* incident, an unrelated off-hours occupancy event created 9 min later (it finished in 0.9 s). | backend: a held re-inject now supersedes the old injection on that sensor (`engine.go Inject`, test `TestVentilationAfterHeldCrowdedRoom`); `scripts/chaos2.py` clears + resets the replay before each scenario and matches the incident by the scenario's target nodes |
| (c) stray bracket / JSON validity | On the board every reasoner output stops at `json` (forced schema closes the object): 4/4 tonight, 3+3+3+40 in A/B1/2/3, **all parse** without the one-bracket repair. Also found: the two 3 h refinements on the board (INC-0361/0362) were **rejected whole** for listing 7 evidence ids (limit 6), and the operator saw the deterministic report | `checkReportV3` now trims over-long lists (evidence > 6, observations > 5, agent_checks > 4, checklist > 5) with a repair note instead of rejecting; test `TestV3GateTrimsOverlongLists` replays the real board report |
| light severity guard (owner) | rule anchor = worst rule status of the flagged sensors (`ruleSeverity`). If it is warning or critical, a reasoner "normal" is kept at warning, and a calm "no fault" title falls back to the findings title. Nothing else is touched. `severity_basis` {rule, reasoner, final, guard} goes into the report and the UI; every rule-vs-reasoner disagreement is logged as `severity-disagreement` JSON in agent.log | `severityGuard`, `TestSeverityGuardLight` |
| severity first | the severity (2nd key) is streamed with the title as provisional (`SeverityFinal` stays false until the gate) | `v3StreamSeverity`, `TestV3StreamSeverity` |
| early release | `HTPD_REASON_IDLE_MS=3000` (was 20000): every reasoner call is preceded by an agent wave, so holding the reasoner for 20 s only made the next incident's agents wait for the 2.5 s reload | §5 |

## 5. Deploy and app run

### Deploys (`scripts/deploy_fast.sh`, log `logs/deploy.log`; rollback = `deploy_fast.sh rollback` → APK c42dac4f + saved profile)

| when (board) | APK / edge-agent | htpd_profile env added | verified |
|---|---|---|---|
| 04:40 | fast1 7e18f522 / c0e4ff8e (fixes a, b, c, severity streaming) | `GGML_HEXAGON_OPPOLL=1 HTPD_REASON_IDLE_MS=3000` | htpd_v8r ready, reasoner slot `idle release 3000 ms` |
| 09:10 | fast2 9311574c / ee202d29 (+ light severity guard, severity basis in the UI, SW cache v35) | same | htpd_v8r ready, reasoner slot up, `go test ./...` ok |

### chaos2 through the app (fast1; 6 scenarios with clear + reset; requests start at ≤ 60 °C; `raw/chaos2/`)

| scenario | incident | domains | path | event → title | event → report done | reasoner | severity |
|---|---|---|---|---|---|---|---|
| crowded_room | INC-0370 | 3 (cross-domain) | reasoner | 15 s | **39.6 s** | 32.7 s | normal |
| off_hours_presence | INC-0373 | 1 | reasoner (single-domain, fix a) | — | done, 2 NPU calls, warning | — | warning |
| ventilation_failure | INC-0376 | 1 | reasoner (fix a) | 9 s | **41.7 s** | 39.3 s (570 tokens) | sensor_fault |
| heat_buildup | INC-0377 | 1 | reasoner (fix a) | 10 s | **29.5 s** | 26.2 s | normal |
| tank_leak | INC-0378 | 1 | reasoner (fix a) | 13 s | **42.9 s** | 36.9 s | critical |
| power_throttling | INC-0379 | 1 | reasoner, then **gate reject** → deterministic | 11 s | 30.9 s | 26.9 s | warning |

- **End to end: 30-43 s per incident.** The title is up 9-15 s after the event (the operator sees the reasoner's headline and severity within about 7 s of the reasoner starting); the full report follows about 20-30 s later.
- The reasoner path is about +25-35 s for single-domain incidents, which used to finish in about 1 s with the deterministic template. This is the owner's call (the reasoner owns the wording).
- Before: INC-0362 (2 domains) took 30.9 s, with a 29.3 s reasoner.
- Rejection: INC-0379 had a warning with a monitor-only checklist and failed the §3 action floor, so the gate rejected it. The deterministic fallback was used, which is correct behaviour.
- The run was clean: no reload failures and no reboot. Every swap logged `agents' model back`, idle in about 3 s.
- Script note: chaos2 missed INC-0373 (off_hours). It matched the scenario's nodes by the wrong JSON key, so it waited 900 s. The incident itself was fine: done, warning, 2 NPU calls. That is a script issue only.

## 6. Split decoding (htpd_v8x2, `HTPD` request `split`; backend `reasoner_split=3`): LIVE since fast4

The head (title → causal_chain: severity and label) is decoded once. The whole state is then copied to 3 sequences:
- group 1: [observations];
- group 2: [agent_checks … confidence];
- group 3: [checklist … explanation].

Each group continues in parallel, one batched step for all three. Each group ends on a sentinel (the next group's first key), so its last value ends exactly as in training. The answer is assembled in SPEC key order. The first version (no sentinel) let a group-final number run to max_new, which is why the sentinel was added.

| set | config | mean reasoner s | old → new |
|---|---|---|---|
| 10 prompts (`raw/split/table.md`) | single (same binary) | 25.6 | |
| | **split-3** | **21.7** | 25.6 → 21.7 (−15%) |
| 30 more RWH (`raw/split30/acc.md`) | single | 25.7 | |
| | **split-3** | **23.7** | 25.7 → 23.7 (−8%) |
| | split-2 (fork after observations) | 24.7 | −4% |

Accuracy on the 30 RWH prompts (gold = held-out answers):
| config | n | parse | sev=gold | label=gold | action1=gold | action set=gold | sev=single | label=single | mean s |
|---|---|---|---|---|---|---|---|---|---|
| single | 30 | 30 | 27 | 25 | 19 | 13 | 30 | 30 | 25.7 |
| sp2 | 30 | 30 | 27 | 25 | 20 | 18 | 30 | 30 | 24.7 |
| sp3 | 30 | 30 | 26 | 24 | 20 | 14 | 29 | 29 | 23.7 |

- Gate: 31/31 valid for every config (`raw/split30/gate.txt`, `TestReasonerV3ABGate` on the board outputs), and 11/11 on the first set.
- Severity/label vs single: split-3 differs on 1/30 (q31) and 1/10 (INC-0362). Both diverge **before the fork**, inside the title at char 56 / char 34: this is HTP run-to-run noise (§0.1), since the head is decoded by the same single-stream path.
- Action 1 vs gold: split-3 20/30 vs single 19/30. Split-3 was adopted on speed with no gold regression.
- Why not 2.5×: on the hybrid model llama.cpp splits a multi-sequence batch into equal-length ubatches (`split_equal`). Streams with different forced-row counts then cost extra weight sweeps, and 3-row steps cost about 100-113 ms against 66-84 ms for one stream.

App (fast4, chaos2 through the app, ≤ 60 °C; `raw/chaos4/`):

| scenario | event → preliminary | event → title | event → done | reasoner |
|---|---|---|---|---|
| crowded_room (3 domains) | 7 s | 17 s | **39.2 s** | 32.2 s (518 tokens) |
| off_hours_presence (1) | 1 s | 9 s | **29.8 s** | 28.4 s |
| ventilation_failure (1) | 2 s | 10 s | **28.4 s** | 25.9 s |

## 7. Two-stage report (fast3, owner-approved): LIVE
The deterministic report (rules + validated agent findings, `preliminary: true`, a UI banner) is shown as soon as the agents finish: **1-7 s after the event**. The reasoner's report replaces it (`raw/chaos3/`, `raw/chaos4/`).

## 8. Hexagon SDK route (owner-approved 2026-10-28): in progress (detached jobs)
- **Toolchain:** `ghcr.io/snapdragon-toolchain/arm64-android:v0.8` (2.46 GB compressed, the version upstream specifies).
- **Upstream:** llama.cpp 338fce65 (2026-10-27) in `C:/Users/hp/gpu_work/llama.cpp-new`.
  - The local `GGML_HEXAGON_HMX_PIPE_ALL` patch is ported.
  - Multi-stream flash attention needs no patch upstream: the FA solver has no `ne[3]` restriction.
- **Kernel** (`scripts/patch_hex_32x4.py`, tree `llama.cpp-k4`):
  - The upstream tiled HVX matmul already DMAs each weight tile into VTCM once per batch. It re-runs the 4-bit unpack (and/shift/shuffle/valign/sub) for every pair of activation rows.
  - New `tiled_vec_dot_q4_0_32x4` unpacks once for 4 rows; 3 rows run as one 32x4 pass with a duplicated row. Integer dot products and per-column scaling are unchanged, so it is bit-identical to the 32x2 path.
  - Vector ops per weight vector: 4 rows 26 → 17, 3 rows 24 → 17.
  - Host side: `GGML_HEXAGON_MM_HVX_ROWS` (default 4) lets HVX keep up to N rows instead of HMX's fixed cost of about 106 ms.
- **Jobs:**
  - `scripts/run_builds.sh` (detach `hex_builds`; RAM gates: start at ≥ 5 GB available, pause the container below 2 GB).
  - `scripts/hexab_chain.sh` (detach `hexab`; BOARD_LOCK; board `run_hexab.sh`: v8x2 vs new vs k4 vs k4 HVX ≤ 8 rows, split-3 reasoner + B50 agents, ≤ 60 °C).
- **Pruned-head port:** `patch_llama_keep.py` anchors were checked against 338fce65 and apply unchanged. It is still on hold (owner go).

### 8.1 Results (board, ≤ 60 °C start, one NPU client; `raw/hexab/`, `raw/agab/`)

| build | reasoner split-3, 10 prompts (mean s) | agents B50 ×10 batch (warm, s) | agents ×4 batch (warm, s) | decisions vs deployed |
|---|---|---|---|---|
| deployed (620d222 + local patches, htpd_v8x2) | **21.0** | 11.0 | 3.34-3.67 | — |
| upstream 338fce65 (htpd_new) | 21.7 (+3%) | 10.55 (−4%) | 3.16-3.47 (−5%) | agents 42/42 same pattern+status (40/42 bytes; run-to-run floor 9/10); reasoner sev/label as deployed on RWH |
| upstream + Q4_0 32x4 HVX kernel (htpd_k4) | 22.2 (+6%) | 10.7 | 3.16-3.50 | agents 42/42 (41 bytes) |
| k4 + HVX up to 8 rows (`GGML_HEXAGON_MM_HVX_ROWS=8`) | 23.2 (+10%) | 10.6-10.9 | 3.16 | agents 42/42 |

- **No clear win, so nothing was deployed.** Upstream saves about 0.45 s per 10-agent batch but costs about 0.7 s per reasoner report, and one htpd serves both, so the net is about zero.
- The 32x4 kernel saves vector unpack ops but is not faster. For 3-4 rows the HVX matmul is limited by the MACs and the weight DMA, not by the unpack. Moving 5-8 rows from HMX to HVX is slower.
- Build fix: the first build lacked the DSP skel (`libggml-htp-v75.so`, board error 0x80000406), so the ExternalProject `htp-v75` is now built (`scripts/build_skels.sh`).
- Note: until now the A/B "agents identical" checks compared two empty responses (the board has no `htpd_warmup.jsonl`). This round uses real B50 agent prompts from the board incidents (`bench/agents10.json`, `agents4.json`).
- Cleanup: the Docker image was removed (`docker rmi` + `system prune`), and both build dirs and the rejected `rsn_v1_q4_0_outq4.gguf` were deleted. The Docker data VHDX (14.7 GB) only shrinks with Docker Desktop's "Clean / Purge data" (or `wsl --unregister docker-desktop`).

## 9. Pruned lm_head: guarded retry (owner-approved 2026-10-28) and the 02:11 reboot RCA

**Retry job:** `proofs/2026-10-28_master/pruned_ab.sh` (detach `pruned`; waits for the board and BOARD_LOCK, refreshes the lock, detects a reboot by uptime reset). Board side: `scripts/pruned_ab.sh`.
- **Phase 1 probe:** htpd_v8p2 (current htpd with split + `libllama_p.so`) + `rsn_v1_q4_0_keep.gguf`, split-3 + OPPOLL, q0-q2. Any anomaly aborts the run: htpd death, MemAvailable < 1 GB, a bad response, or a reboot.
- **Phase 2:** 10 prompts, full head (htpd_v8x2) vs pruned head. Every request starts at ≤ 60 °C, and telemetry is synced every 2 s.
- **Pass:** same severity/label on 10/10 (INC-0362 noise excepted) and a faster mean. Nothing is deployed.

**RCA of the 02:11 reboot (A/B3, `raw/ab3_crash/`), evidence and its limits:**
- **What the logs show.**
  - The reboot came about 5 s into the second request (q0#1) with the pruned head. The first request with the same binary, library and GGUF had finished normally (34 s, valid JSON, `pruned lm_head: 32864 of 248320 tokens`).
  - Last telemetry: 90-94 °C hottest zone, MemAvailable 6.2 GB (more than the full head's 5.3 GB, since the HTP model buffer was 1988 vs 2448 MB), htpd_v8p alive.
  - There was no ABORT, error or `fastrpc` line in `htpd_keep.log`. Its last lines are normal graph reallocations (`splits = 10`, the same as base).
- **What the logs cannot show.**
  - pstore/ramoops, tombstones and dmesg are not readable (`Permission denied`), and `sys.boot.reason = reboot` is the catch-all value.
  - So the record cannot separate three causes: a thermal/PMIC trip, a DSP/SMMU fault, or an external power loss.
- **Against a pruned-head bug.**
  - The pruned path only changes the size of one matmul (the lm_head rows) plus a CPU-side scatter into the logits buffer. The DSP sees an ordinary Q6_K matmul with 32,864 rows.
  - The same request pattern had just completed once.
  - The same night had two confirmed external unplugs (coordinator), plus the 21:08 reboot that happened with htpd idle and none of my jobs running.
  - A2/A3 reached 94-96 °C on other configs without a reboot.
- **For a pruned-head cause.** It is the only reboot that happened while a new binary/library was active, and it came mid-decode, not at idle.
- **Verdict.** Inconclusive, but more likely external or thermal than the pruned head. The retry starts every request at ≤ 60 °C (the crash run started at about 71 °C) and watches uptime, so a repeat would be strong evidence against the pruned head.
