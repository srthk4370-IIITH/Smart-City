# Windows-side trigger for the v2 post-training pipeline.
# Waits until the training supervisor (run_v2.ps1) has finished - supervisor.log says "TRAINING COMPLETE" and
# "supervisor end", and it has shut WSL down and restored the user's .wslconfig - then starts WSL with the
# user's own config (12 GB) and runs post_all.sh. Keeps the PC awake (SetThreadExecutionState, no settings
# changed) while it runs; the lid must stay open (a closed lid enters Modern Standby, HANDBOOK 2.40).
# Launch detached so it survives any terminal:
#   Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine='powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<this file>"'}
$ErrorActionPreference = 'Continue'
$dir = Join-Path $env:LOCALAPPDATA 'sce_train'
$log = Join-Path $dir 'post_launcher.log'
$sup = Join-Path $dir 'supervisor.log'
function Log($m) { "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $m | Add-Content -Encoding utf8 $log }

Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]'0x80000001')   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
Log "=== post launcher start (pid $PID)"

while ($true) {
    $t = if (Test-Path $sup) { Get-Content $sup -Raw } else { '' }
    $complete = $t -match 'TRAINING COMPLETE'
    $ended = $false
    if ($complete) { $ended = ($t.Substring($t.LastIndexOf('TRAINING COMPLETE')) -match 'supervisor end') }
    if ($complete -and $ended) { break }
    Log "waiting for training: complete=$complete supervisor_end=$ended"
    Start-Sleep -Seconds 300
}
Log "training complete and supervisor ended; starting WSL post pipeline"
$sh = '/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post/post_all.sh'
for ($attempt = 1; $attempt -le 3; $attempt++) {
    $p = Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', 'Ubuntu', '--', 'bash', $sh) -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $dir 'post_wsl.out') -RedirectStandardError (Join-Path $dir 'post_wsl.err')
    Log "post_all.sh exited with code $($p.ExitCode) (attempt $attempt)"
    $done = (wsl.exe -d Ubuntu -- bash -c 'test -f ~/smartcity_runs/agents_v2/post/DONE && echo yes') -join ''
    if ($done -eq 'yes') { break }
    Start-Sleep -Seconds 60   # every step is resumable: a retry continues where it stopped
}
[void][W.P]::SetThreadExecutionState([uint32]'0x80000000')
Log "=== post launcher end"
