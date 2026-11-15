@echo off
REM Desktop launcher with console - use this when the window does not show up.
REM ASCII only: batch files are parsed in the OEM code page.
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto NOPY

python "desktop\main.py" --verbose
echo.
echo exited with code %errorlevel%
pause
goto END

:NOPY
echo.
echo Python not found in PATH. Install Python 3.9+ from https://www.python.org/downloads/
echo Or run build_win.py to produce a standalone exe.
echo.
pause

:END
