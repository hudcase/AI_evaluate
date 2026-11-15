@echo off
REM Double-click to start the full stack: API + UI on http://127.0.0.1:8000/
REM ASCII only (batch files are parsed in the OEM code page).
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto NOPY

python backend\app.py --port 8000 --seed-demo
goto END

:NOPY
echo.
echo Python not found in PATH.
echo Install Python 3.9+ from https://www.python.org/downloads/
echo then run again, or use: py -3 backend\app.py --port 8000 --seed-demo
echo.
pause

:END
