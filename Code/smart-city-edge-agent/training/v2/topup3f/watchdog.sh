# sourced by the 3f queue scripts: exits the queue and kills its GPU jobs if $R/HEARTBEAT is older than 15 min
# (the controlling agent touches HEARTBEAT from its wait loop; a stopped agent therefore stops the GPU work).
HB=~/smartcity_runs/agents_v2_topup3f/HEARTBEAT; touch $HB; MAIN=$$
( while sleep 60; do age=$(( $(date +%s) - $(stat -c %Y $HB) )); kill -0 $MAIN 2>/dev/null || exit 0
  if [ $age -gt 900 ]; then echo "$(date +%T) WATCHDOG: heartbeat ${age}s old -> stopping 3f jobs"
    pkill -f "llama-cuda-shim/build-host/bin/llama-server"; pkill -f "host_eval3e.py run"; pkill -f "train_3e.py"
    pkill -f "pipe_3f.sh"; pkill -f "pipe_lora.sh"; pkill -f "post_3f.sh"; kill $MAIN; exit 0; fi; done ) &
WD=$!; trap "kill $WD 2>/dev/null; pkill -f llama-cuda-shim/build-host/bin/llama-server" EXIT
