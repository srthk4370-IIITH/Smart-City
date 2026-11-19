- 2026-11-15 20:52:51 data built: {'kept_real': 34141, 'real_train': 30724, 'real_val': 3417} drops {'audit_not_visible': 2828, 'excl_overlap': 309, 'verify:ungrounded': 125, 'verify:warning_but_1h_avg_critical': 11, 'verify:rerender_error': 61, 'dup': 7059, 'verify:noise_fault_weak': 17, 'verify:rerender_mismatch': 2}
- 2026-11-15 20:52:52 GPU lock taken
- 2026-11-15 20:54:36 FAIL: pilot rc 1:     return F.linear(input, self.weight, self.bias)            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ RuntimeError: !handles_.at(i) INTERNAL ASSERT FAILED at "/pytorch/c10/cuda/CUDACachingAllocator.cpp":400, please report a bug to PyTorch.  
- 2026-11-15 20:55:01 GPU lock taken
- 2026-11-15 21:05:59 FAIL: pilot rc 143: RuntimeError: !handles_.at(i) INTERNAL ASSERT FAILED at "/pytorch/c10/cuda/CUDACachingAllocator.cpp":400, please report a bug to PyTorch.  Loading weights:   0%|          | 0/254 [00:00<?, ?it/s]Loading weights:   0%|          | 1/254 [00:01<04:17,  1.02s/it]Loading weights:   1%|          | 3/25
- 2026-11-15 21:06:24 GPU lock taken
- 2026-11-15 21:19:01 pilot: {"tok_s": 469, "tok_per_row": 1028.3667711598746, "s_per_step": 71.08749997615814, "loss_first": 0.11992, "loss_10": 0.07323, "steps": 10}
- 2026-11-15 21:19:21 GPU lock taken
- 2026-11-15 21:19:47 mix (target 6464 rows = 4 h at pilot speed): {"n_total": 6464, "real": 3230, "real_available": 30724, "replay": 3234, "val_sel": 400}
- 2026-11-15 21:40:01 refs REAL VAL: B50 {"score": 0.90721, "n": 400, "json": 1.0, "status": 0.92, "pattern": 0.89, "cause": 0.9075, "dq": 0.0} | snap_1750 {"score": 0.686, "n": 400, "json": 1.0, "status": 0.6725, "pattern": 0.6325, "cause": 0.64, "dq": 0.875} | snap_1750 syn {"score": 0.90333, "n": 120, "json": 1.0, "status": 0.9083, "pattern": 0.9, "cause": 0.8583, "dq": 0.9417}
- 2026-11-15 23:09:58 train chunk rc 3: step 0 -> 75 / 202 (461 tok/s)
- 2026-11-15 23:29:08 select s0075: {"step": 75, "val": {"score": 0.75288, "n": 400, "json": 1.0, "status": 0.7375, "pattern": 0.7025, "cause": 0.71, "dq": 0.9375}, "syn": {"score": 0.89417, "n": 120, "json": 1.0, "status": 0.8917, "pattern": 0.9, "cause": 0.8667, "dq": 0.9167}} -> {"best_step": 75, "best": 0.75288, "since_best": 0, "stop": false}
- 2026-11-16 00:58:01 train chunk rc 3: step 75 -> 150 / 202 (466 tok/s)
- 2026-11-16 01:16:46 select s0150: {"step": 150, "val": {"score": 0.7445, "n": 400, "json": 1.0, "status": 0.7325, "pattern": 0.6975, "cause": 0.6925, "dq": 0.9225}, "syn": {"score": 0.87333, "n": 120, "json": 1.0, "status": 0.8583, "pattern": 0.8917, "cause": 0.8417, "dq": 0.9083}} -> {"best_step": 75, "best": 0.75288, "since_best": 1, "stop": false}
- 2026-11-16 02:18:00 train chunk rc 0: step 150 -> 202 / 202 (469 tok/s)
- 2026-11-16 02:38:44 select s0202: {"step": 202, "val": {"score": 0.75125, "n": 400, "json": 1.0, "status": 0.7325, "pattern": 0.7225, "cause": 0.695, "dq": 0.915}, "syn": {"score": 0.89333, "n": 120, "json": 1.0, "status": 0.8833, "pattern": 0.8917, "cause": 0.875, "dq": 0.9417}} -> {"best_step": 75, "best": 0.75288, "since_best": 2, "stop": true}
- 2026-11-16 02:38:44 early stop: 2 evals without REAL VAL gain
- 2026-11-16 03:42:01 gate: # GATE_agt: agt_v3 topup snap_0075 (7fa44fd489047170eead7ec8d7e7a406) vs B50 -> **FAIL**
- 2026-11-16 03:42:01 REPORT numbers written
