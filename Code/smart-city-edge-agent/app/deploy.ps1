# Deploy + start the Smart City Edge app on the QIDK (runs standalone afterwards; USB can be unplugged).
#   powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\app\deploy.ps1            # push + start + open dashboard
#   ... deploy.ps1 -Action start|stop|status|logs|open|reset   (reset = clear incident history + full deploy)
param([ValidateSet("deploy", "start", "stop", "status", "logs", "open", "reset")][string]$Action = "deploy",
      [int]$Mode = 3)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Adb = Join-Path $Here "..\..\platform-tools\adb.exe"
if (-not (Test-Path $Adb)) { $Adb = "adb" }
$Dev = "/data/local/tmp/smart_city_edge"
$Genie = "/data/local/tmp/genie_bundle"

function AdbSh([string]$cmd) { & $Adb shell $cmd }

function Stop-App { AdbSh "pkill -x edge-agent; true" | Out-Null }

function Start-App {
    Stop-App
    AdbSh "cd $Dev && mkdir -p state && (setsid nohup ./edge-agent --dir $Dev --genie $Genie --mode $Mode --clock-unix $([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) > state/agent.log 2>&1 < /dev/null &) ; sleep 2; pgrep -x edge-agent > /dev/null && echo STARTED || (echo FAILED; tail -20 state/agent.log)"
}

function Open-UI {
    AdbSh "am start -a android.intent.action.VIEW -d http://127.0.0.1:8000 -e com.android.browser.application_id smartcityedge com.android.chrome >/dev/null 2>&1; true" | Out-Null
    & $Adb forward tcp:8000 tcp:8000 | Out-Null
    Write-Host "Dashboard opened on the QIDK. Also available on this laptop at http://localhost:8000 (adb forward)."
}

function Deploy-All {
        & $Adb get-state | Out-Null
        Write-Host "[1/4] Checking Genie runtime + base model on device..."
        $chk = AdbSh "ls $Genie/genie-t2t-run-2.50 $Genie/llama_v3_2_3b_instruct_part_1_of_3.bin $Genie/llama_v3_2_3b_instruct_part_2_of_3.bin $Genie/llama_v3_2_3b_instruct_part_3_of_3.bin $Genie/llama3.2-3b-sm8650-genie.json 2>&1"
        if ($chk -match "No such file") { throw "Genie bundle incomplete on device:`n$chk" }
        Write-Host "[2/4] Writing agent Genie config (output limit 200 tokens; trained answers are <=147, greedy) next to the base bundle..."
        AdbSh "sed 's/\`"max-num-tokens\`": *[0-9]*/\`"max-num-tokens\`": 320/; s/\`"n-threads\`": *[0-9]*/\`"n-threads\`": 4/; s/\`"cpu-mask\`": *\`"0x[0-9a-f]*\`"/\`"cpu-mask\`": \`"0xf0\`"/' $Genie/llama3.2-3b-sm8650-genie.json > $Genie/smartcity_agent.json && grep -E 'max-num-tokens|n-threads|cpu-mask' $Genie/smartcity_agent.json"
        Write-Host "[3/4] Pushing app (binary, replay data, dashboard)..."
        Stop-App
        AdbSh "mkdir -p $Dev/data $Dev/web $Dev/state"
        & $Adb push (Join-Path $Here "device\edge-agent") "$Dev/edge-agent" | Out-Null
        & $Adb push (Join-Path $Here "device\data\.") "$Dev/data/" | Out-Null
        & $Adb push (Join-Path $Here "device\web\.") "$Dev/web/" | Out-Null
        AdbSh "chmod 755 $Dev/edge-agent && chmod -R go-w $Dev"
        Write-Host "[4/4] Starting edge-agent on the QIDK..."
        Start-App
        Start-Sleep -Seconds 2
        Open-UI
    }

switch ($Action) {
    "deploy" { Deploy-All }
    "start" { Start-App; Open-UI }
    "stop" { Stop-App; Write-Host "stopped" }
    "status" { AdbSh "pgrep -xl edge-agent || echo 'not running'; curl -s http://127.0.0.1:8000/api/status 2>/dev/null | head -c 600; echo" }
    "logs" { AdbSh "tail -40 $Dev/state/agent.log" }
    "open" { Open-UI }
    "reset" { Stop-App; AdbSh "rm -f $Dev/state/incidents.jsonl $Dev/state/agent.log"; Write-Host "incident history cleared"; Deploy-All }
}
