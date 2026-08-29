@echo off
setlocal
title Auto Job Applier - One Click Start
chcp 65001 >nul

REM Always run from this file's folder, wherever you double-clicked it from.
cd /d "%~dp0"

set "SCRIPT=runAiBot.py"
if not "%~1"=="" set "SCRIPT=%~1"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo ============================================================
echo  Auto Job Applier
echo  Working from: %CD%
echo  Using python : %PY%
echo ============================================================
echo.

"%PY%" -u -X utf8 "%SCRIPT%"
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Bot finished with exit code %RC%.
echo ============================================================

if "%~1"=="" pause
endlocal