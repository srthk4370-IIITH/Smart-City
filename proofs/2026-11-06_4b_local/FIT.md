# Qwen3.5-4B QLoRA on the laptop RTX 4050 (6 GB): fit at 6144 tokens

Date 2026-11-06 (WSL clock 2026-11-05 21:30-22:40 UTC). Trainer: `proofs/2026-10-29_rsn_v3/kaggle/train_rsn3.py`.
Recipe unchanged: r32 / alpha 64, same 12 LoRA target modules, dropout 0.05, AdamW8bit, bf16, NF4 base, fla kernels,
non-reentrant checkpointing on every decoder layer, same loss (sum CE over label tokens / n, / accum). No row is truncated
or dropped (rows over --max-len are skipped by prep as before; at 6144 that is 0 rows).

## What was wrong (logs/diag_3072.log)

The CUDA context under WSL leaves only **4.95 GiB** for torch (6.00 total). At 3072 tokens, before the levers:

| item | GiB |
|---|---|
| NF4 body | 1.71 |
| tied embed_tokens = lm_head, bf16 248320 x 2560 | **1.18** |
| LoRA weights fp32 (64.9 M) + their grads | 0.24 + 0.24 |
| checkpoint boundaries (32 layers x T x 2560 bf16) | 0.48 (0.96 at 6144) |
| one layer's recompute + backward (Gated-DeltaNet layers ~0.2 more than attention layers) | ~1.2 (~2.4 at 6144) |

Forward and backward completed at 3072; the step died at the optimizer step with 5.26 GiB reserved (= the ceiling).
Checkpointing was already on every layer (each layer ran forward exactly twice). Logits were already chunked.
The 4B simply carries 1.2 GB of frozen bf16 vocab matrix plus about twice the 2B's per-layer activations.

## What changed (new flags, all default off: 2B and Kaggle runs behave exactly as before)

| flag | what | saves |
|---|---|---|
| `--head-cpu` | tied embed/lm_head weight moved to pinned CPU RAM (64 MiB pieces). Input embeddings = CPU row gather. Loss = `_StreamCE`: vocab chunks streamed to the GPU on a side stream, one pass computes the loss and dL/dh (online softmax). Generation evals move the weight back to the GPU and park it again afterwards | 1.18 GiB |
| `--ckpt-offload` | the saved input of each checkpointed layer goes to a bounded pool of pinned 32 MiB host buffers; backward brings it back, recomputes the layer with the same RNG state (dropout) | 0.96 GiB at 6144 |
| `--mlp-chunk 1024` | the MLP (token-wise) is recomputed in 1024-token checkpointed chunks inside the layer recompute. Exact; costs one extra MLP forward | ~0.6 GiB per layer at 6144 |
| `--lean-host` | labels kept as a bool mask (label == token id wherever trained; asserted per row) and malloc_trim after load. Host RAM, not VRAM | ~0.5 GB host |
| `--mlp-chunk-min N` | chunk the MLP only for forwards over N tokens (speed). **Added but not measured** (run stopped, see RAM below); default 0 = always chunk | - |

