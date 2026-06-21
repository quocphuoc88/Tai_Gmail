@echo off
setlocal ENABLEDELAYEDEXPANSION

REM ==============================
REM Build TaiHoaDon.exe (Console app)
REM - Token: tokenSG.json (do code bạn lưu cạnh exe)
REM - Credentials: credentials_SG.json (add-data vào exe)
REM - Tai_Gmail.xlsx: KHONG add-data, de ngoai de sua
REM ==============================

REM --- Ten file Python chinh (sua lai neu can) ---
set MAIN_PY=HDDT_Sagitta.py

REM --- Ten exe xuat ra ---
set EXE_NAME=TaiHoaDon

REM --- Thu muc script .bat ---
set BASEDIR=%~dp0

REM --- Dung icon neu co ---
set ICON_FLAG=
if exist "%BASEDIR%icon.ico" (
    set ICON_FLAG=--icon "%BASEDIR%icon.ico"
)

REM --- Don output cu ---
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%BASEDIR%%EXE_NAME%.spec" del /f /q "%BASEDIR%%EXE_NAME%.spec"

REM --- Dam bao PyInstaller ---
python -m pip install --upgrade pip
python -m pip install --upgrade pyinstaller

REM --- Thu vien can thiet (neu thieu) ---
python -m pip install --upgrade google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2
python -m pip install --upgrade requests beautifulsoup4 tk tkcalendar pandas openpyxl python-dateutil

REM --- Kiem tra credentials_SG.json ---
if not exist "%BASEDIR%credentials_SG.json" (
    echo [ERROR] Khong tim thay credentials_SG.json trong thu muc: %BASEDIR%
    echo Vui long dat credentials_SG.json cung cap voi file .bat, roi chay lai.
    pause
    exit /b 1
)

REM --- Build CONSOLE app: KHONG dung --noconsole ---
pyinstaller ^
  --onefile ^
  --console ^
  --name "%EXE_NAME%" ^
  %ICON_FLAG% ^
  --add-data "%BASEDIR%credentials_SG.json;." ^
  --hidden-import dateutil ^
  --hidden-import dateutil.parser ^
  --hidden-import bs4 ^
  --hidden-import tkcalendar ^
  --clean --noconfirm ^
  "%BASEDIR%%MAIN_PY%"

echo.
echo ==============================
if exist "dist\%EXE_NAME%.exe" (
  echo ✅ Build hoan tat: dist\%EXE_NAME%.exe
  echo 👉 Dat Tai_Gmail.xlsx cung thu muc voi file .exe truoc khi chay.
) else (
  echo ❌ Build that bai - vui long xem thong bao loi o tren.
)
echo ==============================

pause
