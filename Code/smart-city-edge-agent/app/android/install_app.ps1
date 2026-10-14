# Installs the native "Smart City Edge" app on the QIDK (USB connected) and starts it.
#   powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\android\install_app.ps1
#   -Build         rebuild the APK first (WSL; needs ~/android-sdk + JDK 17, see build_apk.sh)
#   -ClearHistory  start with an empty incident list (do this before a demo)
# After this the laptop is not needed: the app supervises the backend (started through the QIDK's own adb
# daemon on 127.0.0.1:5555 so it may use the NPU), keeps it running and restarts it after every reboot.
# SECURITY: adb on this dev kit needs no authorization; keep the QIDK off untrusted Wi-Fi/LAN.
# Revert: adb root; adb shell setprop persist.adb.tcp.port ""; adb unroot
param([switch]$Build, [switch]$ClearHistory)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Adb = Join-Path $Here "..\..\..\platform-tools\adb.exe"
$Pkg = "com.iiith.smartcityedge"
$Apk = Join-Path $Here "out\SmartCityEdge.apk"

if ($Build -or -not (Test-Path $Apk)) {
    Write-Host "[1/6] Building APK (WSL) ..."
    # javac prints a deprecation note on stderr; under "Stop" PowerShell would treat it as a failure
    $ErrorActionPreference = "Continue"
    wsl -d Ubuntu -- bash -lc "bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/build.sh && bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/app/android/build_apk.sh 2>&1" | Select-Object -Last 2
    if ($LASTEXITCODE -ne 0) { throw "APK build failed" }
    $ErrorActionPreference = "Stop"
} else { Write-Host "[1/6] Using existing APK $Apk" }

& $Adb get-state | Out-Null
Write-Host "[2/6] Stopping the old adb-started backend (the app runs its own) ..."
& $Adb shell "pkill -x edge-agent" 2>$null | Out-Null   # the app starts a fresh one
if ($ClearHistory) { & $Adb shell "rm -f /data/local/tmp/smart_city_edge/state/incidents.jsonl"; Write-Host "      incident history cleared" }

Write-Host "[3/6] Installing app ..."
& $Adb install -r -g $Apk | Select-Object -Last 1

Write-Host "[4/6] Enabling on-device adb loopback (lets the app start the NPU backend as shell user) ..."
if ((& $Adb shell "getprop persist.adb.tcp.port").Trim() -ne "5555") {
    & $Adb root | Out-Null; Start-Sleep 4; & $Adb wait-for-device
    & $Adb shell "setprop persist.adb.tcp.port 5555"
    & $Adb unroot | Out-Null; Start-Sleep 5; & $Adb wait-for-device
}
& $Adb shell "am force-stop $Pkg; run-as $Pkg rm -rf files/genie_bundle files/genie_bundle_ft files/dsp" 2>$null | Out-Null
Write-Host "      protecting the app against uninstall (device admin) ..."
& $Adb shell "dpm set-active-admin --user 0 $Pkg/.AdminReceiver" 2>$null | Out-Null
Write-Host "      on-device model backup (self-healing copy, only first time / when changed) ..."
& $Adb shell "am start -n $Pkg/.MainActivity >/dev/null; sleep 3; B=/sdcard/Android/data/$Pkg/files/backup; mkdir -p `$B; for d in genie_bundle genie_bundle_ft genie_bundle_ft_4096; do [ -d /data/local/tmp/`$d ] || continue;  s1=`$(stat -c %s /data/local/tmp/`$d/llama_v3_2_3b_instruct_part_3_of_3.bin); s2=`$(stat -c %s `$B/`$d/llama_v3_2_3b_instruct_part_3_of_3.bin 2>/dev/null); [ `"`$s1`" = `"`$s2`" ] && [ `$d != genie_bundle_ft -o -f `$B/`$d/VALIDATED ] || { rm -rf `$B/`$d; cp -r /data/local/tmp/`$d `$B/; echo backed-up `$d; }; done; du -sh `$B"
Write-Host "[5/6] Saving clock correction (QIDK clock is set to 2023) ..."
$dev = [long](& $Adb shell "date +%s").Trim()
$off = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $dev
& $Adb shell "echo $off | run-as $Pkg sh -c 'cat > files/clock_offset_s'"

Write-Host "[6/6] Starting the app ..."
$ErrorActionPreference = "Continue"  # "Activity not started, already running" is a stderr warning
& $Adb shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; am start -n $Pkg/.MainActivity" 2>&1 | Out-Null
& $Adb forward tcp:8000 tcp:8000 | Out-Null
Start-Sleep -Seconds 12
try {
    $st = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/status -TimeoutSec 10
    Write-Host ("App running. Agent model: {0}. Sensor time {1}." -f $st.models.agent.name, $st.sim_time_ist) -ForegroundColor Green
    Write-Host "You can unplug USB now. Laptop view (while plugged): http://localhost:8000"
} catch {
    Write-Host "App started but backend not answering yet. Log: adb shell run-as $Pkg tail -30 files/app/state/agent.log" -ForegroundColor Yellow
}
