#!/bin/bash
# owner 2026-11-20 INC-0004: promotion resolve needs rules, no calm title on warning, IST timeline
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1u.log; echo "- go_1u $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1u"; r=$(TAG=phase1u nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1u"; bash $Q/2026-11-16_phase1/deploy_1u.sh >> $L/deploy_1u.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1R_DONE|ABORT|NOT up' $L/deploy_1u.log | tail -1)"
st "DONE"
