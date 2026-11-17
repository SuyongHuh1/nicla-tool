param(
    [string]$PythonLauncher = "py"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & $PythonLauncher -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pip install -r "laptop\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pip install -r "laptop\requirements-training.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Training environment is ready." -ForegroundColor Green
Write-Host "Run: .\reproduce_stool_v1.ps1"
