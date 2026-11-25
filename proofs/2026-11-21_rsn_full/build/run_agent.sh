#!/usr/bin/env bash
# waits for the owner speed_test to take+release the GPU lock (max 40 min to appear), then runs the deployed agent s0450 on windows_real (resumable)
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-21_rsn_full; L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/GPU_LOCK
for i in $(seq 240); do grep -q speed_test $L 2>/dev/null && break; sleep 10; done
while [ -e $L ] && ! grep -q "^v2_agent_run_gpu " $L; do sleep 30; done
export AGT_NP=8
export AGT_MODEL=$HOME/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf
python3 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/v2_agent_run_gpu.py $D/agent_rows/windows_real.jsonl $D/agent_rows/agent_out_real.jsonl
