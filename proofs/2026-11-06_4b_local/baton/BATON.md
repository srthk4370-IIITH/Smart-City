# Baton: one 4B r3 training run that moves between Kaggle and the laptop

One Qwen3.5-4B QLoRA run (dataset r3, `train_rsn3.py`) is trained on Kaggle while the weekly GPU quota lasts, on the laptop
RTX 4050 when the quota is used up, and back on Kaggle after the quota refresh. Only one side trains at a time. The checkpoint
("lineage") moves as a whole, so the result is the same run as one that was never interrupted. Adapters are never averaged.

## What travels (the lineage)

| file | why |
|---|---|
| `ckpt_latest/` (adapter fp32, `state.pt` = optimizer + scheduler + GradScaler + step + CPU RNG) | resume point |
| `ckpt_best_XXXX/` (best-K by the gen dev score), `ckpt_epoch1/`, `ckpt_final/` | results (`SHIP_BEST=0` keeps best-K at home) |
| `schedule.json` + step | data cursor: the fixed 16-row groups of every optimizer step |
| `best.json`, `status.json`, `plan.json`, `maxlen.json` | early-stop / best-K bookkeeping, max_len |
| `train.log`, `losses.jsonl`, `dev.jsonl`, `gen_eval.jsonl` | one continuous log |
| `tokfp.json` | fingerprint of the token caches (both sides must encode every row the same) |
| `baton_scaler_kaggle.pt` | the last fp16 GradScaler state (a laptop save drops it; the next Kaggle session gets it back) |
| `recipe.json`, `BATON_HISTORY.jsonl` | the Kaggle flags; who trained which steps |

`lineage.tar` holds these files plus `MD5SUMS`; `lineage.tar.md5` sits next to it. Every hop checks the tar md5, then every
file's md5, then `state.pt` step == the step recorded in `baton/BATON`. Token caches (`*_tok.pt`) do not travel: each side
builds its own with the trainer's `prep()`, and `tokfp.json` must match.

## Why a step means the same on both sides

- **Batch:** `--accum 16` = 16 rows per optimizer step for any number of GPUs. On T4 x2, rank r trains rows `group[r::2]`
  of the same group. The LoRA gradients are summed in one all-reduce, so the step equals single-GPU accumulation of the
  16 rows. Loss scaling is `/accum` on both sides.
- **Order:** `schedule.json` is built once (seeded shuffle) and travels with the lineage. Step N trains `groups[N]` everywhere.
- **Recipe:** the same trainer file (md5-checked on Kaggle), data (md5-checked), max_len, r/alpha, LR plan, gen-eval and
  best-K/patience settings, `--shared-prefix`.
  - Since 2026-11-07 the exact memory levers `--ckpt-offload --mlp-chunk N [--mlp-chunk-min --offload-min]` also run on
    Kaggle (see "Kaggle OOM fix" below).
  - Only `--head-cpu --lean-host --model-dir --step-log` are laptop-only and dropped. FIT.md shows the levers are exact.
  - Unknown flags stop the handover (`baton_util.py recipe`).
- **dtype:** a T4 has no fast bf16, so Kaggle runs fp16 compute + GradScaler (`--dtype fp16`). The laptop runs bf16 without a
  scaler. On both sides the LoRA weights and AdamW8bit masters are fp32, so the optimizer state is the same object.
  Checked: `baton_util.py loadtest` loads a real laptop `state.pt` into the Kaggle code path and back. Every optimizer
  tensor (uint8 8-bit states + fp32 absmax/qmap) is bit-identical; scheduler `last_epoch`, step and RNG agree. The base on
  Kaggle is the same HF snapshot (`SHA256SUMS` of the laptop copy), quantized to NF4 on load (the laptop loads its
  pre-quantized NF4 copy of the same weights).
- **Not bit-identical (and never was, even laptop-to-laptop):** CUDA RNG (dropout masks) is not saved by the trainer, and
  fp16 vs bf16 arithmetic differs in rounding. The gen-eval score that picks best-K is measured in the dtype of the side
  that ran it. If the laptop held the last fp16 session's scaler, Kaggle restores it. Otherwise the first Kaggle session
  starts a fresh GradScaler, which can skip a few steps while it calibrates (logged as `scale`).

## 2026-11-07: Kaggle OOM fix, live-version check, skipped steps

