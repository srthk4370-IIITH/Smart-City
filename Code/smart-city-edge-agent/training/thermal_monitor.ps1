# Logs GPU temperature, power and CPU load every 20 s so a thermal problem can be diagnosed later.
# Started automatically by train.ps1; can also be run alone:
#   powershell -ExecutionPolicy Bypass -File .\thermal_monitor.ps1
param([string]$Out = "$env:USERPROFILE\smartcity_thermal.csv", [int]$IntervalSec = 20)
"time,gpu_c,gpu_w,gpu_util,cpu_pct,ram_free_mb" | Out-File -FilePath $Out -Encoding utf8
while ($true) {
    try {
        $g = (nvidia-smi --query-gpu=temperature.gpu,power.draw,utilization.gpu --format=csv,noheader,nounits) -split ','
        $cpu = [math]::Round((Get-CimInstance Win32_Processor).LoadPercentage, 0)
        $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB, 0)
        "{0},{1},{2},{3},{4},{5}" -f (Get-Date -Format HH:mm:ss), $g[0].Trim(), $g[1].Trim(), $g[2].Trim(), $cpu, $free |
            Out-File -FilePath $Out -Append -Encoding utf8
    } catch {}
    Start-Sleep -Seconds $IntervalSec
}
