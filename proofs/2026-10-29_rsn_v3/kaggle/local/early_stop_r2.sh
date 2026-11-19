#!/usr/bin/env bash
# early_stop_r2.sh: owner allowed stopping r2 early when it looks done (2026-11-02 ~23:00 IST).
# After every GEN eval: stop when the dev score has plateaued, i.e. step >= MIN_STEP, best >= MIN_SCORE and
# no better score for PLATEAU evals (trainer's own patience is 3; this stops one eval earlier, from MIN_STEP on).
# Then STOP -> checkpoint, mark chain/r2/train_2b.done, restart the chain -> export best checkpoint + gate g2b_r2.
# The gate (not the 80-item GEN score) decides deploy; r1 had GEN 0.954 and still failed the gate.
# If the gate fails: rm chain/r2/train_2b.done chain/r2/export_2b.done and start.ps1 resumes from the checkpoint.
# Launch via proofs/detach.sh.
KG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle; C=$KG/chain; CM=$C/r2; R=~/smartcity_runs/rsn3_2b_r2
MIN_STEP=${MIN_STEP:-1200}; MIN_SCORE=${MIN_SCORE:-0.95}; PLATEAU=${PLATEAU:-2}
st() { echo "- $(date '+%F %T') [early_stop_r2] $*" >> $KG/STATUS.md; echo "$(date '+%T') $*"; }
st "watching GEN evals: stop when step >= $MIN_STEP, best >= $MIN_SCORE, no gain for $PLATEAU evals"
seen=$(grep -c 'GEN step' $R/train.log)
while :; do
  [ -e $CM/train_2b.done ] && { st "train_2b already done; exiting"; exit 0; }
  n=$(grep -c 'GEN step' $R/train.log)
  if [ "$n" != "$seen" ]; then
    seen=$n
    read step best since <<< "$(python3 -c "
import json,re
b=json.load(open('$R/best.json'))
s=[int(m) for m in re.findall(r'GEN step (\d+)', open('$R/train.log').read())][-1]
print(s, b['best'], b['since_best'])")"
    st "GEN step $step: best $best, evals since best $since"
    if [ "$step" -ge "$MIN_STEP" ] && [ "$since" -ge "$PLATEAU" ] && python3 -c "import sys; sys.exit(0 if $best >= $MIN_SCORE else 1)"; then
      st "plateau at step $step (best $best): stopping trainer -> export best + gate"
      touch $C/STOP
      while pgrep -f train_rsn3.py >/dev/null || { p=$(cat $C/chain.pid 2>/dev/null); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }; do sleep 20; done
      touch $CM/train_2b.done; rm -f $C/STOP
      st "trainer stopped; train_2b marked done; best.json: $(tr -d ' \n' < $R/best.json | cut -c1-80)"
      bash $KG/local/train_ctl.sh start
      st "chain restarted -> export_2b + gate g2b_r2"
      exit 0
    fi
  fi
  sleep 120
done
