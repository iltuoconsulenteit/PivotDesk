@echo off
cd /d "%~dp0\..\.."
if not exist .venv\Scripts\pyinstaller.exe (
  echo PyInstaller non trovato nella venv.
  exit /b 1
)
.venv\Scripts\pyinstaller.exe platform\windows\PivotDesk.spec --clean
