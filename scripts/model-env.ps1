# Dot-source this file from the project directory to point the adapters at the
# local model checkouts on Windows.
#
#   . .\scripts\model-env.ps1
#
# Nothing here downloads anything; docs/PLATFORMS.md explains the install steps.

if (-not $env:FORENSICS_PROJECT_DIR) {
    $env:FORENSICS_PROJECT_DIR = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if (-not $env:BFREE_REPO) { $env:BFREE_REPO = Join-Path $env:FORENSICS_PROJECT_DIR "external\B-Free" }
if (-not $env:BFREE_WEIGHTS) { $env:BFREE_WEIGHTS = Join-Path $env:BFREE_REPO "code\weights\BFREE_dino2reg4" }
if (-not $env:BFREE_DEVICE) { $env:BFREE_DEVICE = "cpu" }

if (-not $env:TRUFOR_REPO) { $env:TRUFOR_REPO = Join-Path $env:FORENSICS_PROJECT_DIR "external\TruFor" }
if (-not $env:TRUFOR_PYTHON) { $env:TRUFOR_PYTHON = Join-Path $env:FORENSICS_PROJECT_DIR ".venv\Scripts\python.exe" }
if (-not $env:TRUFOR_DEVICE) { $env:TRUFOR_DEVICE = "cpu" }

if (-not $env:OMP_NUM_THREADS) { $env:OMP_NUM_THREADS = "4" }
if (-not $env:MPLCONFIGDIR) { $env:MPLCONFIGDIR = Join-Path $env:FORENSICS_PROJECT_DIR "output\cache\matplotlib" }
if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $env:FORENSICS_PROJECT_DIR "output\cache\huggingface" }
