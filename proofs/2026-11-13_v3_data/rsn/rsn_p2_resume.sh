#!/bin/bash
# rsn_p2_resume.sh: stages 5-7 of rsn_p2_chain.sh only (gate, export, deploy) after the C: space stop 2026-11-19
# stages: 0 wait ~/smartcity_runs/FINAL_AGENT -> 1 regen agent rows (GPU lock) -> 2 build (v2_gen p2 families) -> 3 verify -> 4 top-up train -> 5 gate -> 6 merge+Q4_0
QP=/mnt/c/Users/hp/Desktop/qidk/proofs; R=$QP/2026-11-13_v3_data/rsn; D=$R/data/final_v2; W=$D/work; LOG=~/detached/rsn_p2.log
st() { echo "STAGE $* $(date -Is)" | tee -a $LOG; echo "- rsn_p2 $* $(date -Is)" >> $QP/AGENT_REGISTRY.md; }
fail() { st "FAILED $*"; exit 1; }
cd $R; O=~/smartcity_runs/rsn3_4b_v3ft_p2
[ -s $O/best.json ] || fail "no p2 best.json"
st "5 gate"; bash $R/rsn_p2_gate.sh || fail "gate script"
grep -q "^RESULT: PASS" $QP/2026-11-18_rsn_p2/GATE.md || { st "gate FAIL: no merge"; bash $R/rsn_p2_ready.sh; exit 0; }
st "6 merge+export"; bash $R/rsn_p2_export.sh || fail "export"
bash $R/rsn_p2_ready.sh; st "export done: auto-deploy reasoner to QIDK (owner 2026-11-19)"
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-19_deploy/deploy_model.sh reasoner /mnt/c/Users/hp/Desktop/qidk/Code/models_stage/rsn_v3_4b_p2_q4_0.gguf >> $HOME/detached/deploy_reasoner.log 2>&1; st "reasoner deploy rc=$? (see ~/detached/deploy_reasoner.log)"
