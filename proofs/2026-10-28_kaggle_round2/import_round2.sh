#!/usr/bin/env bash
# import_round2.sh <rsn_r2_adapter.zip>: Kaggle adapter -> low-RAM merge (merge_q4.sh) -> models_stage/rsn_v2_q4_0.gguf + md5
# -> waits until the GPU is free (P3b done, < 800 MiB used, no trainer) -> RWH + P0 + severity agreement vs ft612.
# Agent-owned shell; touches HEARTBEAT while waiting/evaluating. Log: ~/smartcity_runs/reasoner_v1/import_round2.log
set -e
Z=$1; R=~/smartcity_runs/reasoner_v1; T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final; HB=$R/HEARTBEAT
exec > >(tee -a $R/import_round2.log) 2>&1; echo "=== $(date) import $Z"
CK=$R/run2_kaggle/ckpt_final; rm -rf $CK; mkdir -p $CK; cd $CK && python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall('.')" "$Z"
cat $CK/KAGGLE_MANIFEST.json; grep -q '"done": true' $CK/KAGGLE_MANIFEST.json || echo "WARNING: PARTIAL adapter"
CK=$CK NAME=rsn_v2 bash $T/train/merge_q4.sh            # CPU, waits for >= 4 GB free Windows RAM
( while true; do touch $HB; sleep 300; done ) & TOUCH=$!; trap "kill $TOUCH 2>/dev/null" EXIT
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc 0-9)" -lt 800 ] && ! pgrep -f "[t]rain_3e.py|[t]rain_rsn.py|[l]lama-server" >/dev/null; do sleep 120; done
G2=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v2_q4_0.gguf
bash $T/eval/eval_gguf.sh $G2 rsn_v2 rwh,p0; bash $T/eval/eval_gguf.sh $G2 rsn_v2b rwh
cd $T/eval && { REPAIR=1 python3 score_v3.py rsn_v2 ft612; python3 p0_score.py rsn_v2 ft612 | tail -2; python3 sev_agree.py rsn_v2 rsn_v2b; } | tee $T/eval/results/round2_result.txt
echo "=== $(date) ROUND2 IMPORT+EVAL DONE"
