#!/usr/bin/env bash
# 3f queue 7: alpha 0.3 mixes (less c49 = fewer power warning->critical over-alarms): mixA30, mixRep30 on dev
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master7_3f start"
V=~/smartcity_runs/agents_v2/adapter; C=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49
RL=$(ls -d $R/rep/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1); BL=$(ls -d $R/m50rwB/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mkdir -p $R/post/mixRep30; echo "{\"mix\": [[\"$V\", 0.7], [\"$RL\", 0.3]], \"chosen\": \"mixRep30\"}" > $R/post/mixRep30/choice.json
step Z1_dev bash pipe_3f.sh dev mixA30 mixRep30
echo "=== $(date) MASTER7_DONE"
