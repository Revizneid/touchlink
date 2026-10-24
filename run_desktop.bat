@echo off
chcp 65001 >nul
title TouchLink - Dieu khien PC tu dien thoai
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo Lan dau chay: dang tao moi truong Python...
    %PY% -m venv .venv || goto :err
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
)
".venv\Scripts\python.exe" -c "import aiohttp,mss,PIL,pyautogui,qrcode,pyperclip" 2>nul || (
    echo Dang cai dat thu vien can thiet...
    ".venv\Scripts\python.exe" -m pip install -r desktop\requirements.txt || goto :err
)
".venv\Scripts\python.exe" desktop\main.py %*
goto :eof

:err
echo.
echo CO LOI. Hay chay thu cong:  python -m pip install -r desktop\requirements.txt
pause
