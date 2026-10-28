# Supervisor for the v2 domain-agent training (RETRAIN_V2_SPEC.md). Runs on its own (not tied to any
# terminal or assistant session): start it detached with
#   Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File <this file>'
# What it does:
#   * gives WSL (where training runs) most of the RAM while training, and restores the user's own .wslconfig
#     and returns the RAM to Windows when training stops or completes;
#   * keeps the laptop awake;
#   * runs session_v2.sh with no session limit; on a crash it resumes from the newest checkpoint (<= 20 retries);
#   * guardrails, checked every minute: on battery below 40 %, or C: below 3 GB free -> clean stop
#     (checkpoint first); the GPU thermal pause lives in the trainer (pause at 81 C, resume at 73 C);
#   * clean stop on request: create the file named in $StopFlag (Windows side) -> it writes STOP into the run dir,
#     the trainer checkpoints and exits, and this script restores the resources.
# Log: $Log. Status for humans/assistants: $Status (one line, overwritten every minute).

param([double]$Hours = 0, [switch]$Background, [switch]$Medium)   # -Medium: user works lightly (browser + editor): WSL 8 GB / 3 cores, full GPU   # -Background: share the laptop with the user (less RAM/CPU, GPU ~50 % duty, low priority)   # >0: stop cleanly after this many hours (a reboot inside the window resumes; after it, not)
$ErrorActionPreference = "Continue"
$Root     = "$env:LOCALAPPDATA\sce_train"
New-Item -ItemType Directory -Force $Root | Out-Null
$Log      = "$Root\supervisor.log"
$Status   = "$Root\status.txt"
$StopFlag = "$Root\STOP_TRAINING"
$WslUser  = "hp_srthk4370"
$RunDirW  = "\\wsl.localhost\Ubuntu\home\$WslUser\smartcity_runs\agents_v2"
$Start    = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/start_v2.sh"
$Cfg      = "$env:USERPROFILE\.wslconfig"
$CfgSaved = "$Root\wslconfig.user_backup"

function Log($m) { $l = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $m; Add-Content -Path $Log -Value $l }

