@echo off
rem Launch the local forensics server on Windows.
rem Uses .venv when it exists; otherwise falls back to the interpreter on PATH.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m forensics.server %*
) else (
  python -m forensics.server %*
)
