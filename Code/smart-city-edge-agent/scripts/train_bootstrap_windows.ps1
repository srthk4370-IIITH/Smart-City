param(
  [string]$DataDir = 'C:\Users\hp\Desktop\dataset',
  [string]$Python = 'python',
  [int]$Limit = 100000
)
$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $DataDir)) { throw "Dataset directory not found: $DataDir" }
Push-Location $Project
try {
  $Venv = Join-Path $Project '.bootstrap-venv'
  if (-not (Test-Path -LiteralPath $Venv)) { & $Python -m venv $Venv }
  $Py = Join-Path $Venv 'Scripts\python.exe'
  & $Py -m pip install --upgrade pip
  & $Py -m pip install -r requirements-bootstrap.txt
  & $Py -m pip install -e .
  & $Py scripts\train_bootstrap_agents.py --data-dir $DataDir --limit $Limit
  & $Py scripts\test_bootstrap_models.py
  & $Py scripts\demo_bootstrap_agents.py
  & $Py scripts\generate_qidk_runner_header.py
} finally { Pop-Location }
