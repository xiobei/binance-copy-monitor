@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist config.local.bat (
    echo Missing config.local.bat - copy config.example.bat to config.local.bat and fill in your value.
    pause
    exit /b
)

rem When started at boot (argument "auto") wait for the network first.
if "%1"=="auto" timeout /t 30 /nobreak >nul

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install from python.org and tick "Add Python to PATH".
    pause
    exit /b
)

if not exist ".setup_done" (
    echo First run: installing dependencies, please wait...
    python -m pip install -r requirements.txt
    python -m playwright install chromium
    echo ok> .setup_done
)

call loop_monitor.bat