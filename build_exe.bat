@echo off
chcp 65001 >nul
title Build TouchLink portable exe
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Chay run_desktop.bat truoc de tao moi truong.
    pause & exit /b 1
)

echo Cai dat PyInstaller (neu chua co)...
".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>nul || ".venv\Scripts\python.exe" -m pip install -q pyinstaller

echo Dang build...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name TouchLink ^
  --icon assets\icon.ico ^
  --add-data "web;web" ^
  --hidden-import qrcode.image.pil ^
  --hidden-import PIL._tkinter_finder ^
  --hidden-import pyautogui._pyautogui_win ^
  desktop\main.py

if errorlevel 1 (echo BUILD LOI & pause & exit /b 1)

echo.
echo Xong: dist\TouchLink.exe
pause
