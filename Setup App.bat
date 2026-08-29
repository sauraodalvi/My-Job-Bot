@echo off
setlocal
chcp 65001 >nul
title Auto Job Applier - Setup
cd /d "%~dp0"

if exist "AutoJobApplier.exe" (
    start "" "AutoJobApplier.exe" --setup
) else (
    set "PY=python"
    if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
    "%PY%" -u -X utf8 setup_app.py --setup
    echo.
    echo  Setup closed. If you change your choices later, run this file again.
    pause
)
endlocal