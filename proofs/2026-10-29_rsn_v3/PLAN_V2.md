# rsn_v3 plan v2: laptop + Kaggle, a stronger reasoner, no overtraining (2026-10-30)

Compute: laptop RTX 4050 24/7 (~250-290 tok/s training once logits are computed only at loss positions; distillation
and evaluation between training turns) + Kaggle 2×T4 (~30 GPU-h/week, ~400-800 tok/s). One training run handed
between the two (adapter + optimizer + data cursor), never averaged.

Principle: spend extra compute on **more varied, verified data and error-driven correction**, not on more passes
over the same rows. Every stage is gated on held-out sets the model never trains on; the best checkpoint by dev
score is kept, not the last.

## Data (bigger, more varied, all synthetic + verified)
- Incidents: ~20k rows (round 1: 5.6k), new seeds, all families incl. chatter ×3 and rsn_v1's weak families ×3,
  `+tool` / `+inject` variants, round-1 real_pool rows at the round-1 share. verify.py pass only.
- Chat: 8k questions × up to 2 verified distilled answers (≈12-14k rows), 54 kinds, 40% multi-turn, adaptive think.
- Replay: ~1k general prompts answered by the base model (keeps general language; round 1 had 515).
- **New held-out set RWH-2** (~150 incidents, new seed, families balanced) + chat dev v3 (300): never trained on,
  used to measure generalisation together with RWH (150) and dev (120).

## Stages
1. **SFT epoch 1** (all rows, ~95 M tokens): Kaggle session 1 starts on incidents while the laptop distils chat;
   then laptop/Kaggle hand-offs. Fast dev eval every N steps (40 incident + 40 chat rows), keep best-3 checkpoints.
2. **Gate A** (laptop): RWH + RWH-2 + dev + chat dev on the best checkpoint vs rsn_v1.
3. **Error-driven repair round** (STaR-style, Zelikman et al. 2022): generate a fresh pool (3k incidents + 2k chat,
   new seeds, not RWH/RWH-2/dev), run the best checkpoint on it, verify every output, turn the failures into
   corrected training rows (gold report / verified chat answer) plus the hardest rows of the weak families; continue
   training on repair rows + an equal amount of replayed epoch-1 rows (prevents drift) for a short phase (~15 M tokens).
