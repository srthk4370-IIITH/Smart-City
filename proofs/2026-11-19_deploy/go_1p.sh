#!/bin/bash
# owner 2026-11-20: uncertain-data threshold + Home "being watched"; waits for phase1o first
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1p.log; echo "- go_1p $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
until grep -q "DONE\|FAILED" $L/go_1o.log; do sleep 20; done
st "1 build phase1p"; r=$(TAG=phase1p nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 APK phase1p"; bash $Q/2026-11-16_phase1/deploy_1p.sh >> $L/deploy_1p.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1P_DONE|ABORT|NOT up' $L/deploy_1p.log | tail -1)"
st "DONE"
