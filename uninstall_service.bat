@echo off
chcp 65001 >nul
title Go TouchLinkSvc
net session >nul 2>&1
if errorlevel 1 (
    echo Hay chay file nay voi quyen Admin: click phai ^> "Run as administrator"
    pause & exit /b 1
)
net stop TouchLinkSvc
if exist "%~dp0TouchLinkSvc.exe" "%~dp0TouchLinkSvc.exe" remove
echo Da go TouchLinkSvc.
pause
