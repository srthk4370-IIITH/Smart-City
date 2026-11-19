# start_supervisor.ps1: launch the unattended supervisor (supervisor.sh) detached in WSL + a hidden keepalive wsl.exe.
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\start_supervisor.ps1
# Stop: wsl touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/SUP_STOP . Status: AUTO_STATUS.md in this dir.
$H = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local'
wsl.exe bash -c "rm -f $H/SUP_STOP; p=`$(cat ~/detached/supervisor.pid 2>/dev/null); [ -n `"`$p`" ] && kill -0 `$p 2>/dev/null && echo 'supervisor already running' || bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh supervisor $H/supervisor.sh"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh supervisor 720"
Write-Output "supervisor started (status: proofs\2026-11-06_4b_local\AUTO_STATUS.md)"
