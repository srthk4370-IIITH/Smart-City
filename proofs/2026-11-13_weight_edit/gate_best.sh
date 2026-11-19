# agent gate on BEST snapshot only (owner rule)
cd /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt
# 2026-11-15: GPU_ASSUME_FREE because the dataset-v2 CPU-only llama-server (-ngl 0) matched the gate pgrep and deadlocked it
B=$(cat ~/smartcity_runs/agt_v3/post/BEST)
GPU_ASSUME_FREE=1 bash gate.sh ~/smartcity_runs/agt_v3/run/$B; echo "GATE_RC=$?"
