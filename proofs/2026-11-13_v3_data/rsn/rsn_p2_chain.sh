#!/bin/bash
# Reasoner part 2 chain (PREPARED, NOT STARTED; owner pause 2026-11-18: waits for the FINAL agent).
# stages: 0 wait ~/smartcity_runs/FINAL_AGENT -> 1 regen agent rows (GPU lock) -> 2 build (v2_gen p2 families) -> 3 verify -> 4 top-up train -> 5 gate -> 6 merge+Q4_0
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; R=$QP/2026-11-13_v3_data/rsn; D=$R/data/final_v2; W=$D/work; LOG=~/detached/rsn_p2.log
st() { echo "STAGE $* $(date -Is)" | tee -a $LOG; echo "- rsn_p2 $* $(date -Is)" >> $QP/AGENT_REGISTRY.md; }
fail() { st "FAILED $*"; exit 1; }
cd $R
until [ -s ~/smartcity_runs/FINAL_AGENT ]; do sleep 300; done
GG=$(head -1 ~/smartcity_runs/FINAL_AGENT); [ -s "$GG" ] || fail "FINAL_AGENT gguf missing: $GG"
st "1 agent rows with $GG"
if [ -s $W/agent_out.jsonl ] && [ $W/agent_out.jsonl -nt ~/smartcity_runs/FINAL_AGENT ] && [ "$(wc -l < $W/agent_out.jsonl)" -ge 1900 ]; then st "1 skip: agent rows already made with the final agent"; else
[ -s $W/agent_out.jsonl ] && mv $W/agent_out.jsonl $W/agent_out.pre_final_agent.jsonl
AGT_MODEL=$GG python3 v2_agent_run_gpu.py $W/windows.jsonl $W/agent_out.jsonl >> $W/agent_gpu.log 2>&1 || fail "agent gen"; fi
[ "$(wc -l < $W/agent_out.jsonl)" -ge 1900 ] || fail "agent outputs <1900"
st "2-3 build+verify"
export P2_FAMILIES=1 W; mkdir -p logs
if [ -e $D/READY ] && [ $D/READY -nt $W/agent_out.jsonl ]; then st "2-3 skip: final_v2 READY already built from these agent rows"; else rm -f $D/READY
bash -c 'sed "/^while p=/,/^\[ \"\$n\" -ge/d" v2_stage2.sh > $W/stage2_nowait.sh'; bash $W/stage2_nowait.sh >> logs/p2_stage2.log 2>&1; fi
[ -e $D/READY ] || fail "stage2 no READY ($(tail -n 2 logs/p2_stage2.log | tr '\n' ' '))"
st "3b row audit"; mkdir -p $QP/2026-11-18_rsn_p2; python3 $R/rsn_p2_audit.py $D $QP/2026-11-18_rsn_p2/AUDIT.md >> $LOG 2>&1 || fail "row audit >5% bad (see 2026-11-18_rsn_p2/AUDIT.md)"
st "4 top-up train"
[ "$(df -Pm /mnt/c | awk 'NR==2{print $4}')" -ge 20000 ] || fail "C: <20GB"
O=~/smartcity_runs/rsn3_4b_v3ft_p2
bash $R/rsn_p2_train.sh >> ~/detached/rsn_p2_train.log 2>&1
[ -s $O/best.json ] || fail "no p2 best.json"
st "5 gate"; bash $R/rsn_p2_gate.sh || fail "gate script"
grep -q "^RESULT: PASS" $QP/2026-11-18_rsn_p2/GATE.md || { st "gate FAIL: no merge"; bash $R/rsn_p2_ready.sh; exit 0; }
st "6 merge+export"; bash $R/rsn_p2_export.sh || fail "export"
bash $R/rsn_p2_ready.sh; st "export done: auto-deploy reasoner to QIDK (owner 2026-11-19)"
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-19_deploy/deploy_model.sh reasoner /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_p2_q4_0.gguf >> $HOME/detached/deploy_reasoner.log 2>&1; st "reasoner deploy rc=$? (see ~/detached/deploy_reasoner.log)"
