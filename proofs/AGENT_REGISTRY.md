# Agent registry (resume after a rate limit or restart)

At every wake-up or "usage limit has reset", the main session reads this file. For each agent with status
`running` that has stopped (task notification `failed: rate limit`, or no report yet), it resumes the agent
with **SendMessage**, using the agent id and the resume message below. A new agent is started only if resuming
fails; its id is then updated here.

Long-running work (training via `run_topup.ps1` / WMI, board scripts) runs outside the agents and is not
affected by rate limits.

## (RESUMED 2026-10-23 by the owner; the laptop is in use, so one GPU job at a time and only with at least 3 GB free) PAUSED 2026-10-23 ~12:50 IST by the owner (usage limit at 93%; laptop needed)

Every agent was stopped (TaskStop) and every WSL job was killed; then `wsl --shutdown`. Ramguard was stopped by
creating `%LOCALAPPDATA%\sce_train\STOP_RAMGUARD`; **delete that file before restarting training.** The board
stays on v2 + htpd_v7 and is unaffected.

**To resume:** SendMessage each agent below with "Owner resumed after pause: continue from where you stopped; all
WSL jobs were killed, so relaunch them". The agents keep their transcripts.

- **3f (a0f1fdf8c8cf2adb7)**
  - It was evaluating the candidate `mixA50` (WiSE interpolation, α 0.5) on the dev set, partly done:
    `~/smartcity_runs/agents_v2_topup3f/eval_dev`. `host_eval3e.py` resumes the missing rows.
  - `queue_train_3f.sh` was queued after it.
  - It was about to write the REALWORLD §5 generator (it needs metric limits and allowed causes per role).
  - Resource rules: nice 19, GPU only, ≤ 2 threads, ramguard at 4 GB.
- **Benchmark (ac98ec094d67a09aa)**
  - `driver.sh` was killed while it waited for the GPU. No model had run yet in this round (11/12 reports parse OK
    from earlier).
  - Relaunch the driver; it yields to 3f.
- **UX v34 (a37adfb7a1960d996)**
  - It was mid-edit in Go. The new workflow code exists, but wiring into `reason.go`, `store.go`, `refine.go`,
    `domainhealth.go`, `server.go` and `main.go` was not done.
  - **The working tree may not compile.** Do not build or deploy until v34 finishes and `go test` passes.

| Agent id | Task | Status | Resume message |
|---|---|---|---|
| a3892e9bfe267bd4f | Real-world data workflow hardening (`proofs/2026-10-23_realworld/REALWORLD.md`, backend data-quality fixes and tests) | done | "Rate limit reset — continue the real-world workflow task from where you stopped." |
| a4ea6e24e4558fc6a | Model 3e (`proofs/2026-10-23_v2t3e/RESULTS.md`): run1 c40/c60/c70 all fail the gate (compound -17 pts) | done; c20 + run2 (c30, c49) run unattended, see pipeline.log | main scores: `host_eval3e.py table --ref v2cuda --cand run1c20 run2c30 run2c49` |
| ab15dee89d2eefc00 | UI overflow fixes (`proofs/2026-10-23_ui_overflow/`) | done | "Rate limit reset — continue the UI overflow task from where you stopped." |
| ac4c7cc5e3cf517b4 | Why top-ups fail, plus alternatives (`proofs/2026-10-23_topup_research/TOPUP_WHY.md`) | done | "Rate limit reset — continue the top-up research from where you stopped." |
| ac98ec094d67a09aa | Reasoner benchmark on the laptop GPU (`proofs/2026-10-23_reasoner_research/P0/host_bench/`; GPU priority goes to model training) | done (RESULTS.md; Qwen3.5-4B, FT plan awaiting owner) | "When results/driver.log shows ALL DONE: run make_tables.py and write RESULTS.md (gates first, recommendation)." |

| a0f1fdf8c8cf2adb7 | Model 3f: research and train continued from v2 only (interpolation, targeted repair, label noise, augmentation; `proofs/2026-10-23_v2t3f/`) | done (handoff: 2026-10-23_v2t3f/HANDOFF.md) | "Rate limit reset — continue the 3f task from where you stopped (check detached training/eval jobs first)." |
| a37adfb7a1960d996 | UX v34: approval lifecycle, quality chip, maintenance UI, countdown, shift summary, grouping, filters, notification, small fixes (`proofs/2026-10-23_ux_v34/`) | done (deploying) | "Rate limit reset — continue the UX v34 build from where you stopped." |
| a6fb601c74e4d0d6e | 3f-next / 3g, now track A (continued SFT v2.1 with replay); was the LoRA-scaled screening loop from HANDOFF.md (waits for benchmark RESULTS.md before GPU) | running | "Rate limit reset — continue 3f-next from where you stopped (watchdog jobs died; relaunch)." |
| a7bd48fc617ae4c01 | Track B: grammar-constrained decoding + rule post-checks, CPU only (`proofs/2026-10-24_trackB/`) | running | "Rate limit reset — continue track B from where you stopped." |

