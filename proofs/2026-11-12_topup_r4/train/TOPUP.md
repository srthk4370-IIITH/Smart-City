# r4 top-up of the gated 4B r3 model (step 2800): unattended train -> pick -> export -> STRICT gate (2026-11-12)

Status: **built and CPU-tested, not started** (the GPU is busy; owner starts it). Start adapter (read-only):
`~/smartcity_runs/KEEP_rsn3_4b_r3_s2800/ckpt_best_2800` (r 32, alpha 64). Deployed model stays `rsn_v3_4b_r3_q4_0.gguf`
unless the r4 gate passes. New behaviour taught: a short `<think>` before the report JSON for multi-domain incidents, an empty
think for single-domain ones (owner: adaptive thinking for multi-domain reports).

## Why this top-up should work where earlier ones did not

| earlier failure | cause (TOPUP_WHY.md, rsn_v2 notes) | this run |
|---|---|---|
| domain-agent top-ups "at the noise floor" | ~800 rows, still in warm-up at the checkpoint; dev gains of 2-3 rows on 68-77-row slices (±9-10 pt CI) | ~15k new rows, full schedule (warm-up 3 %, cosine to 0.1x); gate on 400+ held-out items with a paired test, plus 19 checks and 983 fog records |
| rsn_v2 regressed | new data only, high LR: forgetting | **1:1 replay** of r3 rows in every optimizer step (8 new + 8 replay), **LR 3e-5** (r3 peaked at 1e-4, was at 3.4e-5 at step 2800), weight decay 0.01, dropout as r3 |
| "best" checkpoints that were not better | best-K by one dev score, no reference | the **start adapter is scored at step 0**; a checkpoint is kept only if the combined score beats the start AND the r3 slices are not lower than start - 0.01 (a cross-domain gain cannot hide an r3 regression); early stop after 3 evals without a better eligible score |
| a gate against an old baseline (rsn_v1) | passing rsn_v1 says nothing about r3 | **STRICT gate vs r3-2800** itself (below); FAIL keeps r3-2800 |
| silent row drops / OOM skips | | `--oom-stop` (never skips rows), data check (> 2 % of new rows unusable at 7424 tokens -> exit 9), INIT_CHECK |

## Trainer: `topup_train.py` (new file; `train_rsn3.py` and `cont_train.py` unchanged)

Choice: a new trainer that **imports** train_rsn3.py and reuses its encode/prep, `loss_fn`, `loss_fn_batch`, `micro_batches`,
`shared_prefix_step`, `apply_fit_levers` (HeadCPU), `dev_losses`, `gen_score`. cont_train.py was not extended: it has none of
the 6 GB levers (no micro-batching, shared prefix, head-cpu, ckpt-offload, mlp-chunk, lean-host, oom-stop), so the 4B would
not fit or would run 2-3x slower. Patching train_rsn3.py was avoided so the r3 lineage stays byte-identical.

- `--init-adapter`: LoRA weights from the start adapter (r/alpha/targets from its config, asserted = train_rsn3.TARGETS),
  **fresh** AdamW8bit + scheduler + step 0. `INIT_CHECK`: every loaded LoRA tensor is compared with the file (max_abs must be 0,
  no missing keys) or the run exits 10. A resume loads `ckpt_latest` (adapter + optimizer + scheduler + RNG + step) and never
  re-reads the start adapter.
- Fit flags kept, as the r3 run: `--micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix
  --oom-stop`, `RSN3_GEN_TOK_BUDGET=8400`, max_len 7424 (FIT.md maximum on 6 GB; not raised: rows over 7424 are dropped and
  counted, > 2 % of the new rows aborts so the owner decides).
- Schedule (`schedule.json`, resumable): one pass over train_new; each step = 8 new + 8 replay rows (replay reshuffled and
  cycled if shorter). LR 3e-5, warm-up 3 %, cosine to 0.1x over the plan.
- Generation eval at step 0 (start) and every 100 steps: **r4** = r4 dev incidents (60, prompt in the row's think mode;
  parse / severity / label / think decision, report parsed after the think block) + r4 dev chat (60, verify_chat);
  **r3** = the r3 run's slices (gen_inc_r2 + gen_chat_r3, 40 + 40, train_rsn3.gen_score unchanged). Combined = 0.5 r4 + 0.5 r3.
  Dev loss every 100 steps when `--dev` is given. Best-K = 3.
- Exit codes: 0 plan done, 3 chunk hours / STOP, 6 early stop, 7 OOM STOP, 9 data check, 10 init check.

### CPU verification (`test/cpu_test.py` -> `test/cpu_test.json`; tiny random Qwen3.5 as speed/EQUIV.md, real tokenizer, 24 real r3 rows, no GPU)

| check | result |
|---|---|
| init: start adapter loaded, 1 step at LR 0, saved | INIT_CHECK 60 tensors, 0 missing, max_abs 0; saved adapter == start: max_abs **0.0** |
| resume: 2 steps + new process to 3 vs 3 straight | adapter max_abs **0.0**, optimizer exp_avg diff 0.0, scheduler equal; training moved the adapter (rel L2 0.040 vs start) |
| 1:1 mix | groups (new, replay) = (4,4) (4,4) (4,4) (2,4) for 14 new rows, accum 8 |
| selection (scripted scores) | start 0.70 scored at step 0; step 1 (r4 up, r3 -0.05) **not eligible**; kept best_0002/0003/0004 only (all > start); early stop exit 6 at step 5 |
| split_think / gold_of | 5 cases ok |

`test/static_test.sh` -> `test/static_test.txt`: bash -n on all scripts, py_compile, and the gate scorer on cached results
(r3 vs itself: (a) FAIL, all 19 checks + 3 fog slices ok; r3 vs rsn_v1 on test_r2: (a) PASS).

