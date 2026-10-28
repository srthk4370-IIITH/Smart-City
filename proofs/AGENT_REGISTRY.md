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
