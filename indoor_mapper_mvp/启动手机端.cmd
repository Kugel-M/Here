@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Run setup.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0mobile_server.py"
if errorlevel 1 pause
endlocal
