# Final chain (2026-10-21 evening, user away, FULL mode):
#   1. GGUF from agents_v2_topup2 checkpoint-500 (post_topup.sh agents_v2_topup2 v2t) under an offline 11 GB / 4-core
#      WSL profile; writes ~/smartcity_runs/agents_v2_topup2/post/STATUS = "done <md5>" or "failed <reason>".
#   2. Only if 1 succeeded: hands over to run_topup.ps1 -RunName agents_v2_topup3b -Tag v2t3b (full mode), which trains
#      phase 2b and builds ft_v2t3b_q4_0.gguf only on a passing step, then restores everything.
#      If 1 failed: restores the user's .wslconfig / power / lid settings and stops.
# Keep-awake (system + display), AC timeouts never, lid close on AC = do nothing while running.
# Launch detached: Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine='powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<this file>"'}
$ErrorActionPreference = "Continue"
$Root = "$env:LOCALAPPDATA\sce_train"
$Log = "$Root\final_chain.log"
$Cfg = "$env:USERPROFILE\.wslconfig"
$CfgSaved = "$Root\wslconfig.user_backup"
$PowerSaved = "$Root\power_user_backup.json"
$LidSaved = "$Root\lid_user_backup.txt"
$Here = "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/topup"
function Log($m) { Add-Content -Path $Log -Value ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $m) }
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "*final_chain.ps1*" }
if ($others) { exit 0 }
Log "=== final chain start (pid $PID)"
Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]"0x80000043")
if (-not (Test-Path $PowerSaved)) {
    $q = { param($sub,$set) ((powercfg /q SCHEME_CURRENT $sub $set) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value }
    @{ monitor = [Convert]::ToInt32((& $q SUB_VIDEO VIDEOIDLE), 16); standby = [Convert]::ToInt32((& $q SUB_SLEEP STANDBYIDLE), 16) } | ConvertTo-Json | Set-Content $PowerSaved }
powercfg /change monitor-timeout-ac 0; powercfg /change standby-timeout-ac 0
if (-not (Test-Path $LidSaved)) {
    ((powercfg /qh SCHEME_CURRENT SUB_BUTTONS LIDACTION) | Select-String "Current AC Power Setting Index: (0x[0-9a-f]+)").Matches[0].Groups[1].Value | Set-Content $LidSaved }
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0; powercfg /setactive SCHEME_CURRENT
if (-not (Test-Path $CfgSaved)) { Copy-Item $Cfg $CfgSaved -Force; Log "saved user .wslconfig" }
@"
[wsl2]
# FULL offline profile written by final_chain.ps1 (GGUF build); the user's file is restored from $CfgSaved at the end.
memory=11GB
swap=6GB
processors=4
vmIdleTimeout=60000
networkingMode=none

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
"@ | Set-Content -Path $Cfg -Encoding ascii
wsl --shutdown; Start-Sleep -Seconds 8
Log "full offline profile applied (WSL 11 GB, 4 cores, networking none); keep-awake on, lid do-nothing"
# auto-resume of this chain at logon until it hands over / finishes
$Resume = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\sce_resume_final_chain.cmd"
Set-Content -Path $Resume -Encoding ascii -Value ('@start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')

$ok = $false
for ($a = 1; $a -le 2 -and -not $ok; $a++) {
    Log "post_topup.sh agents_v2_topup2 v2t (attempt $a)"
    $p = Start-Process -FilePath "wsl.exe" -ArgumentList "-d Ubuntu -- bash $Here/post_topup.sh agents_v2_topup2 v2t" -PassThru -WindowStyle Hidden -Wait
    $ok = ((wsl -d Ubuntu -- bash -c "test -f ~/smartcity_runs/agents_v2_topup2/post/DONE && test -s ~/smartcity_runs/agents_v2_topup2/post/gguf/ft_v2t_q4_0.gguf.md5 && echo yes") -join '') -eq 'yes'
    Log "post exit $($p.ExitCode), ok=$ok"
}
if ($ok) {
    $md5 = (wsl -d Ubuntu -- bash -c "cut -d' ' -f1 ~/smartcity_runs/agents_v2_topup2/post/gguf/ft_v2t_q4_0.gguf.md5") -join ''
    $match = (wsl -d Ubuntu -- bash -c "grep -A1 tensor_type_match_vs_deployed ~/smartcity_runs/agents_v2_topup2/post/gguf/gguf_manifest.json | grep -o 'true\|false'") -join ''
    wsl -d Ubuntu -- bash -c "echo 'done $md5' > ~/smartcity_runs/agents_v2_topup2/post/STATUS"
    Log "GGUF DONE: md5 $md5, tensor types match deployed: $match"
    Remove-Item $Resume -Force -ErrorAction SilentlyContinue
    # hand over: run_topup.ps1 keeps the saved user settings (it only saves when no backup exists) and restores them at its end
    $f = "C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\training\v2\topup\run_topup.ps1"
    $r = Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine="powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$f`" -RunName agents_v2_topup3b -Tag v2t3b"}
    Log "phase 2b supervisor launched (rv $($r.ReturnValue), pid $($r.ProcessId)); final chain ends, keep-awake handed over"
} else {
    $why = (wsl -d Ubuntu -- bash -c "cat ~/smartcity_runs/agents_v2_topup2/post/STATUS 2>/dev/null") -join ' '
    wsl -d Ubuntu -- bash -c "echo 'failed $($why -replace "'", '')' > ~/smartcity_runs/agents_v2_topup2/post/STATUS"
    Log "GGUF FAILED: $why - restoring settings, phase 2b NOT started"
    if (Test-Path $CfgSaved) { Copy-Item $CfgSaved $Cfg -Force; Remove-Item $CfgSaved -Force }
    wsl --shutdown
    if (Test-Path $PowerSaved) { $pv = Get-Content $PowerSaved -Raw | ConvertFrom-Json
        powercfg /change monitor-timeout-ac ([int]($pv.monitor / 60)); powercfg /change standby-timeout-ac ([int]($pv.standby / 60)); Remove-Item $PowerSaved -Force }
    if (Test-Path $LidSaved) { powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION ([Convert]::ToInt32((Get-Content $LidSaved).Trim(), 16)); powercfg /setactive SCHEME_CURRENT; Remove-Item $LidSaved -Force }
    Remove-Item $Resume -Force -ErrorAction SilentlyContinue
    [void][W.P]::SetThreadExecutionState([uint32]"0x80000000")
    Log "settings restored"
}
Log "=== final chain end"
