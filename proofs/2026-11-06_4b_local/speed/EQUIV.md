# Speed levers for the 4B QLoRA run: equivalence on CPU (2026-11-06)

Trainer: `proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py`. Every new flag is off by default, so the live run and Kaggle runs
behave as before unless a flag is passed. Checkpoint format is unchanged (adapter, optimizer, scheduler, step, schedule.json
cursor, RNG).

## Flags

| flag | what it does | exact? |
|---|---|---|
| `--offload-min N` | `--ckpt-offload` only for forwards over N tokens; shorter forwards use the plain non-reentrant checkpoint (input stays on the GPU) | yes: same recompute |
| `--mlp-chunk-min N` | (existed, unmeasured) `--mlp-chunk` only for forwards over N tokens | yes, up to fp32 summation order |
| `--shared-prefix` | rows of one step that start with the same tokens run that prefix once (details below) | up to float rounding; dropout caveat below |
| `--shared-prefix-min N` (256) | shortest common prefix worth sharing | - |
| `--shared-prefix-cont N` (2048) | padded continuation tokens per forward (also capped at `--micro-tokens` minus the prefix) | - |
| `--step-log` | one line per optimizer step to `steps.jsonl` (seconds, row tokens, tok/s, loss, peak alloc/reserved VRAM); used by `ab.sh` | no numeric effect |

### --shared-prefix: how it works

1. **Clustering.** The step's rows (the same 16 rows from schedule.json) are sorted by token sequence. Neighbours sharing at least
   `--shared-prefix-min` tokens are clustered; prefix length p is their longest common prefix, capped so every row keeps at least
   one own token. Rows that fit no cluster run exactly as before (`micro_batches` + `loss_fn_batch`).
   - Real data: chat rows share p ≈ 4637 tokens (21-tool header 4579 + the common start of the system message).
   - Incident rows share p = 1319 tokens (system prompt + incident tools).
2. **Prefix pass.** The prefix runs once with its autograd graph kept. Each layer returns its end state:
   - full-attention layers: K/V after k_norm + RoPE;
   - Gated-DeltaNet layers: the last K-1 = 3 conv inputs plus the recurrent state, via the same `causal_conv1d_fn` /
     `chunk_gated_delta_rule` (fla) that transformers resolved.
   - It also returns the final-norm hidden states, which the loss on label tokens inside the prefix uses.
   - Checkpointing is the same as the baseline: non-reentrant per layer, or the pinned-pool offload above `--offload-min`
     (`_OffloadCkptN`); `--mlp-chunk` is honoured.
3. **Continuation passes.** Continuations run from that state in right-padded batches at positions p.. (lower-right causal
   attention over prefix + own keys; conv over [prefix tail ; own tokens]; the GDN initial state is the prefix state).
   - Per row, the loss is the baseline's: sum CE over all its label tokens (prefix positions use the prefix hidden states) / n.
   - Each continuation batch calls backward(sum(row loss / n) / accum) through the scaler, as before.
4. **Prefix gradient.** Gradients reaching the prefix outputs are summed in fp32 (`_Tap`). Then ONE backward runs through the
   prefix with that sum.

## Equivalence tests (CPU, fp32 unless stated)

**Setup**
- Model: a tiny random Qwen3.5 built from the real 4B `text_config`: 4 layers (GDN, attention, GDN, attention), hidden 64,
  GQA 4/2 heads, partial mRoPE, gated attention output, GDN with 2 key / 4 value heads.
- LoRA: r32 / alpha 64 on all 12 trainer targets (60 LoRA tensors), lora_B randomised so every gradient is non-trivial.
  Dropout 0.
- Kernels: torch fallbacks (fla and causal_conv1d need a GPU).
- Rows: real r3 rows tokenised by the trainer's own `encode` (`pretok.py`; ids remapped to a compact vocabulary, so sequences,
  prefixes and label positions are identical).
- Baseline: the trainer's current step body (`micro_batches` + `loss_fn_batch`, `--micro-tokens 7424`).
- Compared: summed row loss, and every LoRA gradient (worst-tensor max abs, worst-tensor max abs / max |g|, global rel-L2).

**Raw data**
- `eq_thresholds.json`, `eq_shared_part1.log` (eq_shared.py, first 10 cases), `eq_tail.json`, `eq_bf16diag.log`.
- Scripts: `eqlib.py`, `eq_*.py`, `run_eq.sh`, `go.sh`; watchdog `watch_eq.ps1` (kills the test if Windows available RAM drops
  below the floor).

### Item 2: thresholds (eq_thresholds.json, 5 incident + 3 chat rows)