Env for the run: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2`
(the inductor pool otherwise spawns 8 compile workers, ~1.2 GB host RAM).

Numerics (logs/diag_check_head.log, diag_6144_v2_check.log: 700 rows, original 128-row checkpointed lm_head path vs streamed):
loss identical (rel diff 0 and 4.6e-6). Gradient vs an fp32 ground truth: original path rel-L2 error 6.4e-2,
streamed path 1.7e-3. The streamed gradient is the same formula but 40x closer to exact (the original rounds
softmax minus one-hot to bf16 before the 248k-wide matmul). So the gradient is not bit-identical to the 2B's; it is more accurate.

Rejected / not needed: quantizing lm_head (changes logits), smaller rank or fewer targets (not needed), paged optimizer
(states are only ~0.13 GiB), save_on_cpu (does not reach non-reentrant checkpoint inputs, which are held by reference).

## Results (one optimizer step, 2 synthetic rows of L tokens + 6 real r2 rows, accum 8; logs/run1_*, run2_*)

| max_len | OOM steps | peak allocated | peak reserved | host RSS | tok/s (real rows) |
|---|---|---|---|---|---|
| **6144** | 0 | **4.01 GiB** | 4.62 GiB | 4.8-5.2 GB | 275.6 (1 step), 255.1 (3 steps, 50 s heat pause inside) |
| 5120 | 0 | 3.71 | 4.26 | 5.1 GB | 215.6 (1 step) |
| 4096 | 0 | 3.42 | 3.97 | 5.1 GB | 271.0 (1 step) |

(tok/s differences between the single-step probes are row mix + heat, not length.)

Real-mode speed, exactly the real-run config (accum 16, `--micro-tokens 6144`, max_len 6144, first 5 steps of the r2
schedule, logs/run1_chunk_always/speed_real_train.log): **236 tok/s wall clock**, 5 steps in 991 s with 26 heat pauses
= 260 s paused (GPU >= 87 C -> SIGSTOP, resume <= 82 C), i.e. **~320 tok/s while running, 26 % pause duty**.
nvidia-smi peak 5387 / 6141 MiB. Checkpoint save works (adapter 260 MB, no embedding weights).

## Token lengths (lengths.json; all rows, Qwen3.5 tokenizer, seg tokenization, tools_r2)

2B and 4B tokenizer.json are byte-identical (md5 7b6074791b84e7ce3a5fc12746b82d48).

| file | rows | p50 | p90 | p99 | max | > 4096 | > 5120 | > 6144 |
|---|---|---|---|---|---|---|---|---|
| incidents_train | 35151 | 2402 | 2899 | 3468 | 3824 | 0 % | 0 % | 0 % |
| chat_train | 20973 | 3635 | 4021 | 4474 | 5225 | 7.01 % | 0.014 % (3 rows) | 0 % |
| all | 56124 | | | | 5225 | 2.62 % | 0.005 % | **0 %** |

Total 160.0 M tokens (86.3 M incident + 73.7 M chat). max_len 6144 keeps every row.

## Hours per epoch (no other change)

| tokens | at 320 tok/s (no pauses) | at 236 tok/s (measured, 26 % heat pause) |
|---|---|---|
| 157 M | 136 h | **185 h** |
| 200 M | 174 h | 235 h |

For comparison the 2B r2 ran at ~630 tok/s wall (ETA epoch 1 ~47 h, paused at 87 C ~every few minutes).
The 4B is ~2.7x slower per token. This is the measured cost of the 4B body, not of the levers: the levers add roughly
one extra MLP forward (mlp-chunk) plus PCIe streaming of 1.2 GB per row (head) and 2 x T x 2560 x 2 bytes per layer (offload).

## Host RAM: the next limit

The training process holds ~5.1 GB RSS in the 7 GB WSL VM (data 0.7 GB, pinned vocab 1.27 GB, pinned offload pool
1.0 GB, CUDA/torch). While it ran, **Windows available RAM fell to ~0.6 GB** (5.3 GB after it stopped), and Claude Code
reaped an idle shell for low memory. `laptop_train.sh`'s watchdog SIGSTOPs at Windows free < 1.0 GB and resumes at >= 1.1 GB,
so with the current Windows load the 4B would sit paused. Before the real run, free Windows RAM (close other apps) or
decide on that threshold; a pause frees no RAM. (Not changed here: it is a guard policy.) The first attempt without
--lean-host / compile-thread cap hit 187 MB WSL available and was aborted (logs/attempt1_ram_abort).

## Exact command for the real run (do not start from here; GPU_LOCK handled by laptop_train.sh)

```
# from Windows: wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_4b <script below>
R2D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data/final
mkdir -p ~/smartcity_runs/rsn3_4b_r2 && ln -s ~/smartcity_runs/fit4b_probe/*_seg_tok.pt ~/smartcity_runs/rsn3_4b_r2/   # token caches (skip 10 min prep)
echo '{"max_len": 6144, "probe": "proofs/2026-11-06_4b_local/FIT.md"}' > ~/smartcity_runs/rsn3_4b_r2/maxlen.json      # optional: skip the re-probe
export TORCHINDUCTOR_COMPILE_THREADS=1 MALLOC_ARENA_MAX=2
RSN3_SEG_TOKENIZE=1 RUN=rsn3_4b_r2 BASE=$HOME/models/qwen3.5-4b TOOLS=$R2D/tools_r2.json \
  INC=$R2D/incidents_train.jsonl CHAT=$R2D/chat_train.jsonl DEV=$R2D/dev_mix3.jsonl \
  GEN_INC=$R2D/gen_inc_r2.jsonl GEN_CHAT=$R2D/gen_chat_r2.jsonl \
  GEN_TRAIN_CHAT=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data/chat_gen/chat3_train.jsonl \
  EXTRA="--model-dir $HOME/models/qwen3.5-4b-nf4 --micro-tokens 6144 --head-cpu --ckpt-offload --mlp-chunk 1024 --lean-host" \
  CHUNK_H=6 bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/laptop_train.sh
```
(trainer flags as used by laptop_train: `--quant nf4 --dtype bf16 --max-len 6144 --accum 16` + EXTRA.)
laptop_train.sh now passes EXTRA to its own fit probe too (needed for the 4B; the 2B's EXTRA `--micro-tokens` is ignored in probe mode).
If a different dataset is final (this directory also holds r3 data files from another job), swap the paths; the
length table above is for r2.

Not exercised here: the dev-loss eval (streamed CE without grad) and the generation eval (`gen_hook` moves the 1.2 GB
weight back to the GPU, KV cache batch 8) on the 4B; watch the first eval at step 100/200.

## Files

- `train_rsn3.py` (kaggle/): `_StreamCE`, `HeadCPU`, `_OffloadCkpt` + pinned pool, `apply_fit_levers`, `_lab`, `host_trim`,
  flags `--head-cpu --ckpt-offload --mlp-chunk --mlp-chunk-min --lean-host`, RSS/peak-reserved in the probe result.
- `kaggle/local/laptop_train.sh`: `${EXTRA}` on the fit-probe line.
- here: `fit_diag.py`/`run_diag.sh` (VRAM by phase and layer, numerics check), `fit_probe.sh`/`fit_more.sh` (probes +
  speed, heat/RAM watchdog), `lengths.py` -> `lengths.json`, `lock.sh`, `peek.sh`, `stopjob.sh`, `logs/`.
- token caches for the real run: `~/smartcity_runs/fit4b_probe/{inc_2a1af257940e,chat_3876eaf0badb}_seg_tok.pt` (1.3 GB).

## r3 update (owner: full r3 data, no row skipped)

Exact lengths (`lengths_r3.py` -> `lengths_r3.json`): every row tokenized by `train_rsn3.prep` itself (seg tokenization,
tools_r3.json, 4B tokenizer, max_len 10^6 so nothing dropped). Caches written for the real run:
`~/smartcity_runs/fit4b_r3/{inc_2a1af257940e,chat_5fc7a153630f,dev_8758d3318efb}_seg_tok.pt`.

| file | rows kept / file | p50 | p90 | p99 | max | > 6144 | > 7168 |
|---|---|---|---|---|---|---|---|
| incidents_train | 35151 / 35151 | 2402 | 2899 | 3468 | 3824 | 0 % | 0 % |
| chat_train_r3 | 33597 / 33597 | 5547 | 5930 | 6377 | **7229** | 3.30 % (1109 rows) | 0.006 % (2 rows) |
| dev_r3 | 240 / 240 | 5473 | 5915 | 6293 | 6405 | 3.33 % | 0 % |

Epoch = 268.8 M tokens (86.3 M incident + 182.5 M chat). Max 7229, so **max_len = 7424** (29 x 256) and 0 rows skipped.

Changes for r3, still behind the same flags:
- `--lean-host` now also memory-maps the token caches (`torch.load(mmap=True)`): file-backed pages instead of anonymous RAM.
  Host RSS at 7424 is 4.07 GB (r2 at 6144: 4.8-5.2 GB).
- `--ckpt-offload` pool: pinned 8 MiB buffers. A layer input is split across ceil(T x 5120 B / 8 MiB) of them, so rows
  over 6.5k tokens no longer allocate one-off 64 MiB pinned blocks. Worst case 32 x 5 x 8 MiB = 1.25 GB.

Fit probe at 7424 (`fit_r3.sh 7424`, logs/r3_7424). First two rows of the step are the two **longest real rows**
(`--probe-len 0`: 7229 tokens with their real labels), plus 6 random real rows, accum 8.
Result: **0 OOM, peak allocated 4.32 GiB, peak reserved 4.89 GiB** (ceiling about 5.2), host RSS 4.07 GB,
**225 tok/s** on the 6 random rows (1 step, 10 s heat pause). The levers were the same as for r2; nothing had to change in the recipe.
VRAM margin is only about 0.3 GiB. If a long row OOMs in the real run, `--mlp-chunk 512` is the next lever (exact, untested).

Speed over several steps was **not measured**. Both speed runs (3 probe steps, then 5 real-mode steps) were aborted
by the watchdog at start-up because Windows available RAM was 492 MB (apps open; 1.5 GB with nothing of mine running).
To measure later, with apps closed: take GPU_LOCK, then run `NOSPEED= bash fit_r3.sh 7424`.
Rough projection from the 1-step 225 tok/s plus the r2 heat duty (26 %): 268.8 M tokens means about 330 h busy,
about 450 h wall per epoch. At the r2 real-mode busy rate (320 tok/s) it would be about 235 h busy and 315 h wall.

Real-run command: as above, with
`TOOLS=$R3/tools_r3.json INC=$R3/incidents_train.jsonl CHAT=$R3/chat_train_r3.jsonl DEV=$R3/dev_r3.jsonl` (R3 = this dir's data/final),
max_len 7424 (`echo '{"max_len": 7424}' > <run dir>/maxlen.json` or let laptop_train probe it), caches linked from
`~/smartcity_runs/fit4b_r3/`, `EXTRA="--model-dir $HOME/models/qwen3.5-4b-nf4 --micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 1024 --lean-host"`.
Note: laptop_train's own probe only tests 6144/5120/4096. It would pick 6144 and skip 1109 chat rows, so **write maxlen.json = 7424 first**.

## Real run note (2026-11-06 12:02 IST)
First real chunk (`--mlp-chunk 1024`) hit an OOM in a micro-batch at step 4 (a long real row, margin was ~0.3 GiB), then a
CUDA caching-allocator INTERNAL ASSERT in the next backward -> trainer crash (rc 1). No checkpoint existed. Restarted with
`--mlp-chunk 512` (exact, one smaller MLP recompute chunk; recipe unchanged) via run.env.

## Generation-eval OOM (2026-11-06 21:06 IST)
Step-200 gen eval crashed: batched prefill of chat prompts (tok_budget 24000 -> 3-4 x ~6k-token prompts) + the 1.2 GB vocab
matrix unparked to the GPU -> OOM surfaced as a CUDA caching-allocator INTERNAL ASSERT (not caught by chatloop's OOM retry).
Dev loss at step 200 was logged (incident 0.1097, chat 0.0394); the step-200 gen score was not. Fix: train_rsn3.py reads
RSN3_GEN_TOK_BUDGET (default 24000, Kaggle unchanged); run.env sets 8400 on the laptop (one chat prompt + max_new per batch).
