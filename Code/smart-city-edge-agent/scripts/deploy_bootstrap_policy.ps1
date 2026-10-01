param(
  [string]$Adb = 'C:\Android\platform-tools\adb.exe',
  [string]$Serial = '3ce9a4e2',
  [string]$ModelDir = "$PSScriptRoot\..\models\bootstrap",
  [string]$Runner = "$PSScriptRoot\..\qidk_runtime\build\bootstrap_policy_runner"
)
$ErrorActionPreference = 'Stop'
foreach ($file in @($Adb, (Join-Path $ModelDir 'edge_policy.json'), $Runner)) { if (-not (Test-Path -LiteralPath $file)) { throw "Required file not found: $file" } }
& $Adb -s $Serial shell 'mkdir -p /data/local/tmp/smart_city_edge/bootstrap'
& $Adb -s $Serial push (Join-Path $ModelDir 'edge_policy.json') /data/local/tmp/smart_city_edge/bootstrap/
& $Adb -s $Serial push $Runner /data/local/tmp/smart_city_edge/bootstrap/bootstrap_policy_runner
& $Adb -s $Serial shell 'chmod 755 /data/local/tmp/smart_city_edge/bootstrap/bootstrap_policy_runner'
& $Adb -s $Serial shell '/data/local/tmp/smart_city_edge/bootstrap/bootstrap_policy_runner 1250 27 55 18 30 90'