**Kaggle OOM (seq 1, steps 511 -> 979, T4 x2 fp16, ~640 tok/s).** 102 of 468 steps were skipped with "OOM in a
shared-prefix batch". The recipe had dropped all laptop fit flags, so Kaggle ran `--shared-prefix` without offload or MLP
chunking. Under fp16 it also upcasts the continuation attention to fp32 on sm_75. The laptop, with the same
`--shared-prefix` plus `--ckpt-offload --mlp-chunk 512 --head-cpu`, had none of these OOMs.

Fixes:
1. **Recipe:** Kaggle now keeps `--ckpt-offload` and `--mlp-chunk 512` (exact). With them a step's working set is the
   laptop's, which fits its 4.95 GiB, plus:
   - the lm_head on the GPU (1.2 GiB; `--head-cpu` stays laptop-only for speed);
   - the fp32 attention upcast: per row, q plus the GQA-repeated K/V over at most 7424 positions, under 0.3 GiB at a time.

   That is about 6.5 GiB against 15 GiB per T4. Each rank runs its own 8 rows. Offload uses a bounded pinned host pool per
   rank; Kaggle has about 30 GB RAM. `--shared-prefix-cont` stays at the laptop's 2048.
2. **Trainer** (`train_rsn3.py`, only under `--shared-prefix`, so the 2B default is unchanged): on a shared-prefix OOM the
   rank clears its own partial gradients of that step and re-runs its rows one row per forward (the per-row path: same
   loss, no batching).
   - This is safe because the other rank's gradients are untouched: they are only summed at the all-reduce.
   - **`--oom-stop`** (new trainer flag; the kernel always adds it, so Kaggle can never skip a step): a `--micro-tokens`
     batch that OOMs is retried the same way, and if a row OOMs even alone, the trainer saves `ckpt_latest` at the state
     before that step (no rank has stepped) and exits **7** (`OOM STOP at step N`). The kernel maps torchrun's rc 1 back to
     7, does not retry on 1 GPU, packs the lineage, and the laptop resumes at that very step with its own levers. Without
     the flag (2B, laptop) a one-row OOM still skips the step, as before.
   - Retries are logged as `OOM in a shared-prefix batch at step N (rank r): retrying ...`.
   - The laptop picks this up at its next chunk start.
3. **Kaggle rc:** torchrun reports the trainer's normal exit 3 (session hours used) as 1. The kernel now recovers the real
   code from the last train.log line.

**Stale baton (seq 2 aborted at once).** `kaggle datasets status` says `ready` while the *previous* version is still
served. `to_kaggle.sh` now downloads just `baton_cfg.json` of the live version (`kaggle datasets download -f`, `.zip`
handled). It pushes only when that file is this upload: same seq **and** a random per-upload nonce. Without the nonce, a re-upload of
the same seq after a failed push would have matched the older upload of that seq. Polled every 30 s for up to 30 min,
otherwise exit 22 and the laptop keeps the baton. The kernel also checks seq + nonce before it trains.

**Owner decision (2026-11-07):** the Kaggle seq-1 segment (steps 511 -> 979) is **discarded**. The lineage was restored to
step 511 on the laptop; `BATON` says so. Seq-1 proof is kept:
- `~/smartcity_runs/baton_r3/dl/seq1/` (session log, result);
- `baton/skipped_steps_seq1_discarded.json`: 103 skipped steps, 1,648 rows. That is step 4 from the laptop plus 102 Kaggle
  steps from 521 to 977.

**The current lineage has 1 skipped step: step 4** (laptop, OOM in a micro-batch, 16 rows, before the baton existed). The
gate should note it. No replay of skipped rows is planned. From now on a shared-prefix OOM retries the rows instead of
skipping them, and `from_kaggle.sh` prints the running skipped total after every pull.

## Kaggle speed (2026-11-07): where seq 1's 11 h went, and what changed

The seq-1 session ran 39,558 s with 468 steps, 102 of them skipped. Row tokens per step average 62.1 k. Where the time went:

