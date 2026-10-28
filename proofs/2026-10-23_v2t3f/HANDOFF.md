# 3f handoff (2026-10-24): no candidate passes the gate yet. v2 stays deployed.
Full tables: `RESULTS_TABLES.md`. Raw samples: `raw/<set>/<cand>/`. Literature and design notes: `RESEARCH.md`.

## Gate
- Every stage (early, 1.5 h, 3 h) at or above v2 on pattern and status.
- No slice down more than 1 pt, unless within paired noise with a justification.
- Compound not down. JSON 100%.
- Scored on host Q4_0 GGUFs (`post_3f.sh` = v2 recipe), CUDA llama-server b11815.
- Select on dev (dev3f, 2,010 rows; rw5dev, 313 rows). Confirm on test (3e set, 1,148 rows; rw5test, 318 rows).

## Candidates (v2 → candidate, %; W/L = paired wins/losses)
| cand | what | key numbers | verdict |
|---|---|---|---|
| mixA50 | v2 + 0.5(c49 − v2), delta-space WiSE-FT | **test:** early p 79.1→80.4, 3h s 77.4→81.5, compound held, realworld p/s up, JSON 100%; **1.5h s 77.5→75.7 (2/5)**; dev: all stages up (1.5h s +1.5) | best; fails test 1.5h status |
| soup3 | mean of c30/c45/c49 | dev: calm/routine s 86.2→83.9 (1/14) | fail |
| m50rwL | mixA50 + §5 SFT (LR 1e-5, 1 epoch, 1.5× replay) | dev: early p 77.0→74.2 (4/15) | fail |
| m50rw50 | mixA50 + 0.5·SFT delta | dev: early p −1.3, 1.5h s −1.5 | fail |
| m50rwB | mixA50 + §5/low-pH SFT (LR 2e-5, 1.5 epochs, half event replay) | rw5dev s 62→75 (glitch 40→90, chatter 29→52, acidic 0→58, co2_floor 40→60); dev: calm s −2.5, 1.5h −1.2 | §5 learned, general regressions |
| repL | c49 + status-preserving anchor DPO (ref c49) | dev: compound s 87.6→84.5 | fail |
| mixRep50 | v2 + 0.5(repL − v2) | dev: all stages ≥ v2, only compound s −1 row; **test: 1.5h s 77.5→75.7 (2/5), compound p/s −1.4/−2.7** | fail on test |
| 3e run1/run2 | see `../2026-10-23_v2t3e` | c49 = run2 checkpoint-49 | — |
- **Best GGUF so far (not gate-passing):** `~/smartcity_runs/agents_v2_topup3f/post/gguf/ft_mixA50_q4_0.gguf`, md5 `8397bb0e8a58005cf339999fa6634ad3`.

## Open hypothesis / next steps
- **The 1.5 h status losses come from c49 in every mix:**
  - 3 power rows warning → critical (gradual read as exponential, spike/exp critical);
  - 1 water oscillation warning → normal;
  - 1 AQ dip read as erratic → sensor_fault.
- The anchors fixed normal-vs-alarm displacement, not the warning-vs-critical one.
- **Plan (queued, not run):**
  1. α = 0.3 mixes: `mixA30` (`post/mixA30/choice.json` exists) and `mixRep30` = [[v2, .7], [repL, .3]], on dev.
  2. Task arithmetic: mixRep50 + β(m50rwB − mixA50), β = 0.5 / 0.3 (`post/mRB5`, `post/mRB3`; signed weights in merge_mix), on dev + rw5dev.
  3. Pick on dev, then run the test gate.
- **3g ideas:**
  - add warning-vs-critical anchor pairs for power (rejected = critical on gold-warning rows);
  - lower the §5 SFT LR or add more event replay;
  - per-layer α (HMA, Lin et al.).