Status values: `running`, `done` (report received), or `stopped-by-user`.

### 2026-10-29 evening (rsn_v3 + latency)
| Agent id | Task | Status | Resume message |
|---|---|---|---|
| ad77c356ab5b3973a | rsn_v3 data fixes + Go/Python tool parity (`proofs/2026-10-29_rsn_v3/`, store copy train_store_v3.sqlite, chat_tools_v3*.go) | running | "Limit reset — continue the rsn_v3 data fixes + parity task from where you stopped (re-run run_all.sh, verifier self-test, Go tests)." |
| ae9c947d412b41fa1 | rsn_v3 Kaggle bundle (distill + incidents ~12k + QLoRA r32) + guarded scripts (`proofs/2026-10-29_rsn_v3/kaggle/`) | running | "Limit reset — continue the rsn_v3 Kaggle bundle task from where you stopped." |
| a77eddd77cbac65cf | Parallel weight repack in libggml-hexagon.so, bit-identity test, one guarded lab A/B (`proofs/2026-10-29_latency/repack/`) | running | "Limit reset — continue the repack task; first check the board app is running (adb ps edge-agent/htpd) and proofs/2026-10-29_latency/repack/STATUS.md." |

Board live (2026-10-29 19:00 IST): deploy13 (APK 5da085bc, htpd_v8x5, rsn_v1 full head, chat router). Rollback snapshot: proofs/2026-10-29_latency/deploy8/known_good. Pending deploy: chat_router what_if zero-driver sentence (code done, tested).
| ac4ca8b13b3b0c98b | rsn_v3 laptop chat distillation (llama.cpp CUDA, prompt cache, detached, guarded; `proofs/2026-10-29_rsn_v3/distill_laptop/`) | running | "Limit reset — continue the laptop distillation task; check distill_laptop/STATUS.md and whether the detached job is alive before relaunching." |
(ad77c356ab5b3973a data+parity: done. a77eddd77cbac65cf repack: built, bit-identical; A/B window repack_ab started 2026-10-29 by main session. ae9c947d412b41fa1 Kaggle: resumed with curriculum/split-bundle changes.)

### Detached jobs (2026-10-30, survive Claude limits; check before relaunching)
| job | pid file / log (WSL ~/detached) | status file | stop |
|---|---|---|---|
| distill_laptop (chat self-distill) | rsn3_distill.* | proofs/2026-10-29_rsn_v3/distill_laptop/STATUS.md | distill_laptop/STOP |
| rsn3_laptop_chain (replay, bundle B, 2B train, 4B watch, gates) | rsn3_laptop_chain.* | proofs/2026-10-29_rsn_v3/kaggle/STATUS.md | kaggle/chain/STOP |
| ndk29 (NDK r29 rebuild, repack A/B, VERDICT) | ndk29.* | proofs/2026-10-29_latency/repack/STATUS.md, VERDICT.md | repack/STOP_ndk29 |
| q2b (2B base on NPU speed probe) | q2b.* | proofs/2026-10-29_latency/q2b/STATUS.md, VERDICT.md | q2b/STOP |
Owner pending: Kaggle session 1 with bundle A (kaggle/build/r2/rsn_v3_bundle.zip, md5 d5efe71b…), send PROJECTION line.

### 2026-10-30 update
- q2b DONE: base 2B runs on the NPU, decode 37.6 vs 4B 127.8 ms/step; projected reasoner 7.1 s vs 23.2 s (accuracy pending 2B training) -> q2b/VERDICT.md
- ndk29 DONE: rp29 lossless (text diffs = run-to-run noise), load 3.70 -> 2.80 s -> deploy14 (2026-10-29_latency/deploy14.sh, log deploy14/deploy.log)
- rsn3_distill v2 running (pid 18666, 14 h cap, auto-finalize). ~40% paused on GPU 85 C. Hard train records: ~1,500 of 3,393 within the cap; rest get template rows.
- **WSL instanceIdleTimeout=15 s kills detached jobs once no wsl.exe session is open.** Every long detached job needs a hidden keepalive:
  `Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh <name> <hours>"`
  Live: rsn3_distill (15 h), rsn3_laptop_chain (96 h, pid 22806).
