# Swap the QIDK's fine-tuned Genie bundle for the multi-context-length rebuild, with a rollback.
#
#   powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\deploy_mcl.ps1 -Bundle <dir>
#   ... -Rollback        # restore the previous bundle and exit
#
# The rebuild comes from the SAME checkpoint and encodings as the live bundle, so outputs must be
# byte-identical. This script only stages it; compare_bundles.py must pass before -Activate is used.
param(
    [string]$Bundle = "",
    [switch]$Activate,
    [switch]$Rollback
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Adb = Join-Path $Here "..\..\platform-tools\adb.exe"
$Pkg = "com.iiith.smartcityedge"
$FT = "/data/local/tmp/genie_bundle_ft"
$NEW = "/data/local/tmp/genie_bundle_ft2"
$BAK = "/data/local/tmp/genie_bundle_ft_prev"

function AdbSh([string]$c) { & $Adb shell $c }

if ($Rollback) {
    Write-Host "Rolling back to the previous bundle ..."
    AdbSh "test -d $BAK || { echo 'no backup at $BAK'; exit 1; }"
    AdbSh "am force-stop $Pkg; pkill -x edge-agent; sleep 1; rm -rf $FT && mv $BAK $FT && echo restored"
    AdbSh "am start -n $Pkg/.MainActivity >/dev/null 2>&1"
    Write-Host "Rolled back. The app will restart the backend within ~6 s." -ForegroundColor Green
    exit 0
}

if ($Activate) {
    # Promote the staged bundle, keeping the old one so -Rollback always works.
    Write-Host "Activating $NEW (previous kept at $BAK) ..."
    AdbSh "test -f $NEW/llama_v3_2_3b_instruct_part_3_of_3.bin || { echo 'staged bundle incomplete'; exit 1; }"
    AdbSh "am force-stop $Pkg; pkill -x edge-agent; sleep 1; rm -rf $BAK; mv $FT $BAK && mv $NEW $FT && echo swapped"
    AdbSh "am start -n $Pkg/.MainActivity >/dev/null 2>&1"
    Write-Host "Activated. Rollback with: deploy_mcl.ps1 -Rollback" -ForegroundColor Green
    exit 0
}

if (-not $Bundle) { throw "pass -Bundle <dir with the 3 .bin files>, or -Activate / -Rollback" }
if (-not (Test-Path $Bundle)) { throw "no such directory: $Bundle" }

Write-Host "[1/3] Staging rebuild to $NEW (live bundle untouched) ..."
AdbSh "mkdir -p $NEW"
foreach ($i in 1, 2, 3) {
    $n = "llama_v3_2_3b_instruct_part_${i}_of_3.bin"
    $src = Join-Path $Bundle $n
    if (-not (Test-Path $src)) {
        # AI Hub also writes part1_of_3.bin style names
        $alt = Join-Path $Bundle "part${i}_of_3.bin"
        if (Test-Path $alt) { $src = $alt } else { throw "missing part $i in $Bundle" }
    }
    Write-Host "      pushing $n ..."
    & $Adb push $src "$NEW/$n" | Select-Object -Last 1
}
foreach ($f in "tokenizer.json", "htp_backend_ext_config.json") {
    $src = Join-Path $Bundle $f
    if (Test-Path $src) { & $Adb push $src "$NEW/$f" | Out-Null }
}

Write-Host "[2/3] Writing the agent config (greedy, 4 threads, context size must match the rebuild) ..."
# Start from the live config so every tuned knob is preserved, then let the operator confirm ctx size.
AdbSh "cp $FT/smartcity_agent.json $NEW/smartcity_agent.json"
Write-Host "      NOTE: set dialog.context.size to the largest compiled context length, and verify"
Write-Host "      rope-scaling against the live config before activating."

Write-Host "[3/3] Staged. Next:"
Write-Host "      py training\export\compare_bundles.py --b $NEW -n 20     # must report identical 20/20"
Write-Host "      powershell -File training\deploy_mcl.ps1 -Activate"
