# Supervisor for the v2 TOP-UP training (training/v2/topup), then its post pipeline. A parameterised copy of
# training/v2/run_v2.ps1 (the original is left unchanged). Runs on its own; launch detached with
#   Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine='powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<this file>"'}
# What it does:
#   * training profile for WSL (full mode: 11 GB, swap 6 GB, 4 cores) with networkingMode=none (the 2026-10-17
#     vfpext.sys blue screen); the user's .wslconfig is saved and restored at the end;
#   * keeps the laptop awake (system + display + away mode), AC screen-off / sleep = never, lid close on AC =
#     do nothing; all restored at the end;
#   * runs start_topup.sh; on a crash it resumes from the newest checkpoint (<= 10 retries);
#   * guardrails every minute: battery < 40 % (not charging), C: < 3 GB free, Windows RAM low (drops WSL page
#     cache); the GPU thermal pause lives in the trainer (76 / 68 C), the forgetting guard too (+3 % orig dev loss);
#   * clean stop: create %LOCALAPPDATA%\sce_train\STOP_TRAINING -> STOP in the run dir -> checkpoint + exit;
#   * when training completes (and the forgetting guard did not fire) runs post_topup.sh (merge, GGUF, imatrix,
#     Q4_0, tensor-type check, proofs) under the same offline profile, then restores everything.
# Log: %LOCALAPPDATA%\sce_train\supervisor_topup.log. One-line status: %LOCALAPPDATA%\sce_train\status_topup.txt
# Parameters: -RunName <dir under ~/smartcity_runs> (default agents_v2_topup; trainer extra args in <run>/train_args.txt)
#             -Background: share the laptop (WSL 6 GB / swap 4 GB / 2 cores, WSL process BelowNormal priority, full GPU)
# Post pipeline runs only if choice.json "passes" (orig dev <= +2 % AND targeted dev improved).
#             -Medium: WSL 8 GB / swap 6 GB / 3 cores, full GPU.  -Tag: GGUF name ft_<Tag>_q4_0.gguf (default v2t)
#             -WaitFor <run>: wait until that run's trainer exits, stop its supervisor (no GGUF for it), then pick the
#              start checkpoint from it (pick_init.py: passing step with the lowest original dev loss)
param([string]$RunName = "agents_v2_topup", [switch]$Background, [switch]$Medium, [string]$Tag = "v2t", [string]$WaitFor = "", [string]$Trainer = "train_topup.py")
$ErrorActionPreference = "Continue"
$Root     = "$env:LOCALAPPDATA\sce_train"
New-Item -ItemType Directory -Force $Root | Out-Null
$Log      = "$Root\supervisor_$RunName.log"
$Status   = "$Root\status_$RunName.txt"
$StopFlag = "$Root\STOP_TRAINING"
$WslUser  = "hp_srthk4370"
$RunDirW  = "\\wsl.localhost\Ubuntu\home\$WslUser\smartcity_runs\$RunName"
$Here     = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup"
$Start    = "$Here/start_topup.sh"
$Post     = "$Here/post_topup.sh"
$Cfg      = "$env:USERPROFILE\.wslconfig"
$CfgSaved = "$Root\wslconfig.user_backup"

function Log($m) { $l = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $m; Add-Content -Path $Log -Value $l }

