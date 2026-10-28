#!/usr/bin/env bash
# 3f queue 2 (same laptop rules as master_3f.sh; evals wait for the benchmark's llama-server to exit, see pipe_3f waitgpu)
#  T1 rw5dev: v2, mixA50, m50rwL      T2 rw5test: v2 (scored first)
#  T3 m50rw50 = mixA50 + 0.5 x (m50rwL - mixA50)  (WiSE-FT of the section-5 SFT): dev + rw5dev
R=~/smartcity_runs/agents_v2_topup3f; H=/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f
mkdir -p $R/done; exec >> $R/master.log 2>&1; cd $H; source $H/watchdog.sh
step() { local name=$1; shift; [ -e $R/done/$name ] && return 0; echo "$(date +%T) START $name"
  nice -n 19 ionice -c3 "$@"; local rc=$?; echo "$(date +%T) END $name rc=$rc"; [ $rc = 0 ] && touch $R/done/$name; return $rc; }
echo "=== $(date) master2_3f start"
step T1_rw5dev bash pipe_3f.sh rw5dev mixA50 m50rwL
step T2_rw5test bash pipe_3f.sh rw5test
V=~/smartcity_runs/agents_v2/adapter; C=~/smartcity_runs/agents_v2_topup3e/run2/checkpoints/checkpoint-49
L=$(ls -d $R/m50rw/checkpoints/checkpoint-* | sort -t- -k2 -n | tail -1)
mkdir -p $R/post/m50rw50; echo "{\"mix\": [[\"$V\", 0.25], [\"$C\", 0.25], [\"$L\", 0.5]], \"chosen\": \"m50rw50\"}" > $R/post/m50rw50/choice.json
step T3_rw5dev bash pipe_3f.sh rw5dev m50rw50
step T3_dev bash pipe_3f.sh dev m50rw50
echo "=== $(date) MASTER2_DONE"
