#!/usr/bin/env bash
# After training: export checkpoints -> Q4_0 GGUF, then GPU eval (one llama-server at a time).
# Order: final Q4_0 (all suites incl. P0), base Q4_0 with the v3 short prompt (all suites), step0300 (v3 suites),
# final Q4_K_M (v3 suites). Agent-owned shell; caller keeps HEARTBEAT fresh. Logs: eval/results/eval_all.log
R=~/smartcity_runs/reasoner_v1; O=$R/run1; T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final
exec >> $T/eval/results/eval_all.log 2>&1; echo "=== $(date) eval_all start"
FIN=$(ls -d $O/ckpt_step* | sort | tail -1)
bash $T/train/export.sh $FIN final || { echo "export final failed"; exit 1; }
bash $T/eval/eval_gguf.sh $R/gguf/final/final-q4_0.gguf ft_final rw6,rwh,dev,chatdev,p0
bash $T/eval/eval_gguf.sh ~/models/qwen3.5-4b-gguf/qwen3.5-4b-q4_0.gguf base_v3s rw6,rwh,dev,chatdev,p0
bash $T/train/export.sh $O/ckpt_step0300 s300 && bash $T/eval/eval_gguf.sh $R/gguf/s300/s300-q4_0.gguf ft_s300 rw6,rwh,dev,chatdev
bash $T/eval/eval_gguf.sh $R/gguf/final/final-q4_k_m.gguf ft_final_k rw6,rwh,dev,chatdev
echo "=== $(date) EVAL_ALL DONE"
