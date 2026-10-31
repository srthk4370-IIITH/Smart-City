# rsn_v3: time model and the fastest hybrid plan (laptop + Kaggle)

## Model
Work items: chat distillation (decode tokens `S`), training (tokens `D`), evaluation `E_v`, board check `B`.

Machines: laptop GPU (RTX 4050 6 GB, available 24/7) and Kaggle (2×T4, sessions ≤ 11.3 h, quota `Q` = 30 GPU-h per
week). Progress is an ODE per job:

    dW_train/dt = r_k · u_k(t)            u_k(t) ∈ {0,1},  ∫ u_k dt ≤ Q per week
    dW_dist/dt  = r_d,l · u_l(t) + r_d,k · u_kd(t)        (u_kd uses the same Kaggle quota)
    finish time T = min { t : W_train(t) = D, W_dist(t_d) = S, t ≥ t_d (chat rows needed) }

Measured or estimated rates:
- Laptop training: 290 tok/s (round 1, r16, 4-bit, with flash-linear-attention) but **out of memory for r32 and for
  4-6k-token chat rows** (round 1 log: r32 OOM at 2,055 tokens) → `u_l` can never be training. The laptop does
  distillation, data building and evaluation only.
- Kaggle training `r_k`: round 2 measured 200 tok/s on ONE T4 without flash-linear-attention (torch fallback for the
  Gated-DeltaNet layers). rsn_v3 adds: 2 GPUs (×~1.8), flash-linear-attention (×1.3-2, smoke-tested in the notebook),
  fp16 LoRA without 4-bit quantisation if it fits (×~1.3, also removes the NF4 quantisation error). Range 400-800 tok/s.
- Distillation on the laptop with llama.cpp CUDA (Q8_0 teacher, prompt cache): the 2.8k-token tool header is ~85% of
  every chat prompt and is cached, so a sample costs ~0.3 s prefill + ~150 decode tokens at ~40-60 tok/s per slot,
  4 slots → `S` = 8,000 × 4 samples × ~150 = 4.8 M tokens ≈ 8-12 h, **zero Kaggle quota**.
  (Kaggle HF-generate distillation without a prefix cache: 10-13 h of quota.)

## What drives T
Kaggle quota is the bottleneck, so T ≈ D / r_k (in GPU-h, converted to weeks at 30 h/week) + the non-overlapped
laptop work. Minimising T therefore means:
1. **Maximise r_k:** two GPUs, flash-linear-attention, fp16 no-quant LoRA if session 1's probe shows it fits and is faster.
2. **Minimise D without losing accuracy:** curriculum instead of uniform epochs. Epoch 1 = all rows
   (incidents 12k × ~2.4k ≈ 29 M + chat 7.2k × ~3.7k ≈ 27 M = 56 M tokens). Epoch 2 = only the rows that carry the
   errors: weak/hard incident families (~40%) + hard chat kinds (~42%) ≈ 23 M. D ≈ 79 M instead of 112 M for 2 uniform
   epochs (-30%), with the hard cases still seen twice.
3. **Take distillation off the critical path and off the quota:** the laptop distils chat while Kaggle session 1
   trains the incident part of epoch 1 (incidents need no distillation). Chat rows join from session 2.
4. **Early stop:** checkpoints every 25 steps; the gate runs on the laptop at the end of epoch 1. If it already passes
   (RWH strict, dev within noise), epoch 2 is skipped.

## Numbers (D = 79 M)
| r_k (tok/s) | Kaggle GPU-h | sessions | quota weeks |
|---|---|---|---|
| 400 | 55 | 5 | ~1.8 |
| 600 | 37 | 4 | ~1.2 |
| 800 | 27 | 3 | ~0.9 |
Plus: data build 0.2 h, laptop distillation 8-12 h (overlapped with session 1), import + Q4 0.5 h, gate eval ~3 h on the
laptop, board A/B + deploy ~1 h.
Epoch-1-only result (if the gate already passes): 56 M → 19-39 GPU-h (2-4 sessions).

## Plan
1. Laptop now: make_data (incidents ~12k incl. chatter ×3, chat3), bundle A (incidents + scripts) for Kaggle.
2. Kaggle session 1: probe (2-GPU, fla, fp16 vs 4-bit → pick fastest that fits), then train epoch-1 incident rows.
3. Laptop in parallel: distil chat (llama.cpp, prompt cache) → verify → bundle B (distilled chat) → owner adds it
   as a second Kaggle dataset.
4. Kaggle sessions 2+: the rest of epoch 1 (chat + incidents mixed), then the gate on the laptop from a checkpoint,
   then epoch 2 (hard rows) only if needed.
5. Laptop: import → Q4_0 → gate (RWH strict, dev within 1 item) → board lab A/B → deploy with rollback.

## Measured update (2026-10-30, rsn_v3 Kaggle agent)
- Laptop 4B r32 probe (NF4 pre-quantized, bf16, flash-linear-attention, micro-batch 1, logits at loss positions only): 3.14 GiB
  resident after load. **It runs out of memory at 6,144, 5,120, 4,096 and 3,072 tokens** (CUDA driver OOM in the backward pass). The
  laptop cannot train the 4B at chat lengths, so there are **no 4B hand-offs**: the 4B trains on Kaggle only, and the laptop trains
  the **2B** (owner decision). Its fit and speed are probed at the start of `laptop_train.sh` (6,144 / 5,120 / 4,096) and saved in
  `~/smartcity_runs/rsn3_2b_r1/maxlen.json`.
- Loss positions only: `train_rsn3.loss_fn` runs lm_head only on label positions in chunks of 128. On 4 rows it equals the
  full-logits loss within 1.4e-6.
- Data: incidents 20,000 rows (compact targets: 11,031 rows shortened, 5.9% fewer target tokens on those rows, 467 -> 440);
  RWH-2 has 150 held-out rows; chat 8,000 questions (distilled on the laptop -> bundle B); replay ~1,000 rows (bundle B).
- Order: Kaggle session 1 = probe + the incident part of epoch 1 (bundle A). The laptop finishes distillation, then replay and
  bundle B, then trains the 2B (laptop_chain.sh). Kaggle sessions 2+ run with bundle B attached. Both candidates are gated; compare
  mode picks the more accurate one, and the 2B only if the two are tied within noise.