- 2026-10-30 13:05 IST: board fastcheck x2 (46.7 s fast path once after long idle, then 6.4 s / AI 45.2 s); app added to the doze whitelist (owner OK; undo `dumpsys deviceidle whitelist -com.iiith.smartcityedge`).
  .wslconfig memory 8GB -> 5GB (owner OK; backup distill_laptop/wslconfig.bak_2026-10-30); WSL restarted; rsn3_distill relaunched (pid 493, 8 h cap, keepalive 9 h), rsn3_laptop_chain relaunched (pid 822, keepalive 96 h).
- 2026-10-30 14:07 IST: raise_wsl_cap watcher (Windows, hidden, pid 11248): on kaggle/chain/distill.done -> .wslconfig 5GB->7GB, wsl --shutdown, relaunch rsn3_laptop_chain + keepalive. Log kaggle/local/raise_wsl_cap.log; stop: touch kaggle/local/STOP_raise_cap
- 2026-10-30 14:55 IST: RAM: Copilot closed (owner OK); distill teacher -cram 1024->256, hard-restarted (pid 7215, 7 h cap, keepalive 8 h; GPU_LOCK kept so the chain kept waiting); WSL drop_caches + compact. Windows available 1.4 -> 2.6 GB.
- 2026-10-30 15:20 IST: agent 'spec_split sim' (background, laptop CPU only): offline acceptance/step simulation of split-3 + per-stream speculative drafts (prompt n-gram, past-report suffix corpus) -> proofs/2026-10-30_spec_split/SIM.md. No board, no GPU.
- 2026-10-30 15:40 IST: spec_split sim DONE (PC K8 m2: steps -70%, decode ~24 -> ~9 s projected, restores unpriced). Agent 'htpd v9 split+spec' (background, laptop CPU only): implement HTPD_REASON_SPLIT_SPEC (two seq slots per stream, no n_rs_seq), host tests, board binary -> proofs/2026-10-30_spec_split/v9, STATUS.md there. No board.
- 2026-10-30 lab window spec_ab (base v8x5+rp29 vs htpd_v9 K=8 m=2 corpus_excl_q10_15) running from laptop (lab_run.sh, WINDOW_MAX 2700); results -> proofs/2026-10-29_latency/spec_ab/. Emergency: touch proofs/2026-10-29_latency/DEMO_NOW
- 2026-10-30 21:15 IST: deploy18 live (htpd_v9c split-spec K=8 + ALIGN, corpus 463 reports): lab reasoner 23.3 -> 9.1 s, fastcheck AI 38.5 s. HANDBOOK 2.63.
- 2026-10-30 22:45 IST: laptop lag = Windows thrash (615 MB avail, 23k pages/s) after WSL cap 7GB + replay llama-server RSS 6 GB (mmap). Killed my replay server/chain, laptop_chain.sh replay server now '-lm none' (RSS 3.3 GB), chain relaunched (pid 2842), replay resumes at 513 rows.
- 2026-10-30 22:55 IST: real lag cause = llama-server default --cache-ram 8 GB (prompt cache grew RSS to 6.2 GB). Added -cram 256 to laptop_chain replay, gate_eval.sh, r1 eval_gguf.sh. Replay server now flat ~1.6 GB; chain relaunched, replay 629/~1000.
- 2026-10-31 01:35 IST: laptop_train watchdog narrowed (pause >=84 C, resume <=79 C, 10 s poll; RAM metric = Windows AvailableMBytes in guard.sh, resume >= 2 GB); applies from next 3 h chunk (~02:21). Background agent launched: board latency round (lossless; may deploy19; proofs/2026-10-31_latency/).
- 2026-10-31 01:30 IST: agent 'latency night 10-31' (background): lossless latency cuts (corpus growth/adaptive K, app orchestration), lab windows via lab_run.sh, proofs -> proofs/2026-10-31_latency/. Emergency: touch proofs/2026-10-29_latency/DEMO_NOW
- 2026-10-31 01:42 IST: lab window live_ab (htpd_v9d: cur corpus vs +real-app reports vs +live growth; held-out real app incidents q100-105) from laptop (lab_run.sh, WINDOW_MAX 4800). App down during the window. Emergency: touch proofs/2026-10-29_latency/DEMO_NOW
- 2026-10-31 02:35 IST: deploy19 (htpd_v9d live corpus + real-app corpus + KLONG16) running, log proofs/2026-10-29_latency/deploy19/deploy.log; rollback auto on chaos/fastcheck failure (deploy19/known_good)
- 2026-10-31 02:25 IST: deploy19 LIVE (htpd_v9d live corpus + reason_corpus_v2 576 docs + KLONG16/ROWS48, rp29, APK unchanged): chaos 2 rc=0; fastcheck x2 pass, fast 5.8/5.9 s, AI update 27.0/27.1 s (deploy18 38.5 s). Rollback deploy19/known_good.
- 2026-10-31 02:42 IST: agent 'rsn_v3 repair+dpo scripts' (background): writing kaggle/local/repair_pool.sh + dpo.sh (PLAN_V2 stages 3-4), CPU-only validation, no GPU, not hooked into laptop_chain.
- 2026-10-31 03:05 IST: agent 'agents latency' (background): agents fast-path profile + htpd_v9e (agent draft index: n-gram 8..1, 500-output hashed recent index, persisted agent corpus; off by default). Host check job ag_host (WSL CPU, q2b). Lab window ag1 (base v9d / v9e / base2 v9d, 24 real agent requests + 1 swap sample) via proofs/2026-10-31_agents_latency/lab_ag_run.sh; app down during the window. Emergency: touch proofs/2026-10-29_latency/DEMO_NOW. Proofs -> proofs/2026-10-31_agents_latency/
- 2026-10-31 03:13 IST: agent 'rsn_v3 repair+dpo scripts' DONE: kaggle/local/{repair_pool.sh,dpo.sh,repair_common.sh,repair_lib.py,cont_train.py,cont_chunk.sh} + PLAN_V2 'Stages 3-4' section; CPU-only dry runs (tiny random model) in scratchpad; not hooked into laptop_chain; nothing running.
- 2026-10-31 03:19 IST: 'agents latency' DONE. Profile + htpd_v9e (agent draft index, off by default) -> proofs/2026-10-31_agents_latency/VERDICT.md. Lab ag2: agent wall -21% (2594 -> 2058 ms/request, steps 552 -> 366) but outputs 23/24 identical (base vs itself 24/24; one observation wording flip) -> NOT deployed; live stays deploy19. deploy20.sh ready if the owner accepts. lab_ab.sh/lab_run.sh stop lists now include htpd_v9e. App back up (edge-agent htpd_v9d).
- 2026-10-31 03:40 IST: owner away overnight. deploy20 (htpd_v9e) running; overnight steward agent launched (soak tests every ~20 min to proofs/2026-10-31_night/, lossless research, max 2 deploys, keep Windows avail RAM >= 2 GB, don't touch other Claude sessions or rsn_v3 jobs).
- 2026-10-31 03:50 IST: deploy20 LIVE (htpd_v9e agent draft index): chaos 2 rc=0, fastcheck pass, AI update 21.7 s (deploy19 27.0), fast 5.8 s; chat 3/3 ok. Rollback deploy20/known_good.
- 2026-10-31 07:35 IST: night steward: deploy21 (htpd_v9f chat drafts, lab chatlab/cl1: chat requests -17% mean, 10/10 identical text) running, log proofs/2026-10-29_latency/deploy21/deploy.log; auto-rollback deploy21/known_good (= deploy20)
- 2026-10-31 07:52 IST: deploy21 LIVE (htpd_v9f chat drafts + chat_corpus.jsonl, HANDBOOK 2.66): chaos 2 rc=0, fastcheck x2 pass (5.7/5.6 s, AI 26.7/37.1 s), chat 4/4. Rollback deploy21/known_good (= deploy20). Soak (proofs/2026-10-31_night) runs to 09:00 IST.
- 2026-10-31 09:00 IST: night steward done. Soak 16/16 pass (proofs/2026-10-31_night/VERDICT.md); live = deploy21 (htpd_v9f). Soak job ends itself at its next cycle (~09:14, no board action).
- 2026-10-31 13:50 IST: validator/gap agent: bulk-cleared 399 needs_decision incidents via /api/incidents/{id}/dismiss (proofs/2026-10-31_validator/bulk_clear.txt); deploy22 (APK: weather-only critical validator rule + critical skips window-coverage gate) running, log proofs/2026-10-29_latency/deploy22/deploy.log; auto-rollback deploy22/known_good (= deploy21).
- 2026-10-31 19:55 IST: validator/gap agent done: bulk clear 399 -> 0 needs_decision; deploy22 r2 LIVE (APK d1250c3c), r3 (32506330, re-arm fix) built not deployed (C: full); HANDBOOK 2.67; proofs/2026-10-31_validator.
