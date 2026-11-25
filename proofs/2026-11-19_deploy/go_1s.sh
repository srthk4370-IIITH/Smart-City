#!/bin/bash
# owner 2026-11-20 voice: auto-stop after 2 s quiet, level meter, silent-mic message
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1s.log; echo "- go_1s $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1s"; r=$(TAG=phase1s nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1s"; bash $Q/2026-11-16_phase1/deploy_1s.sh >> $L/deploy_1s.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1R_DONE|ABORT|NOT up' $L/deploy_1s.log | tail -1)"
st "DONE"
