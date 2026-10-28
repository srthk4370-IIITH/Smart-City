# Reasoner deployment plan: Qwen3.5-4B on the QIDK NPU (2026-10-26)

Scope: CPU and research only. No GPU was used, the board was not touched, and no model was loaded (training was running).
NPU latencies here are **estimates**. They take v2's measured V75 HTP rates (970 tok/s prefill, 19 tok/s decode, 2.80 GB)
and scale them by file size, so for the 2.61 GB Q4_0 they are about 1,040 tok/s prefill and 20.4 tok/s decode, as in P0.
Token counts are **measured** with the Qwen3.5 tokenizer on 400 train_mix incident examples (§9 prompt, tools_v3).

## 1. NPU feasibility: supported. No llama.cpp upgrade and no model change are needed.
Evidence:
- **Build used for htpd.** `C:/Users/hp/gpu_work/llama.cpp` at 620d2225 (`app/htpd/build_htpd.sh`), built on Oct 16 into `build-snapdragon`.
  - `src/models/qwen35.cpp` and `delta-net-base.cpp` are compiled into `bin/libllama.so` (9 `qwen35` strings).
  - `libggml-htp-v75.so` contains the GDN kernels: `HVX_GDN_SOLVE` and others.
- **Hexagon `supports_op`** (`ggml-hexagon.cpp`) covers every op of the qwen35 graph:
  - GATED_DELTA_NET: HMX→HVX, `opt_gdn_select=2` by default. It requires f32 inputs and S_v ≤ 128, and the model has S_v = 128.
  - SSM_CONV (d_conv 4 ≤ 32), ROPE with IMROPE/MROPE modes, SOFTPLUS, SIGMOID, L2_NORM.
  - TRI/SOLVE_TRI/CUMSUM/FILL/DIAG/PAD (chunked path), CONCAT, GET_ROWS, and FLASH_ATTN_EXT for the 8 full-attention layers.
  - MUL_MAT in Q4_0 (tiled) and Q6_K (the tied `token_embd`/lm_head).
  - llama.cpp uses the fused GDN for both decode and chunked prefill (`fused_gdn_ar/ch = true`).
- **GGUF** (`~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf`): arch `qwen35`, 441 tensors, 33 blocks.
  - The blocks are 24 Gated-DeltaNet, 8 full attention (every 4th), and 1 MTP `nextn` block (blk.32).
  - Shapes: ssm state 128, conv kernel 4, 16 groups, 32 value heads; attention 16 q heads / 4 kv heads, head dim 256; vocab 248k.
  - `token_embd` is Q6_K and there is no separate `output.weight`.
- **Real gaps.** These are in htpd, not in llama.cpp:
  1. **One model per process.** Two resident models reboot the board (HANDBOOK 2.27/2.37), so the reasoner has to be an in-process swap (§3).
  2. **Recurrent memory.** Partial `llama_memory_seq_rm` fails on the 24 GDN layers. This breaks htpd's draft/role-draft rollback (`seq_rm(pos,-1)`) and makes `seq_cp`-based stream sharing unsafe.
     - The prefix cache must restore whole `llama_state_seq` blobs instead. That works, because the state includes the recurrent state at the end of the prefix.
     - The host CPU run shows the same class of problem: `base_v3_cpu` turn 3 re-prefilled 2,558 tokens when the cached prefix could not be reused.
  3. **Untested on device.** The numerical agreement of the HTP GDN kernels with the host has to be measured on the board after training: op placement with no CPU fallback, then a host-vs-board diff like v2's 207/208.

Cheapest fix: none needed on the llama.cpp side. On the htpd side: a reasoner slot, a recurrent-safe decode loop (no partial rollback), and a state-blob prefix cache. These are steps H1-H3 in §5.