| part | seconds | share | note |
|---|---:|---:|---|
| pip + base download + sha256 | ~150 | 0.4 % | Python 3.13, image **torch 2.11.0+cu130** (the laptop has 2.6.0+cu124) |
| causal_conv1d build | 36 (failed) | - | CUDA 13 torch vs the image's nvcc: build failed, so the **torch reference conv ran all session** (transformers warning) |
| tokenization (tokprep, CPU) | ~970 | 2.5 % | 268 M tokens, every session |
| torchrun + model load + resume | ~70 | 0.2 % | |
| first 4 steps (Triton compile / fla autotune) | ~680 | 1.7 % | vs ~80 s for a normal step |
| dev evals (steps 600, 800) | ~400 | 1.0 % | 240 rows each |
| gen eval (step 800) | ~1,410 | 3.6 % | 40 incident + 60 chat + train slices, generation |
| checkpoint saves (every 25 steps) | small | <0.5 % | |
| training steps | ~35,800 | 90 % | ~77 s/step; **22 % of the steps OOMed and were thrown away** |

Useful throughput was 366 steps x 62.1 k / 39,558 s = **575 tok/s per session** (640 tok/s in the step logs). Two T4s in
fp16 have roughly the tensor throughput of the laptop's RTX 4050, so ~1x the laptop is expected. **fla was active** (no
fallback warning); in transformers 5.20 `torch_chunk_gated_delta_rule` dispatches to fla.

**Per-rank prefix sharing:** with 2 GPUs each rank got `group[r::2]` (8 rows), so both ranks ran the chat header (r3
mean 4,579 tokens) and the incident prompt (1,319) whenever their 8 rows held both kinds. On the real r3 schedule (steps
511-810, token caches memory-mapped, `test/rank_balance_eval.py`), the slower rank's mean per step was:

| setup | layer tokens per step |
|---|---:|
| 1 GPU, shared prefix | 22,585 |
| 2 GPUs, strided split | 14,755 (only 1.53x the 1-GPU speed) |
| 2 GPUs, cluster-balanced split | **12,509** (1.81x) |

The balanced split is **18 % less work for the slower rank** per step.

Changes (training rows, order and loss unchanged; zero skipped steps stays the hard rule):
1. **No more dropped steps:**
   - Kaggle keeps the exact memory levers `--ckpt-offload --mlp-chunk 512`, applied only to forwards longer than 4096
     tokens (`--mlp-chunk-min 4096 --offload-min 4096`, exact): this covers the chat prefixes and long rows, where the peak is.
   - A shared-prefix OOM retries the rank's rows one per forward (trainer).
2. **`--sp-rank-balance`** (new trainer flag, Kaggle with 2 GPUs only):
   - Whole prefix clusters may go to one rank, with a k / n-k split of a cluster allowed, choosing the assignment with
     the smallest maximum per-rank cost. Ties keep the strided split.
   - The step's 16 rows and per-row loss / accum are the same, so the summed gradient is identical up to float summation
     order.
   - It is deterministic, so every rank computes the same split. Tested: every row exactly once, order-independent, never
     costlier than strided.
3. **Token caches as a private dataset** `rsn3-r3-cache`:
   - The laptop's `*_seg_tok.pt` files (~2.2 GB) are uploaded once and re-versioned only when they change.
   - Kaggle uses them only if they match the lineage's `tokfp.json`, otherwise it tokenizes as before. Saves ~16 min per
     session.
4. **Triton cache carried between sessions:**
   - `triton_cache.tar` goes into the output, then to `~/smartcity_runs/baton_r3/kcache/`, then into the next baton upload.
   - `TRITON_CACHE_AUTOTUNING=1`. This should remove most of the ~10 min first-step compile/autotune.
5. **causal_conv1d:**
   - The build now targets sm_75 only (`TORCH_CUDA_ARCH_LIST=7.5`, forced build), keeps its log
     (`causal_conv1d_build.log`), prints `nvcc --version`, and caches the wheel under a torch/python tag.
   - The log line `causal_conv1d kernel ACTIVE|MISSING` and `KAGGLE_RESULT.json` show the outcome.
   - If it still fails (CUDA 13 torch vs nvcc 12), `KAGGLE_PIN_TORCH=1` in `baton.conf` makes Kaggle install the laptop's
     torch 2.6.0+cu124 first. It is off by default because fla on T4 has only run under the image's Triton.
6. **Kaggle rc:** torchrun's 1 is mapped back to the trainer's exit code. `KAGGLE_RESULT.json` now records the setup,
   package and token-cache seconds.

Not changed:
- Eval cadence (dev every 200, gen every 400; best-K must mean the same on both sides).
- The fp16 continuation-attention upcast (numerics).
- Checkpoint cadence.