| config vs live (offload + mlp-chunk 512, min 0) | loss diff | grad rel-L2 | max abs |
|---|---|---|---|
| offload-min 4096, mlp-chunk-min 4096 | 0 | 0 | 0 |
| offload-min 6000, mlp-chunk-min 3000 | 9e-7 (abs) | 1.5e-7 | 2.9e-9 |
| thresholds above every forward | 0 | 9.8e-8 | 1.9e-9 |
| no levers (HF checkpoint only) | 0 | 9.8e-8 | 1.9e-9 |

With `--micro-tokens 7424` nearly every real forward is 4.5k-7.4k padded tokens, so the thresholds rarely trigger in the live
config. They matter once `--shared-prefix` makes continuation forwards short (2-3k tokens).

### Item 1: shared prefix (baseline vs --shared-prefix)

| case | clusters (p, rows) | loss rel diff | grad rel-L2 | max abs | worst-tensor rel | CPU s base / new |
|---|---|---|---|---|---|---|
| chat group, 4 rows | (4637, 4) | 0 | 2.4e-7 | 2.3e-9 | 7.0e-5 | 35.1 / 10.0 |
| incident group, 5 rows | (1319, 5) | 1.5e-8 | 1.7e-7 | 1.9e-9 | 3.6e-5 | 14.2 / 8.9 |
| mixed step, 5 inc + 4 chat | (4637, 4), (1319, 5) | 8.2e-9 | 1.9e-7 | 3.3e-9 | 5.6e-5 | 47.6 / 16.8 |
| mixed, continuation batch 1500 tokens | same | 8.2e-9 | 2.0e-7 | 4.7e-9 | 5.7e-5 | 49.3 / 19.7 |
| single-row group (falls back to baseline) | (0, 1) | 0 | 0 | 0 | 0 | - |
| prefix contains labels (1 incident row + 4 different tails; one row with prefix labels masked) | (2474, 4) | 0 | 2.0e-7 | 1.2e-9 | 5.6e-5 | 13.9 / 10.4 |
| `--micro-tokens 0` (one row per forward) | (4637, 3), (1319, 3) | 0 | 2.3e-7 | 2.8e-9 | 5.7e-5 | 32.8 / 14.2 |
| one row split at token 3000 (k = 1) | - | 0 | 3.0e-7 | 1.2e-9 | 4.4e-5 | - |
| with offload (CPU stub) + mlp-chunk 512 | - | 1.0e-8 | 2.1e-7 | 2.3e-9 | 7.4e-5 | - |
| with offload-min / mlp-chunk-min 3000 | - | 1.0e-8 | 2.1e-7 | 2.3e-9 | 7.3e-5 | - |
| `--head-cpu` stand-in (row-gather embed, CE on selected rows) + offload + mlp-chunk; 20 layer forwards went through `_OffloadCkptN` | - | ~0 | 1.8e-7 | 3.7e-9 | 4.3e-3 | - |
| **fp32 yardstick**: baseline micro-batched vs baseline one row per forward | - | 0 | 8.9e-8 | 1.9e-9 | 5.1e-4 | - |
| fp32: baseline vs shared, same rows | - | 1e-16 | 1.8e-7 | 3.7e-9 | 4.3e-3 | - |

- The worst-tensor relative numbers come from near-zero tensors (in_proj_a/b). They have the same order as the baseline's own
  batching noise in that tensor.
- The global rel-L2 of 2e-7 is at the fp32 rounding level, about 2x the baseline-vs-baseline floor.
- The loss and its normalisation are exact: same rows, sum CE over each row's label tokens / n, / accum, labels inside the
  prefix included.
- The CPU speed-up in the table is the tiny model, where the share of prefix tokens is the same as on the real model.

### bf16 (eq_tail.json, eq_bf16diag.log)

| case | grad rel-L2 | loss rel diff |
|---|---|---|
| bf16 yardstick: baseline micro-batched vs one row per forward | 2.4e-5 | 3e-16 |
| bf16 baseline vs shared, GDN + attention model | **2.5e-3** | 3e-6 |
| bf16 baseline vs shared, GDN-only model | 3.2e-5 | 1e-16 |

- The bf16 gap comes only from the continuation attention. The GDN state carry is at noise level, and fp32 is exact.
- On CPU, the continuation's lower-right causal SDPA (q at positions p.., keys 0..p+C) can only use the math backend, which
  computes in bf16. The baseline's `is_causal` SDPA uses the fused CPU kernel with fp32 accumulation.