4. **Preference step (optional, only if Gate B shows a remaining confusion)**: DPO (Rafailov et al. 2023) on ~2k pairs
   (verified-correct vs the model's own wrong output, e.g. sensor_fault vs normal, unknown vs normal) with a small β,
   LoRA on the laptop, logits at loss positions only.
5. **Gate B**: same sets; ship only if RWH strict ≥ rsn_v1 on every report metric, dev within 1 item, RWH-2 ≥ rsn_v1,
   chat dev pass rate up; then board lab A/B → deploy with rollback.

## Overtraining controls
- Early stopping on the dev score (not loss alone), patience 3 evaluations; best-of-K checkpoints.
- Train/dev gap monitored (train-slice vs dev-slice generation accuracy); a growing gap stops the phase.
- Repair phase mixes in replay rows 1:1; LR lower (5e-5) for continuation; LoRA dropout 0.05, weight decay 0.01.
- Generalisation check on RWH-2 (unseen seed) and per-family breakdown: a family that improves on train but not on
  RWH-2 is a memorisation signal.
- No training on RWH, RWH-2, dev, chat dev, P0 or any real board data.

## Timeline (estimate; refined by the session-1 probe)
| step | where | time |
|---|---|---|
| data build (incidents 20k, RWH-2, replay) | laptop CPU | ~1 h |
| chat distillation | laptop GPU | ~8-12 h (parallel with Kaggle session 1) |
| SFT epoch 1 (~95 M tok) | Kaggle + laptop | ~2-3 days |
| gate A | laptop | ~3 h |
| repair pool run + rows | laptop | ~6 h |
| repair phase (~15 M tok) | laptop/Kaggle | ~0.5-1 day |
| DPO (if needed) | laptop | ~0.5 day |
| gate B + board A/B + deploy | laptop + QIDK | ~4 h |
Total ≈ 4-6 days wall, Kaggle quota ≈ 1-1.5 weeks used.

## Stages 3-4: scripts (run by hand, never by laptop_chain.sh)
Only when a gate fails. Both run on the laptop under WSL via `proofs/detach.sh`, wait for GPU_LOCK, are resumable (rerun the same
command), stop cleanly on `kaggle/<repair|dpo>/<run>/STOP` or `kaggle/chain/STOP`, and log to `kaggle/STATUS.md`. All their rows are
synthetic (no real_agent rows, no held-out prompt or id; checked by `repair_lib.py check`), so they may go into a Kaggle bundle.
- **Gate A FAIL** -> stage 3: `RUN_ID=rp1 GATE=<gate run id> CKPT=<candidate adapter dir> bash proofs/detach.sh repair_rp1
  .../kaggle/local/repair_pool.sh`. Fresh pools (3k incidents + 2k chat, new seeds, weighted by the gate's per-family / per-kind
  failure rates) -> candidate GGUF on them -> failures become gold incident rows + base-teacher self-distilled, verified chat rows
  (distill_llama.py + select_distill.py) + hardest weak-family rows -> 1:1 token replay of epoch-1 rows (<= 15 M tokens) ->
  cont_train.py SFT (LR 5e-5, best-3 by dev score, patience 3) -> Q4_0 -> gate B (`kaggle/gate/gB_rp1`). `UNTIL=check` builds only
  the data.
- **Gate B FAIL with a remaining label / severity confusion** -> stage 4: `RUN_ID=dp1 GATE=gB_rp1 REPAIR=rp1 bash proofs/detach.sh
  dpo_dp1 .../kaggle/local/dpo.sh`. On-policy pairs from a fresh pool (chosen = verified gold / verified chat answer, rejected = the
  model's own wrong output; gate confusions first; plus the repair pool's failures), ~2k pairs, DPO beta 0.1, LR 5e-6, reference =
  starting adapter -> Q4_0 -> gate (`kaggle/gate/gD_dp1`). It refuses to run when the gate shows no confusion (FORCE=1 overrides).
- A passing gate B / D candidate goes through `chain.sh compare` and the owner-approved board A/B as before.
Files: `kaggle/local/{repair_pool.sh, dpo.sh, repair_common.sh, repair_lib.py, cont_train.py, cont_chunk.sh}` (usage in each header).

## r2 add-on: heatwave pairs (2026-11-01, owner-approved; not in r1)
Board problem (HANDBOOK 2.67, INC-0577/0579): a weather-only critical heat incident was reported as sensor_fault. In r1's
20k incident rows there is no weather-only incident and no weather sensor fault, and an agent's sensor_fault claim is turned into
critical only 6 of 2,203 times. `pipeline/gen_heat_r2.py` (seed 2611, synthetic only) writes `data/heat_r2/{train,dev}.jsonl`:
120 contrastive pairs. In each pair, real heat (smooth diurnal ramp; humidity falls, cooling load and AC rise; critical or warning,
label weather_driven, first action monitor/review_schedule) sits next to a stuck, offset-jump, night-drift or spiking outdoor
sensor (sensor_fault). The agent is wrong in about 45 % of rows. Split: train 192 / dev 48, by pair. Every row passes round-1
verify.py and the app's Go gate (`pipeline/heat_r2_go_check.sh`: 240/240; see `data/heat_r2/manifest.json`).
To include it in the next bundle, run `RUN_ID=r2x bash detach.sh mkdata_r2x .../local/make_data.sh` as usual, then
`python3 -B proofs/2026-10-29_rsn_v3/pipeline/gen_heat_r2.py --mix-into proofs/2026-10-29_rsn_v3/kaggle/build/r2x/data` before
`make_bundle.sh`. This step appends the 192 train rows to `incidents3_train.jsonl` at deterministic positions, re-verifies them
and refreshes manifest.json/MD5SUMS. It refuses a second mix. The bundle allowlist needs no change.
Keep `dev.jsonl` out of training: add it to `--gen-inc` or the gate as an extra slice. Gate check: heat dev rows must come out
weather_driven critical or warning, and fault rows sensor_fault. The 192 rows are ~1 % of the incident rows; if the slice fails,
repeat them ×3 (DPO pairs are also possible: chosen = gold, rejected = the swapped label).