**Seq-1 setup check (2026-11-07, from `dl/seq1/baton_kaggle.log`):** inputs + md5 0.4 min, pip 0.8 min, causal_conv1d
build 0.6 min (failed), base download 0.75 min + sha256 0.5 min, tokprep 16.2 min, cursor + torchrun + load 1.2 min,
first 4 steps 11.3 min, then ~82 s per step (incl. evals). Not cached, on purpose: the base model (1.25 min a session,
a 9 GB upload) and the pip wheels (<1 min). The kernel now pins `RSN3_GEN_TOK_BUDGET=24000` (the value seq 1's gen eval
ran with on a T4; the laptop's 8400 is a 6 GB limit). A stale baton cannot be waited out inside the kernel: Kaggle mounts
the dataset version once at session start and the kernel has no token, so it still aborts (exit 34) and the
`to_kaggle.sh` live check (seq + nonce of the downloaded `baton_cfg.json`) is what prevents it.

**Expected:** about **68-75 s/step** (rank balance -15 %, no OOM waste, levers only on long forwards +3-5 %), so about
**830-910 tok/s** in the step logs. Setup drops from ~21 + 10 min to ~5-10 min. That is about **520-570 trained steps per
11.3 h session vs 366 in seq 1 (+45-55 %)**. If causal_conv1d becomes active, a few % more. Not measured: these need a real
session.

## Files

| file | role |
|---|---|
| `baton.conf` | slugs, accelerator, budgets, poll/retry. No secrets |
| `lib.sh` | shared: token check (existence + chmod 600 only), BATON file, pack/unpack, secret scan, data staging |
| `to_kaggle.sh` | laptop -> Kaggle (below) |
| `from_kaggle.sh` | Kaggle -> laptop (below) |
| `baton_auto.sh` | the unattended loop |
| `start_auto.ps1` | Windows launcher: the loop (detach.sh) + hidden keepalive wsl.exe |
| `kaggle/rsn3_r3_baton.py` | the Kaggle script kernel (seq filled in at push) |
| `baton_util.py` | CPU helpers: step/info, scaler sidecar, tokfp, cursor check, recipe, kunpack/kpack (Kaggle side), loadtest |
| `BATON` | current holder (`laptop`, `kaggle` or `conflict`), step, seq, md5 of state.pt, time; `HISTORY.log` = every change |
| `logs/` | Kaggle session logs + `KAGGLE_RESULT.json` per seq (proof) |
| `test/` | offline tests: `run_tests.sh`, fake `kaggle` CLI (`kaggle_shim.sh`, `fake_session.sh`), `fake_ctl.sh`, `selftest_tree.py`, `results.log` |

Kaggle side (all private): dataset `rsn3-r3-data` = `r3_data.tar` (the training/dev/gen rows of `data/final`, md5-verified
against `MD5SUMS`; plus the gen-eval tool tree and stores in the repo layout; no test sets) + `R3_DATA_OK`. It is
re-versioned only when its md5 list changes. Dataset `rsn3-r3-baton` = `lineage.tar` + `baton_cfg.json` + `train_rsn3.py` +
`baton_util.py` [+ the cached `causal_conv1d` wheel], new version at every handover. Script kernel `rsn3-r3-baton-train`
runs on GPU T4 x2 with Internet on.

## Flows

**to_kaggle.sh** (exit 0 pushed, 10 no token/CLI, 11 wrong holder / no checkpoint, 12 laptop still running, 20 quota,
21 push error, 22 upload error, 23 verification failed). Steps in order:
1. token + CLI + holder must be laptop.
2. `kaggle quota -v`: less than `MIN_KAGGLE_H` (2 h) left -> exit 20 and the **laptop is not touched**.
   Session budget = min(11.3 h, left - 0.3 h).
3. r3 `data/final` `md5sum -c MD5SUMS` (+ pinned md5 of `gen_inc_r2.jsonl`), then stage the data tree. The tree
   self-test (`selftest_tree.py`) checks that the staged tree alone verifies the gen-eval gold exactly like the repo.
4. `ctl_4b.sh stop` (clean checkpoint), wait; refuse if the trainer is still alive.
5. Cursor check (scheduled ids exist in the data, best dirs present), tokfp, recipe, then `lineage.tar` + md5.
6. Secret scan of everything uploaded: no `kaggle.json`/`access_token`/`.env*`/`htpd_profile*`/`website_final.sh`/keys/
   gguf/sqlite-wal, no key-like text, no board serials.
7. Upload: data dataset (only if changed), then the baton dataset. Wait until Kaggle reports them `ready`.
8. `kaggle kernels push --accelerator NvidiaTeslaT4 -t <budget+0.5 h>`, then `BATON holder=kaggle` and
   `<run>/BATON_AT_KAGGLE` written.

**Kaggle session** (`rsn3_r3_baton.py`): it checks that `baton_cfg.seq` is the seq baked into the kernel. A stale dataset
version means abort, nothing trained. It then checks the data md5s and trainer md5, runs `kunpack` (tar md5, file md5s,
scaler sidecar, step), installs the pinned packages + `causal_conv1d` (checked against the reference), and downloads the
base (sha256-checked). `tokprep` builds the caches with the trainer's `prep()`, then `tokfp-check` and the cursor check
run. Training uses `torchrun` on 2 GPUs (1 GPU if 2 fail before any progress) and `--hours` = budget - setup - 0.35 h, so
the trainer saves `ckpt_latest` and exits 3 before the 12 h limit. Finally `kpack` writes `lineage.tar` + `.md5` +
`LINEAGE.json` + `KAGGLE_RESULT.json` to `/kaggle/working`.

**from_kaggle.sh** (`--once` = one status check; exit 0 installed, 30 running, 32 nothing usable (holder -> laptop),
33 conflict, 34 kernel aborted before training (holder -> laptop), 35 download failed (retry)):
1. Poll `kaggle kernels status` until complete/error/cancel.
2. `kaggle kernels output`. Session log + result are copied to `baton/logs/`; the wheel is cached.
3. Unpack + md5 check (a raw `run/` dir is accepted if the session was cut before packing). The checkpoint must load
   and its step must be greater than the baton step.
4. **Conflict check:** the laptop checkpoint must still be at the handover step and no trainer may be running. Otherwise
   holder=conflict and nothing is installed.
5. Install: the replaced lineage files move to `<run>.prev_step<N>` (one backup, deleted at the next successful install).
   The new files move in; token caches and laptop `ckpt_step*` snapshots stay. Then cursor/best check (rolled back on
   failure), tokfp check, `BATON holder=laptop`.

**baton_auto.sh** loop:
- holder=kaggle: `from_kaggle.sh --once` every 10 min. The laptop GPU stays free.
- holder=laptop: if the token is present and no back-off is active, run `to_kaggle.sh`.
  - On quota (exit 20) the next try is the later of the quota refresh time (`kaggle quota` refreshAt) and now + `RETRY_H`.
  - Otherwise the laptop trains (`ctl_4b.sh start` when it is not running).
- Ends on `baton/STOP`, on training finished (`status.json` stopped after_epoch1/early_stop, or `chain/train.done`), or on
  a conflict. Status lines: `[baton]` in `proofs/2026-10-29_rsn_v3/kaggle/STATUS.md`.

**Quota detection:**
1. `kaggle quota -v` (CLI 2.2.4: `GPU,<used>h,<remaining>h,<total>h,<refreshAt>`) before every push.
2. The push output (`Kernel push error: ...` matching quota/exceeded/accelerator unavailable).
3. A kernel `Failure message` with the same words (written to `work/quota_hit`).
If the quota runs out *inside* a session despite the budget (Kaggle counts more than our estimate), the session may be
killed. Then from_kaggle installs the raw `run/` dir if Kaggle saved it; otherwise the laptop keeps its own lineage
(nothing lost but that session).

## Commands (WSL; from Git Bash put `export MSYS_NO_PATHCONV=1` first)

```
B=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/baton
powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\baton\start_auto.ps1   # start the loop + keepalive (log ~/detached/baton_r3.log)
wsl touch $B/STOP                                                                     # stop the loop (rm it before relaunching)
wsl bash $B/to_kaggle.sh            # manual handover laptop -> Kaggle   (--fresh: no laptop checkpoint yet)
wsl bash $B/from_kaggle.sh --once   # manual check / pull
wsl cat $B/BATON                    # who holds the baton
wsl bash $B/test/run_tests.sh       # offline tests (CPU, fake kaggle CLI)
```

Run either the loop or the manual scripts, not both at once. While `BATON` says `holder=kaggle`, do not use
`ctl_4b.sh start` / `start.ps1` for the 4B. If you do, from_kaggle detects it as a conflict and installs nothing.

## Owner: one-time steps

State on 2026-11-06:
- The credential is `~/.kaggle/access_token` (new token format, chmod 600).
- The installed CLI (`~/venvs/kaggle/bin/kaggle` 2.2.4) uses it: `kaggle config view` shows `username: srthk4370`,
  `auth_method: ACCESS_TOKEN` and never prints the token.
- `kaggle quota -v` showed GPU 32.83 h used, **0.00 h left, refresh 2026-11-07T00:00:00 (UTC)**. The laptop trains
  until then.

The scripts accept `~/.kaggle/access_token` or the legacy `~/.kaggle/kaggle.json`. They only test that the file exists and
is chmod 600: they never read, print or upload it, and the secret scan blocks both names.

1. Kaggle account: **Settings -> Phone verification** done. Without it there is no GPU and no Internet in kernels.
2. Nothing else is needed for the token. To replace it: create a new token at kaggle.com/settings/api, save it as
   `~/.kaggle/access_token`, then `chmod 600 ~/.kaggle/access_token`.
3. Optional: `KAGGLE_USER=srthk4370` in `baton.conf` (otherwise the username line of `kaggle config view` is used).
4. No notebook settings to click: the kernel metadata sets private, GPU (`--accelerator NvidiaTeslaT4` = T4 x2),
   Internet on, and both private datasets.
5. After the first real push, open kaggle.com -> Code -> `rsn3-r3-baton-train` -> the running version -> Logs. Check that
   `nvidia-smi` lists 2 x T4. If it shows a P100 or 1 GPU, it still trains, more slowly; tell the agent.
6. Start the loop **from Windows** with `start_auto.ps1`. It runs `detach.sh` plus a hidden keepalive `wsl.exe`
   (`proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh baton_r3 720`). `.wslconfig` `instanceIdleTimeout=15 s` would
   otherwise shut WSL down, and kill the loop, as soon as no wsl.exe is open. The keepalive ends when the loop ends
   (or after 720 h).

## Failure modes

| symptom | what happens / what to do |
|---|---|
| `waiting for token` in STATUS.md | no `~/.kaggle/access_token` / `kaggle.json`, or not chmod 600; the laptop keeps training |
| quota used up | laptop trains; Kaggle retried at the refresh time. Nothing to do |
| push error (not quota) | laptop trains; retried after `RETRY_H` (4 h). See `~/smartcity_runs/baton_r3/logs/push.log` |
| upload error | holder stays laptop. The loop restarts the laptop and retries after `RETRY_H` |
| `stale baton` abort | Kaggle mounted an older dataset version. Exit 34, nothing trained, next try pushes again |
| Kaggle rc 7 `OOM STOP` | a row OOMed even alone on a T4: nothing skipped; the lineage up to that step comes home, the laptop trains on. Tell the agent if it repeats |
| `token caches differ` abort | tokenizer/package drift on Kaggle. Nothing trained. Tell the agent (pins in the kernel script) |
| session cut before packing | from_kaggle installs the raw `run/` dir after the load + step checks |
| session failed before training | exit 32, laptop continues from its own (unchanged) lineage |
| **Conflict** (holder=conflict) | the laptop trained while Kaggle held the baton. Nothing was installed. The Kaggle lineage stays in `~/smartcity_runs/baton_r3/new_seq<N>`. Choose ONE: keep the laptop's (`sed -i 's/^holder=.*/holder=laptop/;s/^step=.*/step=<laptop step>/' baton/BATON`) or install Kaggle's by hand. Never merge |
| bad install | cursor/best check fails -> automatic rollback to the previous lineage |
| need the previous lineage | `~/smartcity_runs/rsn3_4b_r3.prev_step<N>` holds the files replaced by the last install |

Not tested yet (needs a real Kaggle session, at the earliest after the 2026-11-07 00:00 UTC quota refresh):
- push, dataset processing time and the kernel mounting the new dataset version;
- T4 x2 fp16 with this trainer version and `--micro-tokens 7424` / max_len 7424 on 16 GB (the 2026-10-29 Kaggle runs used
  max_len 6144 without micro-batches);
- the quota error text inside a session;
- output download size and time (~0.4 GB per hop to Kaggle with ckpt_latest only, ~1.2 GB with 3 best-K; the 4B adapter
  is 260 MB fp32).

Measured offline: `kaggle quota -v` and `config view` on the real account.
