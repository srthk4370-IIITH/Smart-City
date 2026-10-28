#!/usr/bin/env bash
# mine the real-world rows first, then continue the main pool (resumable); stop with: touch ~/smartcity_runs/agents_v2_topup3e/data/STOP_MINE (checked between files)
cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
source ~/venvs/train/bin/activate; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
D=~/smartcity_runs/agents_v2_topup3e/data
python mine_3e.py --pool $D/realworld_train.jsonl --out $D/mined_rw.jsonl >> $D/mine_rw.log 2>&1
python mine_3e.py --pool $D/pool.jsonl --out $D/mined.jsonl --limit ${1:-0} >> $D/mine.log 2>&1
echo "MINE_ALL_DONE $(date)" >> $D/mine.log