## Controller (`chain_r4.sh`, `topup_chunk.sh`, `ctl_r4.sh`, `run_r4.env`, `paths_r4.sh`)

Own run dir `~/smartcity_runs/rsn3_4b_r4topup`, STATUS tag `[chain_r4 r4topup]` / `[topup_chunk r4topup]` in
`proofs/2026-10-29_rsn_v3/kaggle/STATUS.md`. 6 h chunks resumed from ckpt_latest; GPU wait (GPU_LOCK free, no other trainer or
llama-server, < 800 MiB used) then GPU_LOCK held; heat pause >= 92 C / resume <= 88 C; Windows RAM pause < 400 MB / resume
>= 500 MB; chunk start needs 800 MB and 8 GB disk; start-adapter md5 recorded and checked on every start (exit 10 if it changed);
3 failed chunks in a row -> stop. Data paths: `paths_r4.sh` resolves `data/final/` by pattern (train_new*, replay*, dev*inc*,
dev*chat*, test*inc*, test*chat*, tools*.json; else tools_r3.json); any can be pinned in `run_r4.env`.

`supervisor_r4.sh` (new; the running `2026-11-06_4b_local/supervisor.sh` is untouched): every 10 min restarts training if it
died unfinished (not after a data/start-adapter refusal; waits until the r4 data exist and were not written in the last 30 min,
so it starts by itself when the data agent finishes), launches/relaunches `post/post_r4.sh` after training, keepalives, alerts
(Traceback, OOM STOP, GPU >= 92 C 30 min, RAM < 400 MB 30 min), max 6 restarts / 24 h each, writes `AUTO_STATUS_r4.md`.

## Post chain (`post/post_r4.sh`, `post/gate_r4.sh`, `post/gate_score_r4.py`, `post/run_think.py`)

wait (train.done / early stop, nothing training) -> pick (best.json top; if empty: **FAIL, nothing exported**) -> export via
the r3 `export_4b.sh` to `Code/models_stage/rsn_v3_4b_r4_q4_0.gguf` (+ md5; refuses any name containing r3 and any existing
GGUF it did not make) -> STRICT gate -> `post/gate_r4/GATE_r4.md` + gate.json.

**Gate rule (all three, else FAIL and r3-2800 stays):**
- (a) r4 held-out cross-domain test: r4 (adaptive think) vs r3-2800 (think off, its trained mode; also run now) on the same items.
  Combined = mean of parts present (incidents: item score = mean of severity, label, check_recall, check_prec, req of a parsed
  report, 0 if unparsed; chat: verify pass). r4 must be higher by >= 1 item-equivalent and no part worse beyond noise (paired
  z < -1.96). Runs first; a FAIL here ends the gate early.
- (b) the 19 existing checks (RWH, RWH-2, round-1 dev x 6 metrics; chat dev v3 pass rate) >= r3-2800 within 1 item each
  (r3-2800 = its cached gate_r3 results, same items, strict JSON).
- (c) chat_test_r3 per fog (r3-2800: online 0.841, offline 0.692, timeout 0.522): not lower beyond noise (paired over the same
  983 records: a drop counts only if >= 1 item and z < -1.96).
- Incident suites for r4 run with `enable_thinking=true` (= app `reasoner_think=adaptive`), reasoning moved out of the content
  before scoring as the app does; `GATE_THINK=0` runs them thinking-off instead.

## App change (Code/smart-city-edge-agent/app/backend)

`reasoner_v3.go`: `splitReportThink`; `checkReportV3For` strips a leading `<think>...</think>` before the JSON (a `{` inside the
reasoning cannot be taken as the report); profile key `reasoner_think=adaptive` (or `SCE_REASONER_THINK`) opens the think
block in the report prompt, keeps a tool round's reasoning in the next prompt (HF template), closes the block empty before a
forced answer, and closes an unfinished reasoning then forces the answer; htpd's forced-token schema is switched off in that mode
(it starts at the JSON). `ReportCall.Think` (json `think`) keeps the reasoning for the UI/log. Default (key unset):
prompts byte-identical, outputs without think unchanged. Tests `reasoner_v3_think_test.go` (5 tests) + `go test ./...` ok
(`test/go_test.txt`; one earlier full run failed once on an unrelated flaky test, the rerun passed).

## Commands

```
# start (training + supervisor + post + gate, all unattended); safe to run twice
powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-12_topup_r4\train\start_r4.ps1
# status
type C:\Users\hp\Desktop\qidk\proofs\2026-11-12_topup_r4\train\AUTO_STATUS_r4.md
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train/ctl_r4.sh status
# clean stop (supervisor first, then training; -Post also stops the post chain / gate)
powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-12_topup_r4\train\stop_r4.ps1
# CPU tests (no GPU)
wsl bash -c "cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train/test && CUDA_VISIBLE_DEVICES= ~/venvs/rsn/bin/python cpu_test.py cpu_test.json"
```
Before starting: the other GPU job must be finished (the chunk waits for an idle GPU anyway); the r4 data in `data/final/`.

## ETA (from the r3 run on the same laptop: ~83 s per 16-row step at ~750 tok/s; a 160-item gen eval took 75-86 min)

- Plan: 15k new rows / 8 per step = ~1,875 steps = ~43 h of steps + ~19 gen evals of 200 items (~1.7 h each) = ~3 days if it
  runs to the end. Early stop (3 evals without a better eligible score) usually ends it earlier; first useful checkpoint at step 100
  (~4 h incl. the step-0 eval). Lever if needed: `--gen-every 200` in run_r4.env (halves eval time).
- Post: export ~10 min; gate ~6-7 h ((a) 400 + 400 test items for both models ~3.5 h, 19 checks ~1.5 h, chat_test_r3 ~1 h).