## 2. Measured token budget (trained-format §9 prompt)
| part | tokens |
|---|---|
| static: tools_v3 incident header + SYSTEM_INCIDENT_SHORT | **1,317** (cacheable) |
| user prompt (v3 input) | p50 **571**, p90 880 |
| final JSON answer | p50 **407**, p90 537 (title 18; keys/punctuation skeleton ≈ 75-110) |
| tool calls per example (gold) | mean **0.12**, 88% none |

Baseline estimate for the trained model with no optimisation:
- p50: prefill 1,888 tok ≈ 1.8 s, decode 407 ≈ 20.0 s, so **≈ 22 s**;
- p90: ≈ 28 s.

**Decode is about 90% of the time**, so the output length and the decode speed are the levers. P0 (untrained, 6.2 calls/report) was 41.5 s.

## 3. Placement and swap options (one NPU client)
Swap cost:
- **Measured:** htpd `ready in` 1.7-2.4 s for the 2.8 GB Llama (warm page cache, proofs logs).
- **Estimated:** Qwen load about 2 s. A swap per reasoned incident adds ≈ **4-5 s**: unload, load Qwen, reload Llama.
- **Plus:** about 1.9 s on the next agent wave if the agents' prefix cache is not persisted (prefill 6.8 → 8.7 s, HANDBOOK 2.37).
- **Plus:** about 1-2 s of cold UFS reads per load if the 5.4 GB of both files are not both in the page cache.

| option | effect | cost / risk | verdict |
|---|---|---|---|
| A. Swap per incident (inside htpd) | +4-5 s per multi-domain incident; agents wait ≈ 25 s | Small htpd change; one model resident at any time (the safe pattern) | **Do first** |
| B. Batch the reasoner across incidents (queue; one swap per wave; reports decoded as parallel streams) | Swap amortised; 2-3 reports in about 1.1-1.3× one (decode is bandwidth-bound); the early alert shows the agents/rules report first, then the reasoner replaces it | Scheduler in reason.go plus multi-stream decode in htpd; recurrent state ≈ 50 MB per stream | **Next**, especially for the 1.5 h/3 h refinements |
| C. Reasoner resident, domain model swapped | No gain: agent waves are more frequent than reasoner calls, and the agents lose their htpd tuning on every reload | Same swap cost, more often | Reject (except an explicit chat/"Ask" session) |
| D. Reasoner on the board GPU (OpenCL) beside the NPU agents | Est. ≈ 24-32 s: measured Llama-3B OpenCL pp 177 / tg 22 tok/s; this tree has the GDN/SSM_CONV OpenCL ops | kgsl buffers are unmovable, and a second model on the GPU **rebooted the board** (2.37). It shares DDR with the NPU (already 49 of about 68 GB/s), so agent waves slow down | Reject unless a board memory test passes |
| E. Reasoner on the board CPU (llama.cpp, mmap) beside the NPU agents | Est. ≈ 40-60 s (not measured on the board: pp ~60-100, tg ~8-12 tok/s) | mmap pages are reclaimable, so not the reboot class. Costs thermal and DDR contention | Fallback for refinements only, after a board measurement |

