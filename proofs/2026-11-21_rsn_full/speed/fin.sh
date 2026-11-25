#!/usr/bin/env bash
Q=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$Q/2026-11-21_rsn_full
cat > $D/SPEED.md <<'EOF'
# Speed test (48-row sample, accum 4 = 4 rows/step, RTX 4050 6 GB; raw in ~/speedtest/{A,B}, scripts in speed/)
| config | s/step | peak VRAM | step-1 loss | notes |
|---|---|---|---|---|
| A p2 flags (--micro-tokens 7424 --head-cpu --ckpt-offload --mlp-chunk 512 --lean-host --shared-prefix --oom-stop, offload/mlp-min 4096) | 79 (step 1, warmup) / 37 / 33 (~17k tok/step) | 5703 MiB | 0.02080 (baseline) | stable, no OOM |
| B A minus --head-cpu | n/a | 5868 MiB+ | n/a | OOM at step 0, then CUDA allocator assert (rc=1): does not fit 6 GB |
| C Liger fused CE | skipped | | | trainer already does lm_head+CE only on label rows in checkpointed chunks (no full logits); the cost is the 1.2 GB tied head weight, which Liger does not remove; not a small isolated edit |
| D larger --micro-tokens | skipped | | | A peak 5703/6144 MiB, no headroom; B shows the margin is gone |

Fast kernels: fla 0.6.0 + causal_conv1d 1.5.2 in ~/venvs/rsn; no "fast path is not available"/fallback warning in A log (only a Triton 3.2.0 < 3.3.0 notice).
Winner: A (unchanged, speedup 1.0x). run_full.sh already carries these flags (run_ft.env FIT_FLAGS + --offload-min/--mlp-chunk-min 4096).
EOF
echo "speed_test 2026-11-21 done: winner = A (p2 flags), B OOM, C/D skipped, ~33-37 s/step per 4 rows; see 2026-11-21_rsn_full/SPEED.md" >> $Q/AGENT_REGISTRY.md
grep -q "^speed_test" $Q/2026-10-29_rsn_v3/GPU_LOCK && rm -f $Q/2026-10-29_rsn_v3/GPU_LOCK
touch $D/SPEED_DONE; ls $D/SPEED_DONE $Q/2026-10-29_rsn_v3/GPU_LOCK 2>&1
