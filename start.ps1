# start.ps1: start (or resume) the laptop GPU training: Qwen3.5-4B QLoRA, dataset r3 (proofs/2026-11-06_4b_local, ctl_4b.sh).
# Resumes from the last checkpoint. Safe to run twice (says ALREADY RUNNING). Stop with stop.ps1.
# Status only: wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/ctl_4b.sh status
# (Old 2B r2 chain: wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/train_ctl.sh start)
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/ctl_4b.sh start
if ($LASTEXITCODE -eq 0) {
  # keeps WSL alive while the job runs (WSL otherwise shuts down 15 s after the last window closes)
  Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh rsn3_4b_r3 168"
}
