@echo off
rem Claude Voice - one-click setup. Installs everything inside this folder.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_voice.ps1" %*
echo.
pause
