# owner 2026-11-19: accept agent v2 s0450 (Kaggle fp16 + laptop Q4_0 checked) -> deploy agent now; FINAL_AGENT -> reasoner p2 chain (rows, audit, train, gate, export, auto-deploy)
for p in $(pgrep -f "rsn_p2_chain.sh"); do kill $p; done
G=$HOME/smartcity_runs/agt_topup_k2b/post/s0450/agt3_s0450_q4_0.gguf
printf '%s\nowner accepted 2026-11-19: v2 s0450 (fp16 val .816 hard .929 tool .813; Q4_0 val .813 hard .918 t2 .92)\n' "$G" > $HOME/smartcity_runs/FINAL_AGENT
bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn_p2 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn/rsn_p2_chain.sh
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-19_deploy/deploy_model.sh agent "$G"
