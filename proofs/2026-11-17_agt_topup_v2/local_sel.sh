# owner 2026-11-18 23:10 IST: local laptop Q4_0 selection of continuation snapshots s0634 + s0450 vs s0300 (Kaggle eval r2 overran). No handoff, no FINAL_AGENT.
export TOPUP_K=$HOME/smartcity_runs/agt_topup_k2b ONLY_TAGS="s0634 s0450" SKIP_BELOW=100
bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-17_agt_topup_v2/select_v2.sh; echo "LOCAL_SEL rc=$?"
