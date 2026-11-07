@echo off
chcp 65001 >nul
title TouchLink v3.0 - Dieu khien PC tu dien thoai
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo [TouchLink] Lan dau chay: Dang tao moi truong Python .venv...
    %PY% -m venv .venv || goto :err_venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
)

echo [TouchLink] Kiem tra thu vien can thiet...
".venv\Scripts\python.exe" -c "import aiohttp,mss,PIL,pyperclip,qrcode,cryptography,numpy,dxcam,aiortc,av,soundcard" 2>nul || (
    echo [TouchLink] Dang cai dat/cap nhat thu vien v3.0 (aiortc, av, soundcard, dxcam, numpy...)...
    ".venv\Scripts\python.exe" -m pip install -r desktop\requirements.txt || goto :err_dep
)

echo [TouchLink] Dang khoi dong TouchLink v3.0...
".venv\Scripts\python.exe" desktop\main.py %*
set "EXITCODE=%errorlevel%"

if %EXITCODE% neq 0 (
    echo.
    echo ========================================================
    echo  [LOI] Ung dung dung voi ma loi: %EXITCODE%
    echo ========================================================
    pause
    exit /b %EXITCODE%
)
goto :eof

:err_venv
echo.
echo [LOI] Khong the tao virtual environment .venv.
echo Vui long kiem tra da cai dat Python 3.10+ tren may.
pause
exit /b 1

:err_dep
echo.
echo [LOI] Khong the cai dat cac thu vien can thiet.
echo Hay thu chay thu cong bang lenh:
echo   .venv\Scripts\python.exe -m pip install -r desktop\requirements.txt
pause
exit /b 1
