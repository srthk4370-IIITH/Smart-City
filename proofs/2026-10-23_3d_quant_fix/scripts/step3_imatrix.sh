#!/usr/bin/env bash
# Domain imatrix (aligned agent prompts, 256 x 1280) for one model tag: 3d | v2
set -uo pipefail
TAG=$1; FIX=~/smartcity_runs/agents_v2_topup3d/post/gguf_fix; W=$FIX/work; B=~/gpu_work/llama.cpp/build-host/bin
M=$W/ft_${TAG/3d/v2t3d}_q8_0.gguf; [ "$TAG" = v2 ] && M=$W/ft_v2_q8_0.gguf
OUT=$FIX/imatrix_dom_${TAG}.gguf
[ -s $OUT ] && { echo "exists $OUT"; exit 0; }
echo "[$(date)] imatrix $TAG on $M"
nice $B/llama-imatrix -m $M -f $FIX/calib/calib_domain.txt --parse-special -c 1280 -b 1280 --chunks 256 -t 4 \
   -o $OUT.tmp --output-format gguf --save-frequency 64 > $FIX/imatrix_dom_${TAG}.log 2>&1
tail -5 $FIX/imatrix_dom_${TAG}.log
[ -s $OUT.tmp ] && mv $OUT.tmp $OUT && echo "[$(date)] imatrix $TAG done"