- On the GPU, torch 2.6 sends `causal_lower_right` to the flash kernel or, for head_dim 256 backward on sm_89, to the
  mem-efficient kernel. Both accumulate in fp32 like the baseline's kernel, so the gap is expected to be CPU-only.
- This is to be confirmed by the GPU A/B: per-step loss of B vs A. Applied since: the continuation attention is upcast to fp32 off CUDA (CPU tests) and for fp16 (Kaggle T4, no flash on sm_75). The laptop bf16 CUDA path is unchanged.

## Not exact: LoRA dropout

With LoRA dropout 0.05, the baseline draws an independent dropout mask for every row's copy of the prefix. Shared prefix draws
ONE mask for the prefix, used by all rows of the cluster. The expected gradient is unchanged and each row's marginal noise is
the same. The noise of the prefix contribution is correlated across the rows of a step. This is the only change in what is
trained, apart from rounding.

## Pending checks (run at a stop; need about 1.2 GB host RAM, about 20 min of CPU, no GPU)

The CPU tables above ran on the code before these later changes:
- per-row continuation attention;
- `.clone()` of the GDN conv tail;
- `--shared-prefix-cont` 2048 cap;
- prefix hidden-state tap only when there are prefix labels;
- fp32 upcast of the continuation attention off CUDA and on fp16.

Each change is either identical math or a pure memory change. Still to run with the final code:
1. `eq_shared.py`: all fp32 cases.
2. `eq_tail.py`: the head-cpu stand-in, plus the fp32 and bf16 yardsticks. bf16 should now match the baseline at noise level
   thanks to the CPU upcast.
3. `resume_test.py`: the real `main()` on CPU (tiny model dir, 24 real rows, accum 8, dropout 0).
   - A: baseline for 3 steps.
   - B: shared for 2 steps, then resume as baseline to step 3.
   - C: the reverse of B.
   - D: shared for 3 steps.
   - Adapters, AdamW states and the scheduler are compared with A.

Command (from Windows, live trainer stopped or Windows available RAM >= 1500 MB):
```
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/go_chain.sh
& C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\speed\watch_eq.ps1 -Min 1500
```
- Output: `eq_shared.json`, `eq_tail.json`, `resume_test.json`; `chain_eq.done` is written at the end.
- The watchdog kills only this process group (`kill_eq.sh`).

## Memory (real config: 4B, bf16, 7424, --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host)

First GPU attempt (`ab_spthr.txt`, B = `--shared-prefix --offload-min 4096 --mlp-chunk-min 4096`, old code): OOM at the first
shared batch. Causes:
- Continuations of up to 2787 tokens (cap was micro_tokens - prefix) fell under the 4096 thresholds, so there was no offload
  and no MLP chunking: about 0.45 GiB of layer inputs stayed on the GPU, plus the unchunked MLP recompute.
- The continuation attention materialised GQA-repeated prefix K/V for all rows of the batch at once: 3 rows x 16 heads x
  5.6k x 256 x bf16, with gradients about 1.1 GB.
- About 0.5 GiB of prefix state was held on top of that.

Fixes (now in the trainer):
1. The continuation attention runs one row at a time (identical math), so only one row's repeated K/V exists: about 0.09 GiB
   with gradients.
2. `--shared-prefix-cont` defaults to **2048** padded continuation tokens per forward (still capped at micro_tokens - prefix).
   A row longer than the cap runs alone.
3. The fp32 gradient sums are freed one by one while the prefix backward is set up.
4. The prefix hidden-state tap (and its fp32 sum) is created only when a row has labels inside the prefix. r3 chat and incident
   rows have none.
5. Recommended: keep `--offload-min 0 --mlp-chunk-min 0` (the live values) with `--shared-prefix`. Thresholds above the
   continuation size (at most 2048) remove the offload exactly where the prefix state already takes VRAM.

Estimate. Baseline: peak alloc 4.41 GiB at a 7.2k-token forward; fixed part about 2.4 GiB; about 0.28 GiB per 1k forward
tokens with offload + mlp-chunk.

Held while a cluster's continuations run:
- prefix K/V bf16: 8 layers x 2 x 4637 x 1024 x 2 B = 0.14 GiB, plus fp32 sums 0.28 GiB;
- GDN recurrent states fp32: 24 x 2 MB, plus sums: about 0.1 GiB.
- Total about 0.52 GiB.

| phase | estimate |
|---|---|
| continuation batch (2048 tokens) | 2.4 + 0.52 + 0.28 x 2.05 + 0.09 (attention, one row) = about 3.6 GiB |
| prefix backward (4637 tokens; sums converted to bf16 one by one) | 2.4 + 0.15 + 0.28 x 4.64 = about 3.85 GiB |
| baseline worst row (7229 tokens) | 4.41 GiB (measured) |

