#!/bin/bash
# owner 2026-11-19: stored-incident audit fixes -> APK phase1l (build, install, rollback = previous APK)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1l.log; echo "- go_1l $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1l"; r=$(TAG=phase1l nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1l"; bash $Q/2026-11-16_phase1/deploy_1l.sh >> $L/deploy_1l.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1K_DONE|ABORT|NOT up' $L/deploy_1l.log | tail -1)"
st "DONE"
