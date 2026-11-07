@echo off
chcp 65001 >nul
title Build TouchLink v3.0 portable exe
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo [Build] Dang tao moi truong Python...
    %PY% -m venv .venv || goto :err
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
)

echo [Build] Kiem tra dependencies v3.0...
".venv\Scripts\python.exe" -c "import aiohttp,mss,PIL,pyperclip,qrcode,cryptography,numpy,dxcam,aiortc,av,soundcard" 2>nul || (
    echo [Build] Dang cai dat thu vien v3.0...
    ".venv\Scripts\python.exe" -m pip install -r desktop\requirements.txt || goto :err
)

echo [Build] Cai dat PyInstaller (neu chua co)...
".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>nul || ".venv\Scripts\python.exe" -m pip install pyinstaller

echo.
echo ========================================================
echo  [1/2] Dang dong goi TouchLink.exe tu TouchLink.spec...
echo ========================================================
".venv\Scripts\python.exe" -m PyInstaller TouchLink.spec --noconfirm --clean
if errorlevel 1 goto :err

echo.
echo ========================================================
echo  [2/2] Dang dong goi TouchLinkSvc.exe tu TouchLinkSvc.spec...
echo ========================================================
".venv\Scripts\python.exe" -m PyInstaller TouchLinkSvc.spec --noconfirm --clean
if errorlevel 1 goto :err

echo.
echo ========================================================
echo  DONG GOI THANH CONG!
echo  - File app chinh: dist\TouchLink.exe
echo  - File service:   dist\TouchLinkSvc.exe
echo ========================================================
pause
goto :eof

:err
echo.
echo ========================================================
echo  [LOI] Build that bai! Vui long kiem tra thong bao loi o tren.
echo ========================================================
pause
exit /b 1
