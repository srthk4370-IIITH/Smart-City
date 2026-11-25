#!/bin/bash
# owner 2026-11-19: p2 reasoner + static fault guard on the board. 1 build APK phase1j  2 reasoner p2 GGUF (deploy_model.sh, auto rollback)  3 APK phase1j (rollback = previous APK)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" | tee -a $L/go_1j.log; echo "- go_1j $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1j"; TAG=phase1j nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1 | tee -a $L/go_1j.log | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 reasoner p2"; bash $Q/2026-11-19_deploy/deploy_model.sh reasoner /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_p2_q4_0.gguf >> $L/deploy_reasoner.log 2>&1; st "reasoner rc=$? $(grep -hE 'DEPLOYED reasoner|ROLLBACK|ABORT:' $L/deploy_reasoner.log | tail -1)"
st "3 APK phase1j"; bash $Q/2026-11-16_phase1/deploy_1j.sh >> $L/deploy_1j.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1J_DONE|ABORT|NOT up' $L/deploy_1j.log | tail -1)"
st "DONE"
