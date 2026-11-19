# stop.ps1: cleanly stop the laptop GPU training (4B r3; saves a checkpoint, frees the GPU). Resume later with start.ps1.
# Waits up to 15 min. Status only: wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/ctl_4b.sh status
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/ctl_4b.sh stop
