@echo off
rem DBS_SplatTrain - by David Borrull. MIT License. See LICENSE.
rem Installs DBS_SplatTrain for Nuke with Nuke's own Python (tools\DBS_install.py does the work).
setlocal
set "PY="
for /d %%D in ("C:\Program Files\Nuke17*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo DBS: Nuke 17 not found in C:\Program Files, and no python on PATH.
    echo      Run: "path\to\Nuke17\python.exe" "%~dp0tools\DBS_install.py" install
    pause
    exit /b 1
)
"%PY%" "%~dp0tools\DBS_install.py" install %*
echo.
pause
