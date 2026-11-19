#!/usr/bin/env bash
# export_2b_now.sh: 2B export with a lower RAM floor (streaming merge of a 2B fits), then restart the chain -> gate.
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle
EXPORT_RAM_MB=1500 RUN_ID=r1 bash $KG/local/export_gguf.sh ~/models/qwen3.5-2b ~/smartcity_runs/rsn3_2b_r1/ckpt_best_1200 rsn_v3_2b || exit 1
rm -f $KG/chain/STOP
bash $KG/local/train_ctl.sh start
