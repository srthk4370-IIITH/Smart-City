#!/usr/bin/env bash
# Eval half of import_round2.sh (the merge + Q4_0 stage is done: models_stage/rsn_v2_q4_0.gguf md5 b4562c86...).
# Waits for P3b's QUEUE_DONE_P3B.json (not just a momentarily idle GPU) and for no PAUSE_GPU, then RWH + P0 + severity
# agreement vs ft612. Appends the "ROUND2 IMPORT+EVAL DONE" marker gate_study waits for. Standalone (detach.sh).
R=~/smartcity_runs/reasoner_v1; T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/QUEUE_DONE_P3B.json; PAUSE=$T/PAUSE_GPU
exec >> $R/import_round2.log 2>&1 < /dev/null; echo "=== $(date) eval_round2: wait for P3b"
( while true; do touch $R/HEARTBEAT; sleep 300; done ) & TOUCH=$!; trap "kill $TOUCH 2>/dev/null" EXIT
until [ -s $P ] && [ ! -e $PAUSE ] && [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] \
  && ! pgrep -f "[t]rain_3e.py|[t]rain_rsn.py|[l]lama-server" >/dev/null; do sleep 120; done
G2=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v2_q4_0.gguf
bash $T/eval/eval_gguf.sh $G2 rsn_v2 rwh,p0; bash $T/eval/eval_gguf.sh $G2 rsn_v2b rwh
cd $T/eval && { REPAIR=1 python3 score_v3.py rsn_v2 ft612; python3 p0_score.py rsn_v2 ft612 | tail -2; python3 sev_agree.py rsn_v2 rsn_v2b; } | tee $T/eval/results/round2_result.txt
echo "=== $(date) ROUND2 IMPORT+EVAL DONE"
