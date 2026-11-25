# rsn big top-up (Qwen3.5-4B reasoner, continue p2 LoRA) status (append-only)

Plan: data = A no-regression replay + B holes + C chat/tool use + D 4500 new agent rows -> data/final_big/{train_new,replay}.jsonl (+ gate/gate_set.jsonl, tests/dev_hole_inc.jsonl);
Kaggle: private datasets rsn-big-data / rsn-big-run / rsn-big-base (+ existing rsn3-r3-data), kernel rsn-big-train; single launcher run_big.sh (waits for agent rows -> build -> audit -> launch_big.sh auto).
Throughput note: p2 on the laptop ran ~500 tok/s (about 2 min/step of 16 rows) and a gen eval cost ~2 h; Kaggle T4 (single GPU, rsn_ft_train.py asserts world 1) is expected to be similar. 12-14 h therefore
trains ~250 steps = ~2500 new + ~1500 replay rows (p2 itself trained 220 steps of a 14k-row pool, --epochs 0.43): the pool is built to the requested size, the plan takes a fraction (data/final_big/PLAN.md).

- 2026-11-20 01:06 [build A] replay block A: 6414 gold rows, stratified over every final_v2 block (v1/v2 replay, r3, r4, real-agent, campus chat, fog, unseen, taxonomy, p2 families)
- 2026-11-20 01:15 [build gate] frozen gate set gate/gate_set.jsonl (40 report + 30 new-family + 40 English chat + 20 tool-chain probes; none in training), dev_hole_inc.jsonl (20 regression + 20 hole rows for keep-best)
- 2026-11-20 01:20 [kaggle] base r3_edit_C1 (8.8 GB) uploading as private dataset srthk4370/rsn-big-base (kaggle_upload_base.sh); reuse of srthk4370/rsn3-r3-data (gen-eval tool tree)
- 2026-11-19 21:06:01 [run_big] agent rows 2683/4500 (running=1)
- 2026-11-20 02:37:38 [plan] owner: prioritised ~4k-row sample (new 2500: B30/tool27/chat8/agent35 %; replay 1500 balanced per block); pools kept in pool_*.jsonl
- 2026-11-19 21:16:01 [run_big] agent rows 2905/4500 (running=1)
- 2026-11-19 21:26:01 [run_big] agent rows 3132/4500 (running=1)
- 2026-11-19 21:36:02 [run_big] agent rows 3358/4500 (running=1)
- 2026-11-19 21:46:02 [run_big] agent rows 3581/4500 (running=1)
- 2026-11-19 21:56:02 [run_big] agent rows 3808/4500 (running=1)
- 2026-11-19 22:06:02 [run_big] agent rows 4042/4500 (running=1)
- 2026-11-19 22:16:02 [run_big] agent rows 4280/4500 (running=1)
- 2026-11-19 22:30:17 [run_big] data check rc 0: counters: {'id_dups': 0, 'rows:C': 1050, 'rows:D': 776, 'rows:B': 675, 'rows:A': 1500, 'gate_overlap_new_rows': 0, 'gate_id_in_train': 0, 'test_overlap_new_rows': 0}  RESULT: PASS 
- 2026-11-19 22:30:18 [run_big] plan: {"pool_new_rows": 2501, "pool_replay_rows": 1500, "mean_tokens_new": 4079, "mean_tokens_replay": 3217, "tokens_per_step": 60088, "assumed_tok_s": 450.0, "train_h": 9.0, "steps": 242, "epochs_fraction": 0.9676, "new_rows_seen": 2420, "replay_rows_seen": 1452, "seen_share_new_pool": 0.968, "seen_share
- 2026-11-19 22:30:26 [launch_big] FAIL: check failed: nothing pushed
- 2026-11-19 22:31:02 [after_kaggle] launch FAIL seen, no gate (see STATUS.md)
- 2026-11-19 22:40:13 [launch_big] stage ok: data id 38b86574e189d65e3a4036351212c905, big_data.bin 272 MB
- 2026-11-19 22:40:15 [launch_big] uploading rsn-big-data (private, id 38b86574e189d65e3a4036351212c905, 272 MB)
- 2026-11-19 22:42:36 [launch_big] uploading rsn-big-run seq 1 (step 0, budget 11.30 h)
- 2026-11-19 22:42:57 [launch_big] -> Kaggle: seq 1, step 0, kernel v1, budget 11.30 h (quota left 16.87 h)
- 2026-11-19 22:53:01 [launch_big] kernel seq 1 ended: kernelworkerstatus.complete
- 2026-11-19 22:53:05 [launch_big] FAIL: lineage content md5 mismatch
- 2026-11-19 23:00:03 [after_kaggle] launch FAIL seen, no gate (see STATUS.md)
- 2026-11-20 07:01:00 [launch_big] FAIL: pull the previous session first
- 2026-11-20 07:01:51 [launch_big] uploading rsn-big-run seq 1 (step 0, budget 11.30 h)
- 2026-11-20 07:02:05 [launch_big] -> Kaggle: seq 1, step 0, kernel v2, budget 11.30 h (quota left 16.80 h)
- 2026-11-20 07:10:53 [after_kaggle] launch FAIL seen, no gate (see STATUS.md)
- 2026-11-20 10:32:47 [launch_big] kernel seq 1 ended: kernelworkerstatus.complete
- 2026-11-20 10:34:10 [launch_big] <- Kaggle: seq 1 pulled, step 65, done=0 (best adapters in /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best, gate: gate/gate_big.sh <ckpt_best_NNNN>)
- 2026-11-20 10:34:20 [launch_big] uploading rsn-big-run seq 2 (step 65, budget 11.30 h)
- 2026-11-20 10:39:43 [launch_big] -> Kaggle: seq 2, step 65, kernel v3, budget 11.30 h (quota left 13.32 h)
- 2026-11-20 10:59:49 [launch_big] kernel seq 2 ended: kernelworkerstatus.complete
- 2026-11-20 11:01:12 [launch_big] <- Kaggle: seq 2 pulled, step 65, done=0 (best adapters in /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best, gate: gate/gate_big.sh <ckpt_best_NNNN>)
- 2026-11-20 11:01:21 [launch_big] uploading rsn-big-run seq 3 (step 65, budget 11.30 h)
- 2026-11-20 11:06:21 [launch_big] -> Kaggle: seq 3, step 65, kernel v4, budget 11.30 h (quota left 13.10 h)
-  [rsn_big_fix] session 3 cancelled by owner; keeping seq-2 step-65 lineage (run/lineage.bin 11:01), STATE holder=laptop; trimming rows >6000 tok then re-stage
- 2026-11-20 11:17:06 [rsn_big_fix] trimmed train_new 490 + replay 53 rows (list items not cited by answer cut), audit PASS 0 bad, orig in data/orig_pre_trim; floor: tools schema 5029 tok so <=5800 infeasible, max now train 6307 replay 6569
- 2026-11-20 11:17:10 [launch_big] stage ok: data id aff1de9c0466402bee382b444d816134, big_data.bin 271 MB
- 2026-11-20 11:17:31 [launch_big] uploading rsn-big-data (private, id aff1de9c0466402bee382b444d816134, 271 MB)
- 2026-11-20 11:20:29 [launch_big] uploading rsn-big-run seq 4 (step 65, budget 11.30 h)
- 2026-11-20 11:25:25 [launch_big] -> Kaggle: seq 4, step 65, kernel v5, budget 11.30 h (quota left 13.08 h)
- 2026-11-20 11:50:36 [rsn_big_fix] seq 4 (v5, trimmed data) pushed 11:25, still RUNNING at 11:50 (25 min, past the ~20 min point where seq 2/3 OOMed); auto loop + after_kaggle.sh running
- 2026-11-20 20:07:49 [launch_big] kernel seq 4 ended: kernelworkerstatus.complete
- 2026-11-20 20:08:57 [launch_big] <- Kaggle: seq 4 pulled, step 242, done=1 (best adapters in /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best, gate: gate/gate_big.sh <ckpt_best_NNNN>)
- 2026-11-20 20:08:57 [launch_big] plan done
- 2026-11-20 20:14:13 [after_kaggle] FAIL: no best adapter in /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best
- 2026-11-20 20:17:07 [owner] no keep-best ckpt saved (r3 0.944 < p2 0.9917-0.01 on a 24-row sample); gating ckpt_latest step 242 as best/ckpt_best_0242
- 2026-11-20 20:17:07 [rsn_big_gate] gate: export new GGUF from /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/best/ckpt_best_0242 (CPU)
- 2026-11-20 20:55:47 [rsn_big_gate] gate: p2 done in 1351 s
- 2026-11-20 21:18:22 [rsn_big_gate] gate: new done in 1355 s
- 2026-11-20 21:18:22 [rsn_big_gate] gate: GATE.md written (scores only, no auto-deploy)
- 2026-11-22 07:01:09 [rsn_big_gate] gate: export new GGUF from /home/hp_srthk4370/smartcity_runs/rsn_full/ckpt_best_0000 (CPU)
- 2026-11-22 07:02:15 [rsn_big_gate] gate: p2 done in 66 s
- 2026-11-22 07:03:13 [rsn_big_gate] gate: new done in 58 s
- 2026-11-22 07:03:13 [rsn_big_gate] gate: GATE.md written (scores only, no auto-deploy)
