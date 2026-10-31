# stop.ps1: cleanly stop the laptop GPU training (saves a checkpoint, frees the GPU). Resume later with start.ps1.
# Waits up to 15 min. Status only: wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/train_ctl.sh status
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/train_ctl.sh stop
