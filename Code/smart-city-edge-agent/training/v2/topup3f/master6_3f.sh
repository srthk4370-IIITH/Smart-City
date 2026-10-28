#!/usr/bin/env bash
# 3f queue 6: Y1 mixRep50 on the test gate + rw5test; Y2 task arithmetic mRB(beta) = mixRep50 + beta x (m50rwB - mixA50)
# for beta 0.5 / 0.3 on rw5dev + dev (merge_mix with signed weights).
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master6_3f start"
V=~/smartcity_runs/agents_v2/adapter; C=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49
RL=$(ls -d $R/rep/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1); BL=$(ls -d $R/m50rwB/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
for b in 0.5 0.3; do t=mRB${b/0./}; mkdir -p $R/post/$t
  echo "{\"mix\": [[\"$V\", $(python3 -c "print(0.5-$b/2)")], [\"$RL\", 0.5], [\"$BL\", $b], [\"$C\", $(python3 -c "print(-$b/2)")]], \"chosen\": \"$t\"}" > $R/post/$t/choice.json; done
step Y1_test bash pipe_3f.sh test mixRep50
step Y1_rw5test bash pipe_3f.sh rw5test mixRep50
step Y2_rw5dev bash pipe_3f.sh rw5dev mRB5 mRB3
step Y2_dev bash pipe_3f.sh dev mRB5 mRB3
echo "=== $(date) MASTER6_DONE"
