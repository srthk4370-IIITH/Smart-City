# Restores EVERYTHING the Smart City Edge demo needs onto a QIDK (USB connected), e.g. after the board
# came back from an event wiped or reflashed. Safe to run on a working board too (it only refreshes).
#   powershell -ExecutionPolicy Bypass -File C:\Users\hp\Desktop\qidk\qidk_backup\restore_qidk.ps1
#
# Sources on this laptop:
#   qidk_backup\runtime\            genie-t2t-run-2.50, the 5 QAIRT libs Genie loads, NPU (DSP) libs, configs
#   qidk_backup\genie_bundle_ft\    the validated fine-tuned NPU model (82.6 % pattern on device) + VALIDATED
#   Code\smart-city-edge-agent\models\genie_bundle\   Qualcomm's base Llama 3.2 3B bins (fallback model)
#   Code\smart-city-edge-agent\app\android\           the app + install_app.ps1
$ErrorActionPreference = "Stop"
$K = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $K
$Adb = Join-Path $Root "Code\platform-tools\adb.exe"
$Base = Join-Path $Root "Code\smart-city-edge-agent\models\genie_bundle\llama_v3_2_3b_instruct-genie-w4a16-qualcomm_snapdragon_8gen3"
$T = "/data/local/tmp"

& $Adb wait-for-device
Write-Host "[1/5] Checking base model files against SHA256SUMS ..."
$sums = Get-Content (Join-Path $Base "SHA256SUMS.txt") | Where-Object { $_ -match "^[0-9a-f]{64}" }
foreach ($line in $sums) {
    $h, $name = $line -split "\s+\*?", 2
    $f = Join-Path $Base $name.Trim()
    if (-not (Test-Path $f)) { throw "missing $f" }
    if ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $h) { throw "hash mismatch: $f" }
}

Write-Host "[2/5] Base runtime + model -> $T/genie_bundle ..."
& $Adb shell "mkdir -p $T/genie_bundle/qairt_2_50_libs $T/genie_bundle/dsp_2_50"
foreach ($f in Get-ChildItem (Join-Path $K "runtime") -File) { & $Adb push $f.FullName "$T/genie_bundle/$($f.Name)" | Out-Null }
& $Adb push (Join-Path $K "runtime\qairt_2_50_libs\.") "$T/genie_bundle/qairt_2_50_libs/" | Select-Object -Last 1
& $Adb push (Join-Path $K "runtime\dsp_2_50\.") "$T/genie_bundle/dsp_2_50/" | Select-Object -Last 1
foreach ($i in 1, 2, 3) {
    $n = "llama_v3_2_3b_instruct_part_${i}_of_3.bin"
    & $Adb push (Join-Path $Base $n) "$T/genie_bundle/$n" | Select-Object -Last 1
}
& $Adb shell "chmod 755 $T/genie_bundle/genie-t2t-run-2.50"

Write-Host "[3/5] Fine-tuned model -> $T/genie_bundle_ft ..."
& $Adb shell "mkdir -p $T/genie_bundle_ft"
& $Adb push (Join-Path $K "genie_bundle_ft\.") "$T/genie_bundle_ft/" | Select-Object -Last 1

Write-Host "[4/5] Quick NPU check ..."
& $Adb shell "printf '<|start_header_id|>user<|end_header_id|>\n\nSay OK.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n' > $T/ok.txt; cd $T/genie_bundle_ft && LD_LIBRARY_PATH=$T/genie_bundle/qairt_2_50_libs ADSP_LIBRARY_PATH='$T/genie_bundle/dsp_2_50;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp' $T/genie_bundle/genie-t2t-run-2.50 -c smartcity_agent.json --prompt_file $T/ok.txt 2>&1 | grep -E 'BEGIN|ERROR' | head -2; rm -f $T/ok.txt"

Write-Host "[5/5] Installing the app (also: adb loopback, uninstall protection, on-device backup, clock) ..."
& (Join-Path $Root "Code\smart-city-edge-agent\app\android\install_app.ps1") -ClearHistory
Write-Host "Restore complete." -ForegroundColor Green