Pinned host pool: prefix 3 x 32 buffers + continuation (2048 tokens) 2 x 32 buffers = 160 x 8 MiB = 1.25 GiB. This equals the
current worst case.

## Speed estimate (estimate_tokens.json; real schedule.json, 4297 steps x 16 rows)

**Method**
- A step holds 3-15 chat rows (median 8).
- Tokens through the 32 decoder layers (each costs forward + recompute + backward) per step: baseline 62.6k, shared 22.9k.
  That is **-63 % (2.7x fewer)**, using the 4579-token header only for chat (conservative) and 1319 tokens for incident.

**Unchanged costs**
- The vocab CE (label tokens only; streamed head per row) is unchanged.
- There are 2-3 more, shorter forwards per step: about 6-7 forwards instead of about 11, but less efficient per token.

**Expected wall-clock speed-up**
- About **1.8-2.4x** (about 265 -> 480-640 row-tok/s; epoch-1 ETA about 250 h -> 105-140 h busy). `ab.sh` measures it.

## GPU A/B (owner runs it; nothing was run on the GPU here)

```
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/speed/ab.sh 3                     # A = live flags, B = live + --shared-prefix
B="--shared-prefix --offload-min 3072 --mlp-chunk-min 3072" TAG=sp_thr wsl bash .../speed/ab.sh 3  # then: thresholds on the short continuations
```

**What to compare:** tok/s per step (first step excluded), peak reserved (must stay at or below about 5.2 GiB), and per-step
loss. Same rows, so B - A should be at rounding level (dropout masks differ, about 1e-3 relative).

## GPU A/B results (RTX 4050 6 GB, real 4B run, steps 44 -> 46 from the frozen step-44 copy `~/smartcity_runs/ab_base44`)

Raw data: `ab_spthr.txt` (arm A; the first B attempt OOMed), `ab_spB.txt` (B OOM: GDN conv tail kept as a view of the whole
projection, about 1.8 GB; fixed with `.clone()`), `ab_spB2.txt` + `ab_spB2_B_steps.jsonl` (B after the fix).

| step | A tok/s | A s | B tok/s | B s | speed-up | A loss | B loss | rel diff |
|---|---|---|---|---|---|---|---|---|
| 45 (warm-up) | 262 | 220.8 | 558 | 103.6 | 2.13x | 0.41781 | 0.41850 | +1.7e-3 |
| 46 | 284 | 235.6 | 840 | 79.7 | 2.96x | 0.38937 | 0.38957 | +5e-4 |

Peak VRAM: A 4.41 GiB allocated / 4.98 GiB reserved; B 4.08 / 4.69 (the ceiling is about 5.2).

A is bit-reproducible (two A runs: 0.417811681823). B draws different LoRA-dropout masks, so the loss is expected to differ
slightly. The open check is a dropout-0 A/B (`A="--lora-dropout 0" B="--shared-prefix --lora-dropout 0"`), which separates
dropout from kernel numerics.

## Dev-loss pass with --shared-prefix (staged: `speed/train_rsn3.devshared.py`)

**What changed.** `dev_eval` now calls `dev_losses()`.
- With `--shared-prefix`, dev rows that share a prefix run it once: `shared_prefix_loss` under no_grad, with no backward.
- The 240 dev_r3 rows are mostly chat, so the header is computed once per eval instead of once per row.
- Rows outside a cluster, and any cluster that OOMs, use the per-row `loss_fn` as before.
- The per-row loss sum and n are unchanged, and the DEV log line and dev.jsonl are unchanged.
- There is no new flag, so the Kaggle recipe is unchanged.

**CPU check** (`eq_dev.py` -> `eq_dev.json`). Setup: tiny model, 5 incident + 5 chat real rows, model.eval() with dropout
0.05 configured.

| dtype | max per-row loss rel diff | logged DEV metrics |
|---|---|---|
| fp32 | 1.1e-7 | identical to 4 decimals |
| bf16 | 9e-6 | identical to 4 decimals |

**Generation eval: no exact cheap win.**
- `gen_score` already batches through `chatloop.HFBackend`: left-padded micro-batches, tok_budget 24000.
- Reusing a prefilled header KV/state cache would change the prefill rounding, because the header's recurrent and attention
  states are computed in a different chunking and padding layout. That can flip greedy argmaxes, so the outputs would not be
  bit-identical.
- Not done.
