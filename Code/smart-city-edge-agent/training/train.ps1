# ONE command for the whole overnight pipeline (Windows PowerShell, laptop plugged in, QIDK on USB):
#   powershell -ExecutionPolicy Bypass -File .\Code\smart-city-edge-agent\training\train.ps1
# Stages: preflight -> pilot/plan -> QLoRA training -> eval -> merge
#         -> [export to Genie/NPU via Qualcomm AI Hub] -> [push to QIDK + on-device validation]
# Options:  -Deadline "2026-10-07 13:00"   (IST; training+eval+merge must finish by then)
#           -NoExport                      (stop after merge)
#           -Attempts 6                    (auto-restarts if the laptop hibernates/crashes)
#           -GpuWatts 35                   (GPU power cap; 0 = off. This laptop LOCKS it, so default is 0)
param([string]$Deadline = "2026-10-07 13:00", [switch]$NoExport, [int]$Attempts = 6, [int]$GpuWatts = 0)
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Keeping the laptop awake while plugged in (sleep would kill the run)..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10

# Thermal protection. On 2026-10-07 the laptop force-hibernated 21x: ACPI zone TZ01 reached its
# 100 C limit while the GPU ran at 50 W and the CPU boosted freely. Capping the CPU costs almost
# nothing for a GPU-bound QLoRA job and removes most of that heat.
Write-Host "Capping CPU to 75% on AC (cuts heat; GPU training is unaffected)..."
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 75 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null

# GPU power cap. Verified 2026-10-07 on this machine: even elevated, nvidia-smi replies
#   "Changing power management limit is not supported for GPU: 00000000:01:00.0"
# The 50 W limit is locked in the laptop VBIOS (usual for RTX laptop GPUs with Dynamic Boost), so the
# cap is OFF by default and we rely on the thermal guard, the CPU cap and the WSL limits instead.
# -GpuWatts 35 will still try, in case a driver update ever unlocks it.
function Get-GpuLimit { [double](((nvidia-smi --query-gpu=enforced.power.limit --format=csv,noheader) -replace '[^\d.]', '')) }
$gpuLimit = Get-GpuLimit
if ($GpuWatts -gt 0 -and $gpuLimit -gt ($GpuWatts + 1)) {
    Write-Host "GPU may draw up to $gpuLimit W. Capping to $GpuWatts W (one admin prompt; resets on reboot)..."
    try {
        Start-Process -FilePath "nvidia-smi" -ArgumentList "-pl", "$GpuWatts" -Verb RunAs -Wait -WindowStyle Hidden -ErrorAction Stop
        Start-Sleep -Seconds 2
        $now = Get-GpuLimit
        if ($now -le ($GpuWatts + 1)) { Write-Host "GPU power limit is now $now W." -ForegroundColor Green }
        else { Write-Host "GPU limit still $now W - the thermal guard will handle it by pausing." -ForegroundColor Yellow }
    } catch {
        Write-Host "  Not applied (prompt declined or blocked). To do it yourself, in an ADMIN PowerShell:" -ForegroundColor Yellow
        Write-Host "      nvidia-smi -pl $GpuWatts" -ForegroundColor Yellow
        Write-Host "  Training continues regardless; the thermal guard just pauses more often." -ForegroundColor Yellow
    }
}

$mon = Start-Job -ScriptBlock { param($f) & powershell -ExecutionPolicy Bypass -File $f } -ArgumentList (Join-Path $Here "thermal_monitor.ps1")
Write-Host "Thermal log: $env:USERPROFILE\smartcity_thermal.csv"

Write-Host "=== Stage A: training (keep this window open) ==="
$ok = $false
for ($i = 1; $i -le $Attempts; $i++) {
    if ($i -gt 1) {
        Write-Host "--- attempt $i of $Attempts (resuming from the last checkpoint) ---" -ForegroundColor Cyan
        Start-Sleep -Seconds 60   # let the machine cool after a thermal hibernate
    }
    wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training && DEADLINE='$Deadline' bash run_all.sh"
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Write-Host "Stage A stopped with exit code $LASTEXITCODE." -ForegroundColor Yellow
    if ((Get-Date) -gt [datetime]::ParseExact($Deadline, "yyyy-MM-dd HH:mm", $null)) {
        Write-Host "Past the deadline; not retrying."; break
    }
    wsl --shutdown | Out-Null
    Start-Sleep -Seconds 10
}
Stop-Job $mon -ErrorAction SilentlyContinue | Out-Null
Remove-Job $mon -Force -ErrorAction SilentlyContinue | Out-Null
if (-not $ok) { Write-Host "Training pipeline did not finish - see ~/smartcity_runs/<run>/run_all.log"; exit 1 }
Write-Host "Training done. Adapter + eval report: Code\smart-city-edge-agent\training\results\"

if ($NoExport) { exit 0 }
Write-Host "=== Stage B: export fine-tuned model to a Genie NPU bundle (Qualcomm AI Hub; ~4-5 h, upload ~14 GB) ==="
wsl -d Ubuntu -- bash -lc "bash /mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/export/export_to_npu.sh"
if ($LASTEXITCODE -ne 0) { Write-Host "Export failed - the app keeps the base model (fallback). Log: ~/qaihm_work/ft_export.log"; exit 2 }

Write-Host "=== Stage C: push to QIDK + validate on the NPU ==="
& (Join-Path $Here "deploy_tuned.ps1")
Write-Host "All stages finished. On-device comparison: Code\smart-city-edge-agent\training\results\device_eval.md"
