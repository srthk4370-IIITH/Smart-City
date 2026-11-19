# stop_r4.ps1: clean stop of the r4 top-up. The supervisor goes first (SUP_STOP), otherwise it restarts training within 10 min;
# then training saves ckpt_latest at its next step and exits; a running post chain / gate stops at its next check (post/STOP).
# start_r4.ps1 resumes everything (it removes SUP_STOP; remove post/STOP by hand to resume a stopped post chain).
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-12_topup_r4\train\stop_r4.ps1 [-Post]
param([switch]$Post)
$T = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train'
wsl.exe touch $T/SUP_STOP
if ($Post) { wsl.exe touch $T/post/STOP }
wsl.exe bash $T/ctl_r4.sh stop
