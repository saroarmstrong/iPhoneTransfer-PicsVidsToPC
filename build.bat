@echo off
cd /d %~dp0
rem Builds dist\iPhoneTransfer\iPhoneTransfer.exe
rem Uses ..\.build\venv if it exists, otherwise "python" on PATH (pip install -r requirements.txt first).
set PY=%~dp0..\.build\venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m pytest -q tests || exit /b 1
"%PY%" tools\pack_art.py || exit /b 1
"%PY%" -m PyInstaller --noconfirm --clean iPhoneTransfer.spec || exit /b 1
echo.
echo Built: %~dp0dist\iPhoneTransfer\iPhoneTransfer.exe
