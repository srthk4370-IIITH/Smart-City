param(
    [string]$Adb = 'C:\Android\platform-tools\platform-tools\adb.exe',
    [string]$Serial = '3ce9a4e2',
    [string]$Bundle = "$PSScriptRoot\..\models\genie_bundle\sm8650-v75"
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Adb)) { throw "ADB not found: $Adb" }
if (-not (Test-Path -LiteralPath $Bundle)) { throw "Bundle directory not found: $Bundle" }
if (-not (Test-Path -LiteralPath (Join-Path $Bundle 'qairt_version.txt'))) {
    throw 'Refusing deployment: qairt_version.txt is missing from the model bundle.'
}

& $Adb -s $Serial shell 'mkdir -p /data/local/tmp/smart_city_edge/genie_bundle'
Get-ChildItem -LiteralPath $Bundle -File | ForEach-Object {
    & $Adb -s $Serial push $_.FullName /data/local/tmp/smart_city_edge/genie_bundle/
}

