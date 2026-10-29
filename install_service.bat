@echo off
chcp 65001 >nul
title Cai dat TouchLinkSvc
net session >nul 2>&1
if errorlevel 1 (
    echo Hay chay file nay voi quyen Admin: click phai ^> "Run as administrator"
    pause & exit /b 1
)
if not exist "%~dp0TouchLinkSvc.exe" (
    echo Khong tim thay TouchLinkSvc.exe cung thu muc!
    pause & exit /b 1
)
"%~dp0TouchLinkSvc.exe" install
net start TouchLinkSvc
echo.
echo Da cai dat va khoi dong TouchLinkSvc.
echo Kiem tra trong app TouchLink: Cai dat ^> Service mo khoa tu xa.
pause
