@echo off
setlocal
REM Compiled bundle launcher helper (local test for PyInstaller one-dir output).

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%PivotDeskTray.exe" (
  echo [PivotDesk Compiled] Starting PivotDeskTray.exe
  start "" "%ROOT%PivotDeskTray.exe"
  goto :eof
)

if exist "%ROOT%PivotDesk.exe" (
  echo [PivotDesk Compiled] Starting PivotDesk.exe
  start "" "%ROOT%PivotDesk.exe"
  goto :eof
)

echo [PivotDesk Compiled] ERROR: neither PivotDeskTray.exe nor PivotDesk.exe found.
exit /b 1

