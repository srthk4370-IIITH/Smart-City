#!/bin/bash
# owner 2026-11-20 hands-on fixes: no sensor refs in titles, 4-of-8 wording, chat stale wording
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1r.log; echo "- go_1r $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1r"; r=$(TAG=phase1r nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1r"; bash $Q/2026-11-16_phase1/deploy_1r.sh >> $L/deploy_1r.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1R_DONE|ABORT|NOT up' $L/deploy_1r.log | tail -1)"
st "DONE"
