# RAM guard for 3e: every 30 s; if Windows free RAM < 1500 MB, first drop the WSL page cache, then (if still low)
# stop the resumable host eval (host_eval3e.py + its llama-server). Training is never touched. Ends when
# %LOCALAPPDATA%\sce_train\STOP_RAMGUARD exists. Log: %LOCALAPPDATA%\sce_train\ramguard3e.log
$log = "$env:LOCALAPPDATA\sce_train\ramguard3e.log"
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\sce_train" | Out-Null
Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]"0x80000041")   # keep the system awake while the guard runs
while (-not (Test-Path "$env:LOCALAPPDATA\sce_train\STOP_RAMGUARD")) {
    $f = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
    if ($f -lt 1500) {
        wsl.exe -d Ubuntu -u root -- sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
        Start-Sleep 15
        $f2 = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
        Add-Content $log "$(Get-Date -f s) low RAM $f MB -> after cache drop $f2 MB"
        if ($f2 -lt 1500) {
            wsl.exe -d Ubuntu -- sh -c 'pkill -f "host_eval3e.py run"; sleep 2; pkill -f "build-host/bin/llama-server"'
            Add-Content $log "$(Get-Date -f s) stopped host eval (resumable)"
        }
    }
    Start-Sleep 30
}
