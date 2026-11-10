@echo off
setlocal
rem ================================================================
rem  Tomato Clock launcher - double-click to start
rem  Order: pyw / pythonw (no console) -> py / python (console)
rem ================================================================
cd /d "%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "main.py"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "main.py"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 "main.py"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    python "main.py"
    exit /b 0
)

echo Python 3 not found. Please install Python 3.12 and add it to PATH.
pause
exit /b 1