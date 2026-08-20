param(
    [string]$Adb = 'C:\Android\platform-tools\platform-tools\adb.exe',
    [string]$Serial = '3ce9a4e2'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Adb)) { throw "ADB not found: $Adb" }

& $Adb devices -l
& $Adb -s $Serial shell getprop ro.product.model
& $Adb -s $Serial shell getprop ro.soc.model
& $Adb -s $Serial shell getprop ro.build.version.release
& $Adb -s $Serial shell getprop ro.product.cpu.abi
& $Adb -s $Serial shell getenforce
& $Adb -s $Serial shell df -h /data /data/local/tmp
& $Adb -s $Serial shell dumpsys thermalservice

