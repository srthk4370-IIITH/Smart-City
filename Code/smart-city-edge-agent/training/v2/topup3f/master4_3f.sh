#!/usr/bin/env bash
# 3f queue 4 (agent's own background task + watchdog): W1 mixA50 on the 1,148-row test gate + rw5test; W2 m50rw50 on
# rw5dev + dev; then queue 3 (variant B SFT training + evals).
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master4_3f start"
step W1_test bash pipe_3f.sh test mixA50
step W1_rw5test bash pipe_3f.sh rw5test mixA50
step W2_rw5dev bash pipe_3f.sh rw5dev m50rw50
step W2_dev bash pipe_3f.sh dev m50rw50
echo "$(date +%T) W_DONE"
bash $H/master3_3f.sh
bash $H/master5_3f.sh