## Paths
- **Adapters:**
  - v2: `~/smartcity_runs/agents_v2/adapter`
  - c49: `~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49`
  - mixA50 as an exact rank-64 LoRA: `~/smartcity_runs/agents_v2_topup3f/m50_adapter` (`mix_to_lora.py`)
  - `.../m50rw/checkpoints/checkpoint-77`, `.../m50rwB/checkpoints/checkpoint-122`, `.../rep/checkpoints/checkpoint-30`
  - Intermediate checkpoints and optimizer states were deleted for disk space.
- **Data (`~/smartcity_runs/agents_v2_topup3f/`):**
  - dev: `dev/dev3f.jsonl`
  - §5 sets: `rw5/rw5_{train,dev,test}.jsonl` (acidic appended from `rw5x_*`), plus `rw5/manifest_rw5*.json`
  - SFT files: `data/train3f_rw5sft{,B}.jsonl`
  - anchors: `data/anchors_c49.jsonl`
  - review page: `proofs/.../rw5/review_rw5_train_60.html`
- **Scripts:** `Code/smart-city-edge-agent/training/v2/topup3f/`
  - `gen_dev3f.py`, `gen_rw5.py` (`--acidic`), `merge_mix.py`, `post_3f.sh`, `pipe_3f.sh`, `master*_3f.sh`, `watchdog.sh`,
    `brief_3f.py` (1-line summary per candidate), `make_results.py`, `anchor_3f.py`, `build_3f.py`, `build_rw5sft.py`,
    `mix_to_lora.py`, `ramguard3f.ps1`, `pause3f.sh`
  - Training uses `topup3e/train_3e.py`. `topup3e/host_eval3e.py` now caps llama-server at `-t 2 -tb 2`.
- **Eval refs:** v2 = tag `v2cuda` in `eval_{dev,rw5dev,test,rw5test}/eval/`. Test v2cuda is a copy of the 3e one.

## How to run
1. Write `post/<TAG>/choice.json` = `{"mix": [[adapter, w], ...]}`.
2. `bash pipe_3f.sh dev|rw5dev|test|rw5test TAG...` (serial: build, then eval, resumable).
3. Run it from a `master*_3f.sh` that sources `watchdog.sh`, launched as your OWN `run_in_background` shell, plus:
   - a background loop touching `~/smartcity_runs/agents_v2_topup3f/HEARTBEAT` every 2 min (the watchdog kills the jobs when it is > 15 min old);
   - while the benchmark runs: a marker `python3 -c "import time; time.sleep(N)" topup3f-gpu-claim`, so the driver yields (it stops for `python.*topup`).
4. Summary: `python topup3f/brief_3f.py ~/smartcity_runs/agents_v2_topup3f/eval_dev v2cuda TAG`.

## Pitfalls (all hit in 3f)
- **RAM and the RAM guards:**
  - A GGUF build next to an eval drives Windows free RAM below 1.5 GB, and the 3e ramguard then kills the eval, orphaning its llama-server. Always run builds and evals serially.
  - `ramguard3f.ps1 -PauseMB 2048 -ResumeMB 3072` pauses the 3f jobs; check it is running.
- **Process and pattern matching:**
  - `pkill -f <pattern>` matches its own `bash -lc`. Use bracket patterns (`"[h]ost_eval"`).
  - GPU wait: use `pgrep -x llama-server`, not `-f`, or other agents' shells look like servers.
- **Script mechanics:**
  - Parse PowerShell output with `tr -dc 0-9` (CR bug).
  - Never edit a running bash script.
  - Two pipelines at once duplicated rows: dedupe by id.
- **Disk:** at most 2 candidate GGUFs. `post_3f.sh` deletes `merged/` and `f16.gguf`; delete rejected GGUFs.
- **Generator caveats (`gen_rw5.py`):**
  - rw5 eval rows need `slices_all` (gen_rw5 does not add it; added afterwards).
  - SCRC pH is unusable as a base (railed or noisy), so the acidic slice uses a documented synthetic pH base.
