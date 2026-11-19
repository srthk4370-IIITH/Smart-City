#!/usr/bin/env bash
# Wait-step dry run (CPU, seconds): on the fake run of t_export_tiny.sh (<outdir> must hold base/ and run/), the chain must
# wait while training is not finished, while Kaggle holds the baton, and stop cleanly on the STOP file.  usage: bash t_wait.sh <outdir>
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post; O=${1:?outdir}; W=$O/wait; rm -rf $W; mkdir -p $W/state $W/chain
cp -r $O/run $W/run
export POST_STATUS=$W/status.md POST_OUT=$W/state POST_RUN=rsn3_tiny_post POST_RUNDIR=$W/run POST_NAME=tiny_wait POST_BASE=$O/base \
  POST_CHAIN_DIR=$W/chain POST_BATON=$W/BATON POST_PICK_DIR=$W/pick STAGE_DIR=$W/stage SCRIPT=post_4b_wait
run_case() {   # run_case <label>: start the chain, give it 5 s, STOP it, print its status lines
  rm -f $W/state/STOP $W/status.md
  bash $P/post_chain.sh > /dev/null 2>&1 & local pc=$!
  sleep 5; touch $W/state/STOP
  # the wait loop sleeps 600 s between checks: kill the sleep so STOP is seen at once
  pkill -P $pc sleep 2>/dev/null; wait $pc; echo "[$1] rc=$? markers: $(ls $W/state/markers 2>/dev/null | tr '\n' ' ')"; grep -v '^#' $W/status.md | grep . | cut -c1-140
}
echo '{"step": 120, "done": false}' > $W/run/status.json; echo "holder=laptop" > $W/BATON
run_case "not finished"
echo '{"step": 320, "stopped": "early_stop"}' > $W/run/status.json; echo "holder=kaggle" > $W/BATON
run_case "kaggle holds the baton"
echo "holder=laptop" > $W/BATON; touch $W/run/BATON_AT_KAGGLE
run_case "BATON_AT_KAGGLE marker"
rm -rf $W
