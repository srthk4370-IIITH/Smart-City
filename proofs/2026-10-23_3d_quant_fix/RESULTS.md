# 3d vs v2: is the board gap caused by quantisation? (2026-10-23, laptop only, no adb)

## Verdict

**No, quantisation is not the cause, and no GGUF fix is needed.**

- **Q4_0 costs nothing.** On the host, Q4_0 gives exactly the Q8_0 result for both models (3d 181 = 181, v2 182 = 182 of 208).
- **3d is not better than v2.** At near-full precision, 3d is 181/208 and v2 is 182/208 (2 wins, 3 losses, McNemar p = 1.0).
  The top-up gain seen in training (teacher-forced, nf4 base) does not show up in greedy decoding.
- **The board gap is an NPU runtime artefact.** 7 of 3d's 8 lost rows are garbage answers, found in 3 batches as
  runs of neighbouring stream slots. All of them fell in the part of the board run where thermal pacing was off,
  because adb's temperature read returned -1. The board went down right after that run.
  - The same deployed 3d Q4_0 answers all of these rows correctly on the host.
  - In the thermally paced part of the run, 3d = v2 (172 vs 171 of 184).
- **The merge is correct, and the deployed GGUF is its faithful product.** Details in section 1.

**Recommendation.** Keep v2 deployed. There is no better 3d or v2 GGUF to build: Q8_0 is the upper bound for any
mixed-precision or imatrix fix, and it equals Q4_0. If the owner still wants 3d judged on the board, re-run the
**existing** file with thermal pacing that works (plan in section 5). Expect 3d ≈ v2 within ±1–3 rows.

## 1. Merge and GGUF verification (all tensors)

| check | result | file |
|---|---|---|
| merge_lowmem.py (3d step 50) vs installed PEFT 0.13.2 (PeftModel + set_peft_model_state_dict + merge_and_unload), layer by layer | **255/255 tensors bit-identical** (196 LoRA modules merged, others = base, lm_head = embed) | merge_verify/v2t3d_vs_peft.json |
| merge_lowmem.py (v2 adapter) vs merge_v2.py's full PEFT merge (agents_v2/merged_v2) | **255/255 bit-identical** | merge_verify/v2_lowmem_vs_merge_v2.json |
| f16 GGUF (convert_hf_to_gguf) vs merged bf16, with the Q/K RoPE permutation | **255/255 equal** (rope_freqs is generated) | merge_verify/gguf_f16_vs_merged.json |
| Re-quantised Q4_0 (same imatrix and types) vs the deployed ft_v2t3d_q4_0.gguf (md5 e9088e11…) | 254/256 tensors byte-identical. 2 ffn_down tensors differ in 2 bytes each (1.4e-7 of the bytes, a rounding tie-break). Metadata differs only in general.name and the imatrix path, so the md5 differs. | merge_verify/repro_vs_deployed_q4_0.json |
| Weight change 3d vs v2 | median relative change per tensor 0.13 % (max 0.28 %), about 100 times smaller than Q4_0 rounding noise | merge_verify/gguf_f16_vs_merged.json |

## 2. Host greedy eval on the weak-slice subset (208 rows)

**Subset.** All host400 rows with age 1.5 h, age 3 h or family compound (148 rows), plus 60 other rows: 30 early
and 30 stratified (`scripts/make_subset.py` → `post_diag/eval_set.json`).

**Setup.**
- Backend: `host_eval_v2.py` gguf, i.e. llama-server, CPU build of llama.cpp 620d222 (the htpd base commit).
- 4 threads, 2 slots.
- Same prompt, `{"pattern": "` prefill, greedy decoding, the app's stop at `"action"`, and `common_v2.score_one`,
  exactly as `eval_htpd_v2.py` does.
- Tokenisation equals htpd's (checked at the start of each run).

**Q8_0 stands in for f16.** f16 (7.2 GB) does not fit the shared 8 GB WSL. Q8_0 agrees with the 2026-10-20 HF bf16 run
on all 37 overlapping rows (pattern, status and cause identical): see `bf16_crosscheck.txt`.

