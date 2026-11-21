@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call config.local.bat
:loop
python monitor_trades.py --url "%URL%"
if errorlevel 1 (
    python notify.py "Trade monitor crashed - restarting in 15s"
    timeout /t 15 /nobreak >nul
    goto loop
)