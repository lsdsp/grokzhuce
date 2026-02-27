@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_all.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

if not "%CI%"=="true" pause
exit /b %EXIT_CODE%