| model | json | pattern weak148 | 1.5 h | 3 h | compound | other60 | pattern ALL | status | cause |
|---|---|---|---|---|---|---|---|---|---|
| v2 Q8_0 | 208/208 | 129/148 (.872) | 57/64 (.891) | 54/63 (.857) | 31/36 (.861) | 53/60 | **182/208 (.875)** | .827 | .822 |
| v2 Q4_0 (deployed) | 208/208 | 128/148 (.865) | 57/64 (.891) | 53/63 (.841) | 31/36 (.861) | 54/60 | **182/208 (.875)** | .837 | .812 |
| 3d Q8_0 | 208/208 | 126/148 (.851) | 55/64 (.859) | 54/63 (.857) | 28/36 (.778) | 55/60 | **181/208 (.870)** | .832 | .817 |
| 3d Q4_0 (deployed) | 208/208 | 126/148 (.851) | 55/64 (.859) | 53/63 (.841) | 29/36 (.806) | 55/60 | **181/208 (.870)** | .832 | .832 |
| BOARD v2 (app A/B 10-23) | 208/208 | 128/148 (.865) | 57/64 (.891) | 53/63 (.841) | 31/36 (.861) | 54/60 | 182/208 (.875) | .837 | .817 |
| BOARD 3d (app A/B 10-23) | 201/208 | 119/148 (.804) | 51/64 (.797) | 51/63 (.810) | 26/36 (.722) | 55/60 | 174/208 (.837) | .798 | .808 |

| paired (pattern) | cand wins | cand losses | McNemar p | same (pattern, status, cause) |
|---|---|---|---|---|
| v2 Q8_0 → 3d Q8_0 (training effect) | 2 | 3 | 1.0 | 196/208 |
| v2 Q4_0 → 3d Q4_0 | 1 | 2 | 1.0 | 198/208 |
| v2 Q8_0 → v2 Q4_0 (quantisation loss, v2) | 1 | 1 | 1.0 | 202/208 |
| 3d Q8_0 → 3d Q4_0 (quantisation loss, 3d) | 1 | 1 | 1.0 | 202/208 |
| BOARD v2 → host v2 Q4_0 (proxy fidelity) | 0 | 0 | 1.0 | **207/208** |
| BOARD 3d → host 3d Q4_0 (proxy fidelity) | 7 | 0 | 0.016 | 201/208 (the 7 = board garbage rows) |
| BOARD v2 → BOARD 3d | 1 | 9 | 0.02 | 192/208 |

**Reading.**
- Quantisation loss is zero, net, for both models.
- 3d ≈ v2 on the host, slightly lower on the weak slices (126 vs 129 at Q8_0), which is noise.
- The host Q4_0 run reproduces the board almost exactly (v2: 207/208 identical decisions).
- The only host-vs-board difference for 3d is the set of rows the board turned into garbage.

## 3. Why the board run of 3d looked worse: a batching / NPU artefact (`board_failures.json`)

| board run | invalid answers | batches (stream slots) | rows without thermal pacing |
|---|---|---|---|
| v2 10-20 | 3 | b43 (slots 3, 4, 5) | 0 |
| v2t (topup phase 1) 10-21 | 4 | b9 (7), b12 (2, 3, 4) | 0 |
| v2 10-21 k8 | 0 | – | 0 |
| v2 app A/B 10-23 | 1 | b12 (4) | 0 |
| **3d app A/B 10-23** | **8** | **b29 (2, 3, 4), b47 (0, 1, 2), b48 (4, 5)** | **216 of 400 (from batch 23 on, adb temp = -1)** |

**The failures look like a runtime fault, not a weak model.**
- They are garbage, not plausible wrong answers: for example `"spurship" , "statuscode 1MuhriF`,
  `gradual-climmyclclclc` and `-cla-cla-cla…`.
- They come in runs of neighbouring streams of one batch. The handbook (2.42) describes the same signature:
  "runs of neighbouring streams … points to the batch, not the model".

**All 8 sit in the unpaced part of the run.**
- `eval_htpd_v2.py` waits only when `board_c() >= hot`. When adb fails, `board_c()` returns -1, so batches kept
  running on a hot board. The run started at 75 °C, just after chaos had reached 93.8 °C.
- `app_ab.log` shows "adb: no devices" right after this host400, and the board needed a reboot (resume_3d.sh).

**Split by pacing state:**
- Paced rows (n = 184): v2 171, 3d 172, no invalid answers.
- Unpaced rows (n = 216): v2 179, 3d 169, with all 8 invalid answers.
- Without the garbage rows, 3d vs v2 on all 400 board rows is 3 wins and 4 losses.

**The eval bypasses the app's safeguard.** It sends batches straight to htpd (port 8091). In the app,
`solo_rerun=runaway` re-runs such answers alone (reason.go), so most of them would be recovered there.

**The same artefact may have hit the phase-1 top-up.** It was "rejected on the device" (host400 .877 → .855),
and that run also had 4 invalid batched answers. That rejection may have been partly this artefact too.

## 4. Quantisation fixes: built? No. They cannot help on this evidence.

Q8_0 for every linear layer is the upper bound of anything below it:
- a domain imatrix,
- attn_v / ffn_down / edge layers at Q8_0,
- re-quantising ffn_down.

