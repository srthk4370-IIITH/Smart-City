# Unattended pipeline: 4B r3 training -> best checkpoint -> export -> gate (2026-11-10)

Owner: "automate everything ... without your supervision, with proper care and error mitigation ... keep guardrails ... so it
does everything till eval". No Claude session is needed. One page to read: **AUTO_STATUS.md** (this dir, every 10 min).

## Chain of jobs (all detached in WSL, each with a hidden keepalive wsl.exe against `.wslconfig` instanceIdleTimeout=15 s)

| job | script | does | ends |
|---|---|---|---|
| training | `chain_4b.sh` -> `kaggle/local/laptop_train.sh` -> `train_rsn3.py` | 6 h chunks, resume from ckpt_latest (saved every 25 steps); dev eval every 200, gen eval every 400; best-K checkpoints by gen score | epoch 1 end (step 4297) or **early stop, patience 2** (2 gen evals in a row without beating best 0.9917 @ step 2000 -> stops after step 2800 eval, ~17:00 IST 2026-11-10) -> `chain/train.done` |
| post | `post/post_chain.sh` (already running, waiting) | wait (training finished, laptop holds baton, nothing training) -> pick best checkpoint (best.json) -> `export_4b.sh` merge -> bf16 GGUF -> Q4_0 `Code/models_stage/rsn_v3_4b_r3_q4_0.gguf` + md5 -> `gate_4b.sh` vs rsn_v1 | `post/markers/gate.done`, verdict in `post/gate_r3/GATE.md` (core verdict ~3 h after export, informational fog test r3 983 + test_r2 1368 ~10 h more) |
| supervisor | `supervisor.sh` (`start_supervisor.ps1`) | every 10 min: restarts training if it died unfinished; relaunches post if it died before gate.done; restarts the run keepalive; health alerts; writes AUTO_STATUS.md | SUP_STOP file |

## Guardrails (and where they live)
- Heat: pause at GPU >= 92 C, resume <= 88 C (driver holds 87 C itself) — laptop_train.sh, gate_4b.sh. Temps parsed with `cut -d. -f1` (driver prints decimals).
- RAM: WSL hard cap 6 GB (`.wslconfig`); training pauses below 400 MB Windows available (resume 500); chunk start needs 800; export needs Windows >= 1000 MB + WSL >= 2500 MB; gate pauses < 500 (resume 700). Owner keeps Chrome + VS Code open.
- Disk: export needs C: >= 20 GB free + what it writes; big files .part -> md5 -> mv; work dir on NTFS (no vhdx growth).
- No skipped rows: `--oom-stop` (an OOM retries the step one row per forward; a row that still OOMs saves ckpt and exits rc 7 -> supervisor restarts, max 6/24 h).
- Crash loops: supervisor restarts training/post at most 6 times per rolling 24 h, then writes an ALERT and stops trying.
- One GPU job at a time: GPU_LOCK (training holds it per chunk; gate waits for an idle GPU and holds it).
- Kaggle stays off (`baton/STOP`, owner decision). Nothing touches the board, Ollama or other projects. Nothing is deleted.
- Speed-ups in use (verified equivalent): causal_conv1d kernel, `--shared-prefix` (2.1-3x), dev eval shared prefix, gen budget 8400 on 6 GB.

## Owner controls
- Stop training cleanly: `stop.ps1` (repo root) — **also touch SUP_STOP first**, or the supervisor restarts it within 10 min.
  `wsl touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/SUP_STOP`
- Resume everything: `start.ps1`, then `start_supervisor.ps1` (and `post/start_post.ps1` if post is not running).
- Power cut / reboot: nothing auto-starts at Windows logon (not configured — needs owner OK for a scheduled task). After power
  returns run: `start.ps1`, `post\start_post.ps1`, `start_supervisor.ps1`. Training resumes from the last checkpoint.

## Known limits
- AUTO_STATUS "OOM STOP" alert on 2026-11-10 08:34 is historic (Kaggle seq 3, 2026-11-07), not new.
- Each 6 h chunk restart spikes trainer RAM to ~4.9 GB for ~10 min (model reload), then ~1.1-1.4 GB steady.
- The gate's informational suites run long (~10 h) after the verdict; GATE.md shows PASS/FAIL as soon as the core suites finish.
- After gate.done: NO builds start automatically (owner rule) — Claude builds the agreed list (memory: post-training-build-plan).

## Review notes (what was checked)
- `bash -n` on supervisor.sh, export_4b.sh, gate_4b.sh; supervisor first cycle wrote AUTO_STATUS.md correctly (step 2735, best, evals, processes, RAM, temp).
- Finished-detection uses the same rule as post_chain.sh (`chain/train.done`, or status.json stopped after_epoch1/early_stop).
- Post completion = `post/markers/gate.done` (written by post_chain after the gate, PASS or FAIL).
