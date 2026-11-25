#!/bin/bash
# owner 2026-11-19: clear all incidents (moved to state/cleared_20261119, not deleted), after the phase1l deploy
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
L=~/detached/clear_inc.log
until grep -q "DONE\|FAILED" ~/detached/go_1l.log 2>/dev/null; do sleep 20; done
echo "$(date -Is) stop" >> $L; stop_app >> $L 2>&1
sh_ "cd $W/state && mkdir -p cleared_20261119 && for f in incidents*.jsonl; do [ -e \"\$f\" ] && mv \"\$f\" cleared_20261119/; done; ls cleared_20261119" >> $L 2>&1
start_app >> $L 2>&1 && echo "$(date -Is) app up CLEARDONE" >> $L || echo "$(date -Is) app NOT up CLEARDONE" >> $L
