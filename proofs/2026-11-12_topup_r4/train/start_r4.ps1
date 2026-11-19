# start_r4.ps1: start (or resume) the unattended r4 top-up: training (ctl_r4.sh) + supervisor_r4 (restarts, post chain,
# STRICT gate) + hidden keepalives. Safe to run twice. Status: AUTO_STATUS_r4.md in this dir. Stop: stop_r4.ps1.
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-12_topup_r4\train\start_r4.ps1
$T = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/train'
$P = '/mnt/c/Users/hp/Desktop/qidk/proofs'
wsl.exe bash $T/ctl_r4.sh start
wsl.exe bash -c "rm -f $T/SUP_STOP; p=`$(cat ~/detached/supervisor_r4.pid 2>/dev/null); [ -n `"`$p`" ] && kill -0 `$p 2>/dev/null && echo 'supervisor_r4 already running' || bash $P/detach.sh supervisor_r4 $T/supervisor_r4.sh"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash $P/2026-10-29_rsn_v3/distill_laptop/keepalive.sh supervisor_r4 720"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash $P/2026-10-29_rsn_v3/distill_laptop/keepalive.sh rsn3_4b_r4topup 168"
Write-Output "r4 top-up started (status: proofs\2026-11-12_topup_r4\train\AUTO_STATUS_r4.md)"
