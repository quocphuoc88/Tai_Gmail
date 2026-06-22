@echo off
rem ============================================================
rem  Bam doi de mo ung dung Tai Hoa Don Gmail (giao dien).
rem  Khong can mo PyCharm hay go lenh.
rem ============================================================
set "PYTHONUTF8=1"
set "ROOT=%~dp0"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"

if not exist "%PYW%" (
  echo [LOI] Khong tim thay moi truong ao tai:
  echo     %PYW%
  echo.
  echo Hay tao venv va cai thu vien:
  echo     python -m venv .venv
  echo     .venv\Scripts\pip install -r app\requirements.txt
  echo.
  pause
  exit /b 1
)

cd /d "%ROOT%app"
start "" "%PYW%" "%ROOT%app\gui.py"
exit /b 0
