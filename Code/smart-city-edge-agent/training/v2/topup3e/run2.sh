#!/usr/bin/env bash
# 3e run2 (fallback, same method, cleaner data): pairs without event-vs-stable, flatline-vs-decrease confusions and
# sizes 2.5-6x noise; replay 2:1. Waits for the run1c20 eval (one GPU model at a time), trains, then builds + evals.
R=~/smartcity_runs/agents_v2_topup3e; mkdir -p $R/run2; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
until [ "$(grep -c PIPELINE_DONE $R/pipeline.log)" -ge 2 ]; do sleep 30; done
cd $H; source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
python train_3e.py --out $R/run2 --data $R/data/train3e_r2.jsonl --save-every 15 --lr 5e-6 --beta 0.1 --rpo-alpha 1.0 >> $R/run2/stdout.log 2>&1
echo "RUN2_EXIT $? $(date)" >> $R/run2/stdout.log
bash $H/pipeline_3e.sh run2 "30 49"
