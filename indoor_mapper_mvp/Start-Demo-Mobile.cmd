@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install dependencies first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" mobile_server.py --project projects/map_20261011_035045
if errorlevel 1 pause
endlocal