# --- keep awake (system + away mode; display may sleep)
Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
# ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED: on this laptop the display
# timing out leads into Modern Standby, which froze WSL from 03:08 to 08:50 on 2026-10-18 (event 506), so the
# display must be held too (it may dim). AC timeouts are also set to never and restored at the end.
[void][W.P]::SetThreadExecutionState([uint32]"0x80000043")
$PowerSaved = "$Root\power_user_backup.json"
function Get-AcTimeouts {
    $q = { param($sub,$set) ((powercfg /q SCHEME_CURRENT $sub $set) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value }
    @{ monitor = [Convert]::ToInt32((& $q SUB_VIDEO VIDEOIDLE), 16); standby = [Convert]::ToInt32((& $q SUB_SLEEP STANDBYIDLE), 16) }
}
if (-not (Test-Path $PowerSaved)) { Get-AcTimeouts | ConvertTo-Json | Set-Content $PowerSaved }
powercfg /change monitor-timeout-ac 0; powercfg /change standby-timeout-ac 0
# lid close on AC = Do nothing while training: with the user's "Sleep" it entered Modern Standby and froze WSL
# (2026-10-18 01:12 and 16:18, "Reason: Lid"). Saved and restored with the timeouts.
$LidSaved = "$Root\lid_user_backup.txt"
if (-not (Test-Path $LidSaved)) {
    ((powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value | Set-Content $LidSaved }
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; powercfg /setactive SCHEME_CURRENT
Log ("lid close on AC set to Do nothing (saved: {0})" -f (Get-Content $LidSaved))
Log ("AC screen-off and sleep timeouts set to never (saved: {0})" -f (Get-Content $PowerSaved -Raw).Trim())

# --- resources: WSL gets the machine while training
function Set-TrainingResources {
    if (-not (Test-Path $CfgSaved)) { Copy-Item $Cfg $CfgSaved -Force; Log "saved user .wslconfig to $CfgSaved" }
    @"
[wsl2]
# TRAINING profile written by run_v2.ps1; the user's own file is restored from $CfgSaved when training stops.
memory=$(if ($Background) { "6GB" } elseif ($Medium) { "8GB" } else { "11GB" })
swap=$(if ($Background) { "4GB" } else { "6GB" })
processors=$(if ($Background) { 2 } elseif ($Medium) { 3 } else { 4 })
vmIdleTimeout=60000
# No WSL networking while training: the 2026-10-17 05:45 blue screen (bugcheck 0xD1) was in vfpext.sys, the
# Hyper-V virtual switch filter WSL networking runs on. Training is fully offline; the user's mirrored mode
# comes back with their own file when training stops or completes.
networkingMode=none

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
"@ | Set-Content -Path $Cfg -Encoding ascii
    wsl --shutdown; Start-Sleep -Seconds 8
    Log ("training resources applied ({0})" -f $(if ($Background) { "BACKGROUND: WSL 6 GB, swap 4 GB, 2 cores, full GPU, low priority" } elseif ($Medium) { "MEDIUM: WSL 8 GB, 3 cores, full GPU" } else { "WSL 11 GB, swap 6 GB, 4 cores, full GPU" }))
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

function Read-SessionStatus {
    try { return Get-Content "$RunDirW\session_status.json" -Raw | ConvertFrom-Json } catch { return $null }
}

# single instance: a second copy (e.g. the logon auto-resume while one already runs) exits at once
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*run_v2.ps1*" }
if ($others) { exit 0 }
# auto-resume after a crash/reboot: a Startup-folder entry relaunches this script at logon until training ends
$Resume = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\sce_resume_training.cmd"
Set-Content -Path $Resume -Encoding ascii -Value ('@start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
Log "=== supervisor start (pid $PID); logon auto-resume entry present"
$DeadlineFile = "$Root\deadline.txt"
if ($Hours -gt 0) { (Get-Date).AddHours($Hours).ToString("o") | Set-Content $DeadlineFile }
$Deadline = if (Test-Path $DeadlineFile) { [datetime](Get-Content $DeadlineFile) } else { $null }
if ($Deadline -and (Get-Date) -gt $Deadline) {
    Log "session window ended at ${Deadline} - not resuming"; Remove-Item $Resume -Force -ErrorAction SilentlyContinue; exit 0 }
if ($Deadline) { Log "session window: stop at $Deadline" }
Remove-Item $StopFlag -Force -ErrorAction SilentlyContinue
function TrainingAlive { (wsl -d Ubuntu -- bash -c "pgrep -f '^python train_v2.py' >/dev/null && echo yes") -eq "yes" }
# a trainer that is already running (e.g. this supervisor was replaced) is attached to, never restarted
$attach = TrainingAlive
if ($attach) { Log "training already running: attaching without restarting it" } else { Set-TrainingResources }

# GPU duty for the trainer (re-read live by train_v2.py DutyThrottle): 0.5 in background mode, full otherwise
# no GPU duty-cycling (user, 2026-10-18): background mode = less RAM/cores + low priority, full GPU speed`ntry { Remove-Item "$RunDirW\DUTY" -Force -ErrorAction SilentlyContinue } catch {}
$retries = 0
$stopWhy = $null
while ($true) {
    if ($attach) { $p = $null } else {
    Log "launching training session (attempt $($retries + 1))"
    # a wrapper with no arguments: Start-Process joins -ArgumentList with spaces and would split a "bash -lc" string
    $p = Start-Process -FilePath "wsl.exe" -ArgumentList "-d Ubuntu -- bash $Start" -PassThru -WindowStyle Hidden
    }
    while (($p -and -not $p.HasExited) -or (-not $p -and (TrainingAlive))) {
        Start-Sleep -Seconds 60
        try {
        if ($Deadline -and (Get-Date) -gt $Deadline -and -not $stopWhy) { $stopWhy = "session window of $Hours h ended"; Request-Stop $stopWhy }
        # guardrails
        $b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
        if ($b -and $b.BatteryStatus -ne 2 -and $b.EstimatedChargeRemaining -lt 40 -and -not $stopWhy) {
            $stopWhy = "on battery at $($b.EstimatedChargeRemaining)%"; Request-Stop $stopWhy }
        # Windows must keep breathing room: WSL's page cache (model files) is released only slowly by itself
        $winFree = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
        if ($winFree -lt 2.5) { wsl -d Ubuntu -u root -- sh -c "sync; echo 1 > /proc/sys/vm/drop_caches"; Log ("Windows RAM {0:N1} GB free: dropped WSL page cache" -f $winFree) }
        if ($Background) { Get-Process vmmemWSL, vmmem -ErrorAction SilentlyContinue | ForEach-Object { try { if ($_.PriorityClass -ne "BelowNormal") { $_.PriorityClass = "BelowNormal" } } catch {} } }
        $free = (Get-PSDrive C).Free / 1GB
        if ($free -lt 3 -and -not $stopWhy) { $stopWhy = ("C: only {0:N1} GB free" -f $free); Request-Stop $stopWhy }
        if ((Test-Path $StopFlag) -and -not $stopWhy) { $stopWhy = "user stop flag"; Request-Stop $stopWhy }
        $tail = (Get-Content "$RunDirW\train.log" -Tail 1 -ErrorAction SilentlyContinue)
        $gpu = (& nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used --format=csv,noheader 2>$null)
        Set-Content -Path $Status -Value ("{0:HH:mm} running | GPU {1} | Win RAM {4:N1} GB free | C: {2:N1} GB free | {3}" -f (Get-Date), $gpu, $free, $tail, $winFree)
        } catch { Log "monitor error (continuing): $_" }   # e.g. WMI not ready right after a sleep/wake
    }
    $attach = $false
    $st = Read-SessionStatus
    if ($st -and $st.done) { Log "TRAINING COMPLETE at step $($st.step)/$($st.max_steps)"; break }
    if ($stopWhy) { Log "stopped cleanly ($stopWhy) at step $($st.step)/$($st.max_steps)"; break }
    $retries++
    Log "session exited without completing (exit $(if ($p) { $p.ExitCode } else { 'n/a, attached' })); last status: $($st | ConvertTo-Json -Compress)"
    if ($retries -ge 20) { Log "giving up after 20 retries"; break }
    Start-Sleep -Seconds 90   # let the GPU cool / WSL settle, then resume from the newest checkpoint
}
Restore-Resources
Remove-Item $Resume, $DeadlineFile, $StopFlag -Force -ErrorAction SilentlyContinue
Log "logon auto-resume entry removed"
Set-Content -Path $Status -Value ("{0:HH:mm} supervisor finished: {1}" -f (Get-Date), $(if ($stopWhy) { "stopped ($stopWhy)" } elseif ($st -and $st.done) { "training complete" } else { "gave up / error - see $Log" }))
Log "=== supervisor end"


