@echo off
rem Point the adapters at local model checkouts on Windows.
rem Call this from a launcher or from a command prompt:
rem   call scripts\model-env.bat
if not defined FORENSICS_PROJECT_DIR set "FORENSICS_PROJECT_DIR=%~dp0.."
if not defined BFREE_REPO set "BFREE_REPO=%FORENSICS_PROJECT_DIR%\external\B-Free"
if not defined BFREE_WEIGHTS set "BFREE_WEIGHTS=%BFREE_REPO%\code\weights\BFREE_dino2reg4"
if not defined BFREE_DEVICE set "BFREE_DEVICE=cpu"
if not defined TRUFOR_REPO set "TRUFOR_REPO=%FORENSICS_PROJECT_DIR%\external\TruFor"
if not defined TRUFOR_PYTHON set "TRUFOR_PYTHON=%FORENSICS_PROJECT_DIR%\.venv\Scripts\python.exe"
if not defined TRUFOR_DEVICE set "TRUFOR_DEVICE=cpu"
if not defined OMP_NUM_THREADS set "OMP_NUM_THREADS=4"
if not defined MPLCONFIGDIR set "MPLCONFIGDIR=%FORENSICS_PROJECT_DIR%\output\cache\matplotlib"
if not defined HF_HOME set "HF_HOME=%FORENSICS_PROJECT_DIR%\output\cache\huggingface"
