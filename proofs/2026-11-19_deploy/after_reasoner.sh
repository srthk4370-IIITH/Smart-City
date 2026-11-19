#!/usr/bin/env bash
# Waits for the reasoner deploy to finish (DEPLOYED / ROLLBACK / ABORT, or rsn_p2 gate FAIL), then deploys phase1i.
# Start: bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh after_reasoner /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-19_deploy/after_reasoner.sh
L=~/detached
while ! { grep -qE "DEPLOYED reasoner|ROLLBACK|ABORT:" $L/deploy_reasoner.log 2>/dev/null || grep -q "gate FAIL" $L/rsn_p2.log 2>/dev/null; }; do sleep 60; done
echo "$(date -Is) reasoner finished: $(grep -hE 'DEPLOYED reasoner|ROLLBACK|ABORT:|gate FAIL' $L/deploy_reasoner.log $L/rsn_p2.log 2>/dev/null | tail -1)" >> $L/after_reasoner.log
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_1i.sh >> $L/deploy_1i.log 2>&1
rc=$?
echo "$(date -Is) deploy_1i exit=$rc $(grep -E 'DEPLOY1I_DONE|1i ABORT|NOT up' $L/deploy_1i.log | tail -1)" >> $L/after_reasoner.log
