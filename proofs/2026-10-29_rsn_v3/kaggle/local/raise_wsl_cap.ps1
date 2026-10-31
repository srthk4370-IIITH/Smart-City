# Owner 2026-10-30: raise the WSL memory cap (5GB -> 7GB) once the laptop chat distillation is done, before the 2B training.
# Runs on Windows (hidden), because `wsl --shutdown` kills everything inside WSL. Waits for kaggle/chain/distill.done
# (the chain's marker: distilled file final), then edits .wslconfig, restarts WSL and relaunches laptop_chain + keepalive.
# The chain's steps are idempotent (markers), and its GPU_LOCK line is taken over by the relaunched chain. Gives up after 30 h.
$P = 'C:\Users\hp\Desktop\qidk\proofs\2026-10-29_rsn_v3'
$Log = "$P\kaggle\local\raise_wsl_cap.log"
function Say($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -Append -Encoding utf8 $Log }
Say "watcher start (pid $PID): waiting for kaggle\chain\distill.done"
$end = (Get-Date).AddHours(30)
while (-not (Test-Path "$P\kaggle\chain\distill.done")) {
    if ((Get-Date) -gt $end) { Say "gave up after 30 h: cap unchanged"; exit 1 }
    if (Test-Path "$P\kaggle\local\STOP_raise_cap") { Say "STOP file: cap unchanged"; exit 0 }
    Start-Sleep 60
}
Start-Sleep 20
$cfg = 'C:\Users\hp\.wslconfig'
(Get-Content $cfg) -replace '^memory=5GB$', 'memory=7GB' | Set-Content -Encoding ascii $cfg
Say "distill.done seen; .wslconfig now: $((Get-Content $cfg | Select-String '^memory=') -join ' ')"
wsl --shutdown
Start-Sleep 15
wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn3_laptop_chain /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle/local/laptop_chain.sh | Out-File -Append -Encoding utf8 $Log
Start-Process -WindowStyle Hidden -FilePath wsl.exe -ArgumentList "bash /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/distill_laptop/keepalive.sh rsn3_laptop_chain 96"
Start-Sleep 30
Say "after restart: $((wsl bash -c 'free -m | sed -n 2p; pgrep -af laptop_chain.sh | head -1') -join ' | ')"
Say "watcher done"
