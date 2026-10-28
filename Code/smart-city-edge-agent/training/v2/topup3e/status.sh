#!/usr/bin/env bash
# one-screen status of 3e jobs
R=~/smartcity_runs/agents_v2_topup3e
date
echo "mine: $(grep -c . $R/data/mined.jsonl 2>/dev/null) rows; $(tail -1 $R/data/mine.log | cut -c1-120)"
for t in $R/eval/eval/*/; do echo "host $(basename $t): $(wc -l < $t/samples.jsonl) rows; $(tail -1 $R/eval/logs/$(basename $t).log 2>/dev/null)"; done
for d in $R/run*/; do [ -d "$d" ] && echo "train $(basename $d): $(tail -1 $d/train.log | cut -c1-160)"; [ -f $d/stats.jsonl ] && tail -1 $d/stats.jsonl; done
nvidia-smi --query-gpu=temperature.gpu,memory.used,utilization.gpu --format=csv,noheader
pgrep -fa "llama-server|train_3e|mine_3e|tf_eval|llama-quantize|convert_hf" | grep -v pgrep | cut -c1-100
free -g | sed -n 2p
ls /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_realworld/ 2>/dev/null | tr '\n' ' '
