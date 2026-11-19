# Owner-confirmed (chat, 2026-11-16): real windows on Kaggle as a PRIVATE dataset for this top-up. push -> pull (re-push if unfinished) -> select (pauses the reasoner fine-tune for the GPU, then resumes) -> board agent switch
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_agt_topup_kaggle; QP=/mnt/c/Users/hp/Desktop/qidk/proofs; RF=$QP/2026-11-13_v3_train/rsn_ft
st() { echo "$(date -Is) $*"; echo "- $(date -u +%FT%H:%MZ) [agt_topup_k] $*" >> $QP/AGENT_REGISTRY.md; }
for k in 1 2 3; do
  bash $D/push_topup.sh; rc=$?; st "push #$k rc=$rc"; [ $rc = 0 ] || { [ $rc = 20 ] && st "quota: stop"; exit $rc; }
  bash $D/pull_topup.sh; rc=$?; st "pull #$k rc=$rc"
  python3 -c "import json,sys,os;d=json.load(open(os.path.expanduser('~/smartcity_runs/agt_topup_k/run/status.json')));sys.exit(0 if d.get('stopped') or d.get('step',0)>=d.get('n_steps',1) else 1)" && break
done
st "training finished; pausing reasoner fine-tune for selection"
touch $RF/chain/STOP; while pgrep -f '[f]t_chain.sh' > /dev/null; do sleep 60; done
bash $D/select_topup.sh; rc=$?; st "select rc=$rc ($(cat ~/smartcity_runs/agt_topup/FINAL_K 2>/dev/null | cut -c1-120))"
rm -f $RF/chain/STOP; /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -ExecutionPolicy Bypass -File 'C:\Users\hp\Desktop\start.ps1'
[ $rc = 0 ] && [ -s ~/smartcity_runs/agt_topup/FINAL_K ] || { st "no winner: board keeps s0075"; exit 3; }
G=$(awk '{print $1}' ~/smartcity_runs/agt_topup/FINAL_K)
sed -e "s#AG=.*final_s0075/agt3_final_s0075_q4_0.gguf#AG=$G#" -e 's#agt3_s0075_q4_0.gguf#agt3_k_q4_0.gguf#g' $QP/2026-11-16_phase1/switch_agt3.sh > $D/switch_k.sh
bash $D/switch_k.sh; st "board agent switch rc=$?"
