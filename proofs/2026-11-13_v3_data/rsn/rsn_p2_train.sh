#!/bin/bash
# rsn_p2_train.sh: part-2 top-up from the fine-tune best (step 400 adapter) on data/final_v2; lock/guards/watchdog = ft_chunk.sh
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; T4=$QP/2026-11-13_v3_train/rsn_ft; D=$QP/2026-11-13_v3_data/rsn/data/final_v2
set -a; source $T4/run_ft.env; set +a
S=$(python3 -c "import json;print(json.load(open('$HOME/smartcity_runs/rsn3_4b_v3ft/best.json'))['top'][0][1])")
export RUN=rsn3_4b_v3ft_p2 NEW=$D/train_new.jsonl REPLAY=$D/replay.jsonl TOOLS4=$D/tools_v4.json BASE=$(cat $T4/chain/BASE)
export START_ADAPTER=$(printf "%s/smartcity_runs/rsn3_4b_v3ft/ckpt_best_%04d" $HOME $S)
export TOPUP_FLAGS="--lr 2e-5 --warmup 0.05 --floor 0.1 --accum 16 --mix 0.75 --epochs 0.43 --save-every 25 --eval-every 1000 --gen-every 1000 --patience 3 --keep-best 3 --w-r4 0.5 --r3-tol 0.01"
export MAX_STEPS=${MAX_STEPS:-220} CHUNK_H=6
mkdir -p ~/smartcity_runs/$RUN
for i in 1 2 3; do bash $T4/ft_chunk.sh; rc=$?; case $rc in 0|6) exit 0;; 3) ;; *) sleep 600;; esac; done
exit $rc
