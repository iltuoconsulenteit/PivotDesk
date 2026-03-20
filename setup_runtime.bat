@echo off
setlocal
REM Source/runtime setup helper for local Python environments.
REM Not required for compiled EXE distributions.

set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [PivotDesk Setup] Creating virtual environment...
  python -m venv .venv
)

echo [PivotDesk Setup] Installing core dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-core.txt

if exist "requirements-desktop.txt" (
  echo [PivotDesk Setup] Installing optional desktop/tray dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt
)

echo [PivotDesk Setup] Completed. Use start.bat or PivotDesk.bat in source mode.
endlocal
