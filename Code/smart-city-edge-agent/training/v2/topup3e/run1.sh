#!/usr/bin/env bash
# 3e run1: wait for the GPU to be free of other llama-servers, then preference training (resumable)
R=~/smartcity_runs/agents_v2_topup3e; mkdir -p $R/run1
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
# (wait loop removed: GPU checked by hand)
python train_3e.py --out $R/run1 --data $R/data/train3e.jsonl --save-every 20 --lr 5e-6 --beta 0.1 --rpo-alpha 1.0 >> $R/run1/stdout.log 2>&1
echo "RUN1_EXIT $? $(date)" >> $R/run1/stdout.log
