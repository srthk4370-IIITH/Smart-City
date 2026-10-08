# Push the fine-tuned Genie bundle to the QIDK and validate it on the NPU.
# Run on its own at any time (QIDK connected):
#   powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\deploy_tuned.ps1
# The app only switches its domain agents to the tuned model if validation passes; otherwise it keeps
# the base model and shows "fallback" in the header.
param([string]$Bundle = "", [int]$PerRole = 4)
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Bundle) {
    # AI Hub writes part1_of_3.bin; older local exports write llama_..._part_1_of_3.bin
    $found = (wsl -d Ubuntu -- bash -lc "ls -d ~/qaihm_work/ft_genie/*/ 2>/dev/null | head -1").Trim()
    if (-not $found) { Write-Host "No exported bundle found in ~/qaihm_work/ft_genie/. Run export_to_npu.sh first." -ForegroundColor Red; exit 1 }
    $Bundle = "\\wsl$\Ubuntu" + ($found.TrimEnd('/') -replace "/", "\")
}
Write-Host "Bundle: $Bundle"
if (-not (Test-Path $Bundle)) { Write-Host "Bundle path not reachable from Windows." -ForegroundColor Red; exit 1 }

python (Join-Path $Here "export\validate_tuned_on_device.py") --bundle $Bundle --per-role $PerRole
Write-Host ""
Write-Host "Report: Code\smart-city-edge-agent\training\results\device_eval.md"
