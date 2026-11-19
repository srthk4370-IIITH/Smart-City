# start_auto.ps1: start the baton loop detached in WSL plus a hidden keepalive wsl.exe, so .wslconfig instanceIdleTimeout
# (15 s) does not shut WSL down when no terminal is open. Stop the loop: wsl touch <baton>/STOP (the keepalive ends with it).
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-06_4b_local\baton\start_auto.ps1
$B = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/baton'
$P = '/mnt/c/Users/hp/Desktop/qidk/proofs'
wsl.exe bash -c "rm -f $B/STOP; bash $P/detach.sh baton_r3 $B/baton_auto.sh"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash $P/2026-10-29_rsn_v3/distill_laptop/keepalive.sh baton_r3 720"
Write-Output "baton loop started (log: wsl ~/detached/baton_r3.log; status: [baton] in proofs/2026-10-29_rsn_v3/kaggle/STATUS.md)"