# single instance
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*run_topup.ps1*-RunName $RunName*" }
if ($others) { exit 0 }
# phase 2b was cancelled by the coordinator (2026-10-21 19:05) in favour of a diagnosed phase 2c; final_chain.ps1 still
# hands over to it, so that hand-over ends here (settings backups are left for the next supervisor to restore)
if ($RunName -eq "agents_v2_topup3b") { Log "phase 2b cancelled (coordinator): not started"; exit 0 }

Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]"0x80000043")
$PowerSaved = "$Root\power_user_backup.json"
function Get-AcTimeouts {
    $q = { param($sub,$set) ((powercfg /q SCHEME_CURRENT $sub $set) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value }
    @{ monitor = [Convert]::ToInt32((& $q SUB_VIDEO VIDEOIDLE), 16); standby = [Convert]::ToInt32((& $q SUB_SLEEP STANDBYIDLE), 16) }
}
if (-not (Test-Path $PowerSaved)) { Get-AcTimeouts | ConvertTo-Json | Set-Content $PowerSaved }
powercfg /change monitor-timeout-ac 0; powercfg /change standby-timeout-ac 0
$LidSaved = "$Root\lid_user_backup.txt"
if (-not (Test-Path $LidSaved)) {
    ((powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value | Set-Content $LidSaved }
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; powercfg /setactive SCHEME_CURRENT
Log "=== top-up supervisor start (pid $PID)"
Log ("lid close on AC set to Do nothing (saved: {0}); AC screen-off/sleep never (saved: {1})" -f (Get-Content $LidSaved), (Get-Content $PowerSaved -Raw).Trim())

function Set-TrainingResources {
    if (-not (Test-Path $CfgSaved)) { Copy-Item $Cfg $CfgSaved -Force; Log "saved user .wslconfig to $CfgSaved" }
    @"
[wsl2]
# TOP-UP TRAINING profile written by run_topup.ps1; the user's own file is restored from $CfgSaved at the end.
memory=$(if ($script:PostMode) { "11GB" } elseif ($Background) { "6GB" } elseif ($Medium) { "8GB" } else { "11GB" })
swap=$(if ($Background) { "4GB" } else { "6GB" })
processors=$(if ($script:PostMode) { 4 } elseif ($Background) { 2 } elseif ($Medium) { 3 } else { 4 })
vmIdleTimeout=60000
# No WSL networking while training (2026-10-17 bugcheck 0xD1 in vfpext.sys). Training and post are offline.
networkingMode=none

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
"@ | Set-Content -Path $Cfg -Encoding ascii
    wsl --shutdown; Start-Sleep -Seconds 8
    Log ("training resources applied ({0}, networking none, full GPU)" -f $(if ($Background) { "BACKGROUND: WSL 6 GB, swap 4 GB, 2 cores, low priority" } elseif ($Medium) { "MEDIUM: WSL 8 GB, swap 6 GB, 3 cores" } else { "WSL 11 GB, swap 6 GB, 4 cores" }))
}
function Restore-Resources {
    if (Test-Path $CfgSaved) { Copy-Item $CfgSaved $Cfg -Force; Remove-Item $CfgSaved -Force; Log "user .wslconfig restored" }
    wsl --shutdown
    if (Test-Path $PowerSaved) {
        $pv = Get-Content $PowerSaved -Raw | ConvertFrom-Json
        powercfg /change monitor-timeout-ac ([int]($pv.monitor / 60)); powercfg /change standby-timeout-ac ([int]($pv.standby / 60))
        Remove-Item $PowerSaved -Force; Log "AC screen-off / sleep timeouts restored" }
    if (Test-Path $LidSaved) {
        powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION ([Convert]::ToInt32((Get-Content $LidSaved).Trim(), 16)); powercfg /setactive SCHEME_CURRENT
        Remove-Item $LidSaved -Force; Log "lid close action restored" }
    [void][W.P]::SetThreadExecutionState([uint32]"0x80000000")
    Log "WSL shut down: RAM returned to Windows; keep-awake released"
}
function Request-Stop($why) {
    Log "STOP requested: $why"
    try { New-Item -ItemType File -Force "$RunDirW\STOP" | Out-Null } catch { Log "could not write STOP into run dir: $_" }
}
function Read-SessionStatus { try { return Get-Content "$RunDirW\session_status.json" -Raw | ConvertFrom-Json } catch { return $null } }
function TrainingAlive { (wsl -d Ubuntu -- bash -c "pgrep -f '^python train_topup(_c)?[.]py --out /home/$WslUser/smartcity_runs/$RunName ' >/dev/null && echo yes") -eq "yes" }
function Guard {   # returns a stop reason or $null; refreshes the status line
    try {
        $b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
        if ($b -and $b.BatteryStatus -ne 2 -and $b.EstimatedChargeRemaining -lt 40) { return "on battery at $($b.EstimatedChargeRemaining)%" }
        $winFree = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
        if ($winFree -lt 2.5) { wsl -d Ubuntu -u root -- sh -c "sync; echo 1 > /proc/sys/vm/drop_caches"; Log ("Windows RAM {0:N1} GB free: dropped WSL page cache" -f $winFree) }
        if ($Background) { Get-Process vmmemWSL, vmmem -ErrorAction SilentlyContinue | ForEach-Object { try { if ($_.PriorityClass -ne "BelowNormal") { $_.PriorityClass = "BelowNormal" } } catch {} } }
        $free = (Get-PSDrive C).Free / 1GB
        if ($free -lt 3) { return ("C: only {0:N1} GB free" -f $free) }
        if (Test-Path $StopFlag) { return "user stop flag" }
        $tail = (Get-Content "$RunDirW\train.log" -Tail 1 -ErrorAction SilentlyContinue)
        $gpu = (& nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used --format=csv,noheader 2>$null)
        Set-Content -Path $Status -Value ("{0:HH:mm} running | GPU {1} | Win RAM {4:N1} GB free | C: {2:N1} GB free | {3}" -f (Get-Date), $gpu, $free, $tail, $winFree)
    } catch { Log "monitor error (continuing): $_" }
    return $null
}

$Resume = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\sce_resume_$RunName.cmd"
Set-Content -Path $Resume -Encoding ascii -Value ('@start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -RunName ' + $RunName + ' -Tag ' + $Tag + ' -Trainer ' + $Trainer + $(if ($WaitFor) { ' -WaitFor ' + $WaitFor } else { '' }) + $(if ($Background) { ' -Background' } elseif ($Medium) { ' -Medium' } else { '' }))
Log "logon auto-resume entry present ($Resume)"
Remove-Item $StopFlag -Force -ErrorAction SilentlyContinue
$attach = TrainingAlive
if ($WaitFor -and -not $attach) {
    Log "waiting for the $WaitFor trainer to finish"
    while ((wsl -d Ubuntu -- bash -c "pgrep -f '^python train_topup(_c)?[.]py --out /home/$WslUser/smartcity_runs/$WaitFor ' >/dev/null && echo yes") -eq "yes") {
        Set-Content -Path $Status -Value ("{0:HH:mm} waiting for $WaitFor to finish" -f (Get-Date)); Start-Sleep -Seconds 60 }
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*run_topup.ps1*-RunName $WaitFor*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Log "stopped the $WaitFor supervisor (pid $($_.ProcessId)): no separate GGUF for it" }
    Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\sce_resume_topup.cmd", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\sce_resume_$WaitFor.cmd" -Force -ErrorAction SilentlyContinue
    wsl --shutdown; Start-Sleep -Seconds 5   # ends a post pipeline that supervisor may have started
    $pick = (wsl -d Ubuntu -- bash -c "~/venvs/train/bin/python $Here/pick_init.py $WaitFor $RunName 2>&1") -join ' '
    Log "start checkpoint: $pick"
}
if ($attach) { Log "training already running: attaching" } else { Set-TrainingResources }

$retries = 0
$stopWhy = $null
$st = Read-SessionStatus
while (-not ($st -and $st.done)) {
    if ($attach) { $p = $null } else {
        Log "launching top-up training session (attempt $($retries + 1))"
        $p = Start-Process -FilePath "wsl.exe" -ArgumentList "-d Ubuntu -- bash $Start $RunName $Trainer" -PassThru -WindowStyle Hidden
    }
    while (($p -and -not $p.HasExited) -or (-not $p -and (TrainingAlive))) {
        Start-Sleep -Seconds 60
        $why = Guard
        if ($why -and -not $stopWhy) { $stopWhy = $why; Request-Stop $stopWhy }
    }
    $attach = $false
    $st = Read-SessionStatus
    if ($st -and $st.done) { break }
    if ($stopWhy) { Log "stopped cleanly ($stopWhy) at step $($st.step)/$($st.max_steps)"; break }
    $retries++
    Log "session exited without completing (exit $(if ($p) { $p.ExitCode } else { 'n/a' })); last status: $($st | ConvertTo-Json -Compress)"
    if ($retries -ge 10) { Log "giving up after 10 retries"; break }
    Start-Sleep -Seconds 90
}
$result = "gave up / error - see $Log"
if ($st -and $st.done) {
    if ($st.forgetting_stop) { Log "training stopped by the FORGETTING GUARD at step $($st.step) (original dev loss > +3 %)" }
    else { Log "TRAINING COMPLETE at step $($st.step)/$($st.max_steps)" }
    if (-not $st.choice_passes) {
        Log "no evaluated step passes the run's rule: post pipeline NOT run; see choice.json"
        wsl -d Ubuntu -- bash -c "mkdir -p ~/smartcity_runs/$RunName/post && echo 'no passing step' > ~/smartcity_runs/$RunName/post/STATUS"
        $result = "step $($st.step), forgetting_stop=$($st.forgetting_stop), no passing step; no post"
        wsl -d Ubuntu -- bash -c "RUN=~/smartcity_runs/$RunName bash $Here/proofs_topup.sh" | Out-Null
    } else {
        Log "a passing step exists (choice.json); starting post pipeline"
        # post runs in the same (<= 8 GB) VM: post_topup.sh merges tensor-wise (merge_lowmem.py, bit-exact with merge_v2)
        Set-Content -Path $Status -Value ("{0:HH:mm} training complete; post pipeline running" -f (Get-Date))
        for ($a = 1; $a -le 2; $a++) {
            $pp = Start-Process -FilePath "wsl.exe" -ArgumentList "-d Ubuntu -- bash $Post $RunName $Tag" -PassThru -WindowStyle Hidden -Wait
            $done = (wsl -d Ubuntu -- bash -c "test -f ~/smartcity_runs/$RunName/post/DONE && echo yes") -join ''
            Log "post_topup.sh exited $($pp.ExitCode) (attempt $a), DONE=$done"
            if ($done -eq 'yes') { break }
            Start-Sleep -Seconds 60
        }
        $md5 = (wsl -d Ubuntu -- bash -c "cat ~/smartcity_runs/$RunName/post/gguf/ft_${Tag}_q4_0.gguf.md5 2>/dev/null") -join ''
        $result = if ($done -eq 'yes') { "training + post complete: $md5" } else { "training complete; post FAILED - see post/post_topup.log" }
        if ($done -eq 'yes') { wsl -d Ubuntu -- bash -c "echo 'done $($md5.Split(' ')[0])' > ~/smartcity_runs/$RunName/post/STATUS" }
        else { wsl -d Ubuntu -- bash -c "sed -i 's/^/failed /' ~/smartcity_runs/$RunName/post/STATUS" }
        Log "POST RESULT: $result"
    }
} elseif ($stopWhy) { $result = "stopped ($stopWhy)" }
Restore-Resources
Remove-Item $Resume, $StopFlag -Force -ErrorAction SilentlyContinue
Log "logon auto-resume entry removed"
Set-Content -Path $Status -Value ("{0:HH:mm} top-up supervisor finished: {1}" -f (Get-Date), $result)
Log "=== top-up supervisor end"
