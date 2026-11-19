# Board has no Wi-Fi: carry its network calls over USB (adb reverse) to laptop services. Re-run after a board/adb restart.
$Q = 'C:\Users\hp\Desktop\qidk'; $A = "$Q\Code\platform-tools\adb.exe"
# --- watchdog (2026-11-19): every 30 s, while the board is attached, re-apply any missing `adb reverse` port. One instance (pid lock).
# Start hidden (once, after the lines above):  Start-Process -WindowStyle Hidden powershell -ArgumentList '-NoProfile','-File',"$Q\proofs\2026-11-16_phase1\tools\usb_relay.ps1",'-Watch'
if ($args -contains '-Watch') {
  $lock = "$Q\proofs\2026-11-16_phase1\relay_watchdog.pid"; $log = "$Q\proofs\2026-11-16_phase1\relay_watchdog.log"
  if (Test-Path $lock) { $old = Get-Process -Id ([int](Get-Content $lock -ErrorAction SilentlyContinue)) -ErrorAction SilentlyContinue; if ($old -and $old.Id -ne $PID) { exit } }
  Set-Content $lock $PID
  while ($true) {
    try {
      if ((& $A get-state 2>$null) -eq 'device') {
        $have = (& $A reverse --list 2>$null) -join ' '
        foreach ($p in 9999,8787,8094,8092,1883) {
          if ($have -notmatch "tcp:$p\b") { & $A reverse "tcp:$p" "tcp:$p" | Out-Null; Add-Content $log ("{0} repaired tcp:{1}" -f (Get-Date -Format s), $p) }
        }
      }
    } catch { Add-Content $log ("{0} error {1}" -f (Get-Date -Format s), $_) }
    Start-Sleep -Seconds 30
  }
}

Start-Process -WindowStyle Hidden wsl.exe -ArgumentList "-u root mosquitto -c /etc/mosquitto/mosquitto.conf"   # MQTT broker (WSL, 0.0.0.0:1883, anonymous, persistent)
Start-Process -WindowStyle Hidden python -ArgumentList "$Q\proofs\2026-11-16_phase1\tools\tcp_proxy.py 9999 10.2.203.214 9999"
Start-Process -WindowStyle Hidden python -ArgumentList "$Q\Code\smart-city-edge-agent\app\tools\heartbeat_monitor.py --port 8787 --dead-s 300"
Start-Process -WindowStyle Hidden python -ArgumentList "$Q\proofs\2026-11-16_phase1\tools\alert_sink.py 8094"
foreach ($p in 9999,8787,8094,8092,1883) { & $A reverse "tcp:$p" "tcp:$p" | Out-Null }
& $A reverse --list
