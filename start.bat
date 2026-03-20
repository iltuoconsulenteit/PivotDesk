@echo off
setlocal
REM DEV launcher (virtualenv-friendly): starts canonical server bootstrap directly.

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%.venv\Scripts\python.exe" (
  echo [PivotDesk DEV] Using .venv python
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%main.py"
) else (
  echo [PivotDesk DEV] Using system python
  python "%ROOT%main.py"
)

endlocal
