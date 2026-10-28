#!/usr/bin/env bash
# Host greedy eval (host_eval_v2.py gguf backend = llama-server CPU, same prompts/prefill/stop/scoring as the board eval)
# of each "tag=model" pair on the diagnosis subset; one model at a time, behind gate.sh; page cache dropped after each.
#   bash run_evals.sh v2_q8=/path/a.gguf 3d_q8=/path/b.gguf ...
S=/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/scripts
for pair in "$@"; do
  tag=${pair%%=*}; m=${pair#*=}
  $S/gate.sh wsl.exe -d Ubuntu -- bash -c "cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post && \
    nice ~/venvs/train/bin/python host_eval_v2.py run --post /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_3d_quant_fix/post_diag \
    --backend gguf --model $m --tag $tag --threads 4 --np 2 --slot-ctx 1536 --max-new 160 2>&1 | grep -v '^  [0-9]*0/'"
  wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
  echo "=== $(date +%T) $tag done"
done
