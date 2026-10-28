# 3f RAM guard (owner on the laptop): every 20 s, if Windows free RAM < PauseMB (default 2048): drop the WSL page cache (most of the
# WSL footprint during GGUF builds is page cache of the model shards); if still below it, PAUSE (SIGSTOP) the 3f jobs
# (pipe/queue shells, host eval + llama-server, GGUF builds, training, anchors) via pause3f.sh. While paused the cache
# is dropped every cycle; resume (SIGCONT) at >= ResumeMB (3072). Runs next to the 3e ramguard.ps1 (1.5 GB, stops evals).
# Ends when %LOCALAPPDATA%\sce_train\STOP_RAMGUARD3F exists (jobs resumed first). Log: %LOCALAPPDATA%\sce_train\ramguard3f.log
param([int]$PauseMB = 2048, [int]$ResumeMB = 3072)
$log = "$env:LOCALAPPDATA\sce_train\ramguard3f.log"
$ps3f = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup3f/pause3f.sh"
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\sce_train" | Out-Null
function Free { [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024) }
function Drop { wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' }
$paused = $false
Add-Content $log "$(Get-Date -f s) start (pause < $PauseMB MB after cache drop, resume >= $ResumeMB MB)"
while (-not (Test-Path "$env:LOCALAPPDATA\sce_train\STOP_RAMGUARD3F")) {
    $f = Free
    if ($f -lt $PauseMB) {
        Drop; Start-Sleep 8; $f2 = Free
        if ($f2 -lt $PauseMB -and -not $paused) {
            wsl.exe -d Ubuntu -- bash $ps3f STOP
            $paused = $true
            Add-Content $log "$(Get-Date -f s) PAUSE: free $f MB, after cache drop $f2 MB"
        } elseif (-not $paused) {
            Add-Content $log "$(Get-Date -f s) cache drop: $f -> $f2 MB"
        }
    } elseif ($f -ge $ResumeMB -and $paused) {
        wsl.exe -d Ubuntu -- bash $ps3f CONT
        $paused = $false
        Add-Content $log "$(Get-Date -f s) RESUME: free $f MB"
    }
    Start-Sleep 20
}
wsl.exe -d Ubuntu -- bash $ps3f CONT
Add-Content $log "$(Get-Date -f s) stop"
