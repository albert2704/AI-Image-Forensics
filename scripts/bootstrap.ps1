# Create the project environment on Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -Models
#
# Re-running is safe: an existing .venv is reused.

[CmdletBinding()]
param(
    [switch]$Models,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv with $Python"
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv. Install Python 3.12 and retry." }
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

if ($Models) {
    Write-Host "Installing pinned inference packages."
    & $venvPython -m pip install -r requirements-models.txt
}

$env:PYTHONUTF8 = "1"
Write-Host "`nEnvironment ready. Current state:`n"
& $venvPython scripts\doctor.py

Write-Host @"

Next:
  .\.venv\Scripts\python.exe -m forensics.server      # http://127.0.0.1:8765
  .\run.bat                                          # same, with UTF-8 enabled
  .\scripts\model-env.ps1                            # dot-source the model paths first
  .\.venv\Scripts\python.exe -m unittest discover -s tests
"@
