@echo off
title LyricSync Pro

echo.
echo  =============================================
echo   LyricSync Pro - Starting...
echo  =============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo  Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

REM Install dependencies silently if not present
echo  Checking dependencies...
pip install -r requirements.txt -q --disable-pip-version-check

echo  Launching app at http://127.0.0.1:5000
echo  (Your browser will open automatically)
echo.
echo  Press Ctrl+C to stop the server.
echo.

python app.py

pause
