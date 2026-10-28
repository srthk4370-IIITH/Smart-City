#!/usr/bin/env bash
# After run1: CUDA GGUF greedy eval of v2 (GPU) while the checkpoints are turned into Q4_0 GGUFs (CPU), then the
# candidates one at a time on the GPU, then the paired tables. Unattended; log: $R/pipeline.log
#   bash pipeline_3e.sh RUN "STEPS"      e.g. bash pipeline_3e.sh run1 "40 60 70"
RUN=${1:-run1}; STEPS=${2:-"40 60 70"}
R=~/smartcity_runs/agents_v2_topup3e; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3e
cd $H; source ~/venvs/train/bin/activate
exec >> $R/pipeline.log 2>&1
echo "=== $(date) pipeline $RUN steps $STEPS"
until tail -n 3 $R/$RUN/stdout.log | grep -q "${RUN^^}_EXIT"; do sleep 60; done
echo "$(date +%T) training ended: $(tail -n 1 $R/$RUN/stdout.log)"
N=$(wc -l < $R/eval/eval3e.jsonl)
ev() {  # tag gguf: run until all rows are scored (max 3 tries; the RAM guard may stop a try)
  for t in 1 2 3; do
    python host_eval3e.py run --out $R/eval --model $2 --tag $1 --cuda --threads 4 --np 4 >> $R/eval/logs/$1.log 2>&1
    [ "$(wc -l < $R/eval/eval/$1/samples.jsonl)" -ge "$N" ] && { echo "$(date +%T) eval $1 complete"; return 0; }
    sleep 30
  done; echo "$(date +%T) eval $1 INCOMPLETE"; }
# CPU: GGUFs for the candidates (background), GPU: v2 baseline meanwhile
( for s in $STEPS; do bash post_3e.sh $R/$RUN/checkpoints/checkpoint-$s ${RUN}c$s v2; echo "$(date +%T) post ${RUN}c$s rc=$?"; done ) &
PP=$!
ev v2cuda ~/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf
for s in $STEPS; do
  g=$R/post/gguf/ft_${RUN}c${s}_q4_0.gguf
  until [ -s $g.md5 ] || ! kill -0 $PP 2>/dev/null; do sleep 30; done
  [ -s $g.md5 ] && ev ${RUN}c$s $g
done
wait $PP
python host_eval3e.py table --out $R/eval --ref v2cuda --cand $(for s in $STEPS; do echo -n "${RUN}c$s "; done) > /dev/null
echo "=== $(date) PIPELINE_DONE"