## 4. Latency plan, ranked (effect on reasoner wall time, p50 estimate)
| # | option | expected effect | cost | status |
|---|---|---|---|---|
| 1 | **Cap tool calls + deterministic pre-fetch** (MEMORY M#, RE-CHECK R#, all related sensors in the prompt; cap 1 early / 2 refine; at the cap the answer is forced with the trained prefix `{"title": "`) | P0 behaviour 41.5 → ≈ 22 s; removes the +3-5 s per extra round and bounds p90 (≤ cap+2 completions) | Done (Go) | **implemented** |
| 2 | **MTP speculative decoding** (the GGUF ships Qwen's own MTP block; this tree has `DRAFT_MTP` with recurrent checkpoints) | decode ×1.4-1.8 → −6…−9 s | htpd: MTP draft plus recurrent-safe verify. The MTP head is not LoRA-tuned, so acceptance must be measured on the host after training | to do (H4) |
| 3 | **Forced JSON scaffolding** (keys, punctuation and enum values fed as forced tokens in one batch, without a decode step each) | ≈ 75-110 of 407 tokens → −4…−5 s; near-lossless because the key order is fixed by training | htpd change (~1 day); the gate still validates | to do (H5) |
| 4 | **Prompt-lookup (n-gram) drafting** from the prompt (ids, numbers and phrases are copied into observations) | −2…−4 s on top of #2 (they overlap) | Needs the same recurrent-safe verify as #2 | after #2 |
| 5 | **Prefix/state cache of the static 1,317 tokens** (state blob ≈ 95 MB, persisted to disk across swaps; the same for the agents' role prefixes) | −1.3 s per report; −1.9 s on the agent wave after a swap | htpd: cache key per model, `state_seq_set` only | to do (H3) |
| 6 | **Stream the title first** (title is the first key, ≈ 18 tokens) | Perceived: the title shows ≈ 1.5-3 s after the reasoner starts; total unchanged | Done (Go: `v3StreamTitle` sets `inc.Title` and logs it; the token sink streams the rest) | **implemented** |
| 7 | **Batching**: reasoner across incidents (B). With the agents: impossible, because it is a different model and forward passes cannot be shared | Throughput ×2-3 per wave; no single-report gain | Scheduler + htpd streams | after A |
| 8 | **Q4_0 (not Q4_K_M)** | Q4_K_M is +6.6% bytes ≈ +1.3 s, and only Q4_0 takes the tiled HMX path, so likely more | Host accuracy A/B is already planned (D6) | choose Q4_0 unless a CI-separated accuracy gap |
| 9 | Re-quantise the tied Q6_K `token_embd`/lm_head (0.52 GB/token, ~20% of the bytes) to Q4_0 | −1.3 s | Accuracy risk; host test first | optional |
| 10 | Shorter prompt | Already done: the short §9 system prompt saved ~1k tokens (~1 s). Anything further is < 0.6 s once cached, and needs a retrain because the contract is frozen | — | no |
| 11 | Context length | No effect: GDN is constant-time and the KV of the 8 attention layers at 4,096 is ≈ 64 MB. Keep n_ctx 4096 (p90 total 2,789) | — | keep |

**Targets.** #1 + #5 + #2 + #3 give ≈ 10-12 s per report, plus a 4-5 s swap, so ≈ 15 s p50. That is under the G2 limit (p50 ≤ 20 s), and accuracy is not traded: #2/#4 are lossless and #3 is checked by the gate.

## 5. htpd work (not done; C++, needs the board after training)
- **H1.** `--reasoner-model` slot. Kind `reason` frees the agent model and contexts, loads Qwen once and keeps it until the next `agents` request. One process, one NPU client. Superviser and ladder rules apply: `oom_score_adj`, `drop_caches` before a load.
- **H2.** Kind `reason`: stop at EOG (`<|im_end|>`), not at the JSON close, because tool calls are not JSON objects. Set max_new 700 and stream pieces.
- **H3.** For `llama_model_is_hybrid`: disable `HTPD_DRAFT`/role-draft/`seq_cp` sharing. Build the prefix cache from `llama_state_seq_get/set` blobs, persisted to disk per model.
- **H4.** MTP draft with a checkpoint/restore verify.
- **H5.** Forced-token scaffolding.
- **H6.** Board P0 after training:
  - op placement (`GGML_SCHED` debug: no CPU-split ops);
  - memory headroom (7.26 GB Normal zone);
  - host-vs-board output diff;
  - measured prefill/decode, swap time, and 30 incidents through the app.

## 6. Backend wiring (done, behind a flag, default off)
- **Code.** `app/backend/reasoner_v3.go` (with `reasoner_v3_header.txt` and `reasoner_v3_system.txt` embedded), plus `reason.go`:
  - the Report fields;
  - in Mode 3, `reasoner=v3` replaces the synthesizer call.
- **Turning it on.** `htpd_profile` `reasoner=v3` (or `SCE_REASONER=v3`). Related keys: `reasoner_engine=llama-server|htpd`, `reasoner_url`, `reasoner_max_calls` (can only lower D7), `reasoner_max_new`, `reasoner_claimflags=prompt`.
  - The `htpd` engine refuses until H1/H2 exist (`SCE_REASONER_HTPD=1`). This is so htpd never answers a Qwen prompt with the Llama model.
- **reasonerPromptV3.**
  - `RenderV3User` is a byte-exact port of `pipeline/lib.render`, including CONTEXT (holidays, night 22-06), units, quality, NO CURRENT DATA, rejected agents, related-line filters, R#/M#/notes and the missing note.
  - It is wrapped in the jinja-rendered Qwen3.5 template, with thinking off and tool turns.
  - Golden test: `testdata/reasoner_v3_fixtures.json`, made by `make_fixtures.py` from the frozen pipeline, the model's `chat_template.jinja` and jinja2. No model was loaded.
  - The static prefix is identical for every incident (the prefix-cache key).
- **Input.** Agent outputs are taken from the validated `AgentCall`, plus the LIMITS/TANK head lines of its prompt. Quality comes from the engine snapshot. Memory lines come from closed incidents on the same nodes (pre-fetch), and R# lines from revisions.
- **claim_flags.**
  - Merged deterministically into `agent_checks` (`by: "claimcheck"`) when the reasoner missed them.
  - In the prompt only with `reasoner_claimflags=prompt`. They are off by default because the model was not trained on such lines.
- **Report fields.** `title`, `observations`, `explanation`, `checklist` (`action` = `checklist[0]`), `agent_checks`, `causal_chain`, `suspect_sensors`, `monitor_next`, `needs_more_data`, `needs_deeper`, `source` (badge: `device:qwen3.5-4b (…)` or `device:rules (reasoner output rejected)`) and `escalation`.
- **Tool loop.** Hard cap: early 1, refinements 2, at most cap+2 completions. Tool calls over the cap are refused and the answer is forced. The read-only tools run over device data: related_context, get_action_history, find_incidents, get_sensor_history.
- **Escalation (offer only, DECISIONS.md).** `verification_failed`, `too_big` (> 4 calls wanted), `coverage` (a tool result with `complete:false`) and `model_offer` (`needs_deeper`). Nothing is sent anywhere.
- **Gate (`checkReportV3`).** It checks:
  - enums, the 12-action whitelist and the severity-to-action floor;
  - known ids and grounded numbers in observations;
  - title ≤ 80 characters and never "normal" on a non-normal report;
  - actuation language.
  A rejected report falls back to the deterministic report (fallback.go).
  - The floor was aligned with the generator policy. It accepts **all 6,046 gold answers** (dev 299, RWH 150, train 5,597): 0 false rejections.
- **Tests.** `reasoner_v3_test.go` covers the golden prompt and tool turn, context/units, the gate (8 rejection kinds), claim-flag merge, escalation, title streaming, the cap (direct / capped / cap 0) and default-off. `go test ./...` passes (WSL, GOMAXPROCS=2).
- **Host harness (for later).**
  - `reasoner_v3_host_test.go` (`TestReasonerV3Host`, skipped without `SCE_REASONER_HOST_URL`; `TestReasonerV3GateOnGold`) and `run_host_harness.sh <gguf> [n]`.
  - The script starts a CPU llama-server (port 8092, c 4096) only if ≥ 3 GB is free, drives the real backend loop over the dev set with the gold tool results replayed, and writes JSONL: gate result, completions, tool calls, tokens, latency.
  - Run it only after training.
- **Approximation to fix when there are real data.** The R# lines use "HH:MM severity: title". The training data words them as "warning: CO2 was 603 ppm (acknowledged by …)".