That bound equals Q4_0: 181 = 181 for 3d and 182 = 182 for v2. So no candidate can beat the deployed files on these
slices, for 3d or for v2. I stopped before spending about 4 h of laptop CPU on candidates. "q4exact" (pack_exact_gguf)
repacks Genie device weights and does not apply to a llama.cpp-quantised LoRA merge.

What was prepared, in case it is wanted later (scripts in `scripts/`):
- **Domain calibration.** `make_calib_domain.py`; output in `~/smartcity_runs/agents_v2_topup3d/post/gguf_fix/calib/`.
  - 256 chunks × 1280 tokens, every chunk starting at a real agent prompt's BOS (verified).
  - Rows: 3d top-up TRAIN split, with stage 1.5 h / 3 h / early rows and compound rows boosted to 40 %.
  - All roles and window buckets present (manifest: `calib_domain_manifest.json`).
  - The deployed imatrix used 64 × 1024 chunks that cut across prompts.
- `step3_imatrix.sh` and `step3_quant.sh` build the variants: `dimx`, `dimx_v8_d8`, `dimx_v8_edge8`.

**Hexagon support at 620d222 (the htpd base).** `ggml_hexagon_is_repack_type` includes Q8_0 (and Q4_0, Q4_1,
Q4_K, Q5_K, Q6_K, IQ4_NL, MXFP4); every shape here is a multiple of 32. So Q8_0 for sensitive tensors would run on
HMX. Cost estimate if ever needed:

| change | added size | added decode weight bytes |
|---|---|---|
| attn_v → Q8_0 | +44 MB | +1.6 % |
| all ffn_down → Q8_0 | +352 MB (2.80 → 3.15 GB) | about +13 % |

Decode is bandwidth-bound, so latency would rise by roughly the same share.

## 5. Board test plan (optional; for the owner to run)

**No new file is needed.** Re-test the existing 3d file:
`~/smartcity_runs/agents_v2_topup3d/post/gguf/ft_v2t3d_q4_0.gguf`, md5 `e9088e111cf85a036a3119e864ab6305`.

1. **Fix pacing first.** In `training/v2/post/device_eval_v2/eval_htpd_v2.py`:
   - treat `board_c() < 0` as hot: wait and retry the read, or abort, instead of proceeding;
   - also log the temperature after each batch.

   Without this, the A/B is not valid.
2. **Check the file on the board.** With the app stopped, run
   `md5sum /data/local/tmp/gpu/ft_v2t3d_q4_0.gguf`; it must be `e9088e11…`.
3. **Push only if the md5 differs.**
   - Stop the app and htpd, and wait until they have exited.
   - `adb push` to `ft_v2t3d_q4_0.gguf.part`.
   - Run `md5sum` on the board; it must match.
   - `mv` the `.part` file into place.
4. **Switch the app to 3d** (as `app_ab.sh switch`):
   - add `model=/data/local/tmp/gpu/ft_v2t3d_q4_0.gguf` to `htpd_profile`;
   - `rm state/htpd_args`;
   - launch, and confirm that `htpd_v7`'s cmdline shows the file.
5. **Cool the board to below 50 °C**, then run the app's htpd evals:
   - `eval_htpd_v2.py --set host400 --port 8091`;
   - `placement_v2.py run/analyze` on placement_s24.

   Then switch back to v2 the same way, and run v2 in the same session under the same pacing.
6. **Score.**
   - Paired against `proofs/2026-10-23_3d_quant_fix/post_diag/eval/3d_q4_0_deployed` (expect ≥ 201/208 identical).
   - Against board v2.
   - Count invalid answers per batch and slot with `scripts/board_failures.py`.
   - Judge 3d on the valid rows, and through the app with `solo_rerun` on.

## Files

| what | where |
|---|---|
| diagnosis subset | `post_diag/eval_set.json` |
| per-row host outputs | `post_diag/eval/{v2_q8_0, v2_q4_0_deployed, 3d_q8_0, 3d_q4_0_deployed}/samples.jsonl` (+ summary, tables, server.log, tokenize_check) |
| tables | `tables.md`, `tables.json` |
| all board runs and pairwise agreement | `board_runs.json` |
| failure slots | `board_failures.json` |
| merge, GGUF and repro checks | `merge_verify/` |
| md5 and tensor types of all GGUFs | `gguf_manifest.json` |
| scripts | `scripts/` |

**WSL artefacts.**
- `~/smartcity_runs/agents_v2_topup3d/post/gguf_fix/` holds the manifest, the logs and the calibration text.
- The large intermediates were deleted after use: merged bf16, f16 GGUF and the Q8_0 files, md5s recorded.
  They are listed in `INTERMEDIATES_DELETED.txt`.
