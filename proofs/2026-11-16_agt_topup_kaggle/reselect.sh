# owner 2026-11-16: free space (re-creatable non-best screening GGUFs only), rerun selection s0150..s0312, board switch on a winner
R=$HOME/smartcity_runs; QP=/mnt/c/Users/hp/Desktop/qidk/proofs; D=$QP/2026-11-16_agt_topup_kaggle; RF=$QP/2026-11-13_v3_train/rsn_ft
rm -f $R/agt_topup/post/s0075/agt3_s0075_q4_0.gguf $R/agt_topup_k/post/s0050/agt3_s0050_q4_0.gguf $R/agt_v3/post/final_snap_1500/agt3_final_snap_1500_q4_0.gguf $R/agt_v3/post/snap_1750/agt3_snap_1750_q4_0.gguf
echo "C: free $(df -Pm /mnt/c | awk 'NR==2{print $4}') MB"
touch $RF/chain/STOP; while pgrep -f '[f]t_chain.sh' > /dev/null; do sleep 60; done
bash $D/select_topup.sh; rc=$?; echo "select rc=$rc $(cat $R/agt_topup/FINAL_K 2>/dev/null | cut -c1-120)"
rm -f $RF/chain/STOP; /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -ExecutionPolicy Bypass -File 'C:\Users\hp\Desktop\start.ps1'
[ $rc = 0 ] && [ -s $R/agt_topup/FINAL_K ] || { echo "no winner: board keeps s0075"; exit 3; }
G=$(awk '{print $1}' $R/agt_topup/FINAL_K)
sed -e "s#AG=.*final_s0075/agt3_final_s0075_q4_0.gguf#AG=$G#" -e 's#agt3_s0075_q4_0.gguf#agt3_k_q4_0.gguf#g' $QP/2026-11-16_phase1/switch_agt3.sh > $D/switch_k.sh
bash $D/switch_k.sh; echo "board agent switch rc=$?"
