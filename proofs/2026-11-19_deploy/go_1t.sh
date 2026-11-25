#!/bin/bash
# owner 2026-11-20 critical early AI on history, trend-only guard, report steps merged, clean titles
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1t.log; echo "- go_1t $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1t"; r=$(TAG=phase1t nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1t"; bash $Q/2026-11-16_phase1/deploy_1t.sh >> $L/deploy_1t.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1R_DONE|ABORT|NOT up' $L/deploy_1t.log | tail -1)"
st "DONE"
