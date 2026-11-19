# start_runner.ps1: start the agt_v3 runner detached in WSL plus a hidden keepalive wsl.exe (.wslconfig instanceIdleTimeout would
# otherwise stop WSL and the loop). The runner itself WAITS for proofs/2026-11-13_v3_data/APPROVED_AGENTS before it uploads or
# trains anything. Stop: wsl touch /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/STOP
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\proofs\2026-11-13_v3_train\agt\start_runner.ps1
$A = '/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt'
$P = '/mnt/c/Users/hp/Desktop/qidk/proofs'
wsl.exe bash -c "rm -f $A/STOP; bash $P/detach.sh agt_v3 $A/runner.sh"
Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "bash $P/2026-10-29_rsn_v3/distill_laptop/keepalive.sh agt_v3 240"
Write-Output "agt_v3 runner started (log: wsl ~/detached/agt_v3.log; status: proofs/2026-11-13_v3_train/agt/STATUS.md)"
