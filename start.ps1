# start.ps1: start (or resume) the laptop GPU training (rsn_v3: 2B training + 4B adapter watch).
# Resumes from the last checkpoint. Safe to run twice (says ALREADY RUNNING). Stop with stop.ps1.
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/train_ctl.sh start
if ($LASTEXITCODE -eq 0) {
  # keeps WSL alive while the job runs (WSL otherwise shuts down 15 s after the last window closes)
  Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh rsn3_laptop_chain 168"
}
