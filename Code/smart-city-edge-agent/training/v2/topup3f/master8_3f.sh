#!/usr/bin/env bash
# 3f queue 8 (LoRA-scaling screen): build base0 Q4_0 once, then the queued lines of $R/queue8.txt, one per call:
#   "SET TAG TAG ..." -> pipe_lora.sh. Lines already done are recorded in $R/done/q8_<md5 of line>.
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done $R/screen; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
echo "=== $(date) master8_3f start"
if [ ! -s $R/post/gguf/ft_base0_q4_0.gguf.md5 ]; then mkdir -p $R/post/base0
  echo '{"mix": [["/home/hp_srthk4370/smartcity_runs/agents_v2/adapter", 0.0]], "chosen": "base0"}' > $R/post/base0/choice.json
  nice -n 19 ionice -c3 bash $H/post_3f.sh NONE base0 v2; echo "$(date +%T) post base0 rc=$?"; fi
[ -s $R/post/gguf/ft_base0_q4_0.gguf.md5 ] || exit 3
# GPU only after the reasoner benchmark finished (RESULTS.md) or main said so ($R/GPU_OK)
while [ ! -e /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_reasoner_research/P0/host_bench/RESULTS.md ] && [ ! -e $R/GPU_OK ]; do sleep 30; done
echo "$(date +%T) GPU gate open"
while true; do
  line=$(while read -r l; do [ -z "$l" ] && continue; k=q8_$(echo "$l" | md5sum | cut -c1-12); [ -e $R/done/$k ] || { echo "$l"; break; }; done < $R/queue8.txt)
  [ -z "$line" ] && break
  k=q8_$(echo "$line" | md5sum | cut -c1-12); echo "$(date +%T) START $line"
  nice -n 19 ionice -c3 bash $H/pipe_lora.sh $line; echo "$(date +%T) END $line rc=$?"; touch $R/done/$k
done
echo "=== $(date) MASTER8_DONE"
