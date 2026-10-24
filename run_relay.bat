@echo off
chcp 65001 >nul
title TouchLink Relay Server
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
)
".venv\Scripts\python.exe" -c "import aiohttp" 2>nul || ".venv\Scripts\python.exe" -m pip install -r relay\requirements.txt
".venv\Scripts\python.exe" relay\relay_server.py --port 8430
pause
