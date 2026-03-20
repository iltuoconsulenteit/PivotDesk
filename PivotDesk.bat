@echo off
setlocal
REM PivotDesk source/runtime launcher (development repository mode).
REM Compiled distributions should use PivotDeskTray.exe / PivotDesk.exe directly.

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [PivotDesk] Starting tray companion in source/runtime mode...
python "%ROOT%tray.py"

endlocal
