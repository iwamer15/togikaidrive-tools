@echo off
REM Double-click launcher for the togikaidrive portal (Windows).
REM Starts lab\togikaidrive-portal\server.py and opens the browser.
REM Stop: press Ctrl+C in this window, or close it.
REM NOTE: keep this file ASCII-only with CRLF line endings. Japanese text here can
REM       break cmd.exe on Japanese Windows (code page 932).

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0lab\togikaidrive-portal"
if not exist server.py (
  echo ERROR: lab\togikaidrive-portal folder not found.
  echo Keep this file in the top folder of togikaidrive-tools.
  pause
  exit /b 1
)

echo Starting togikaidrive portal... http://localhost:8898
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8898"

where python >nul 2>nul
if %errorlevel%==0 (
  python server.py
  goto :done
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py
  goto :done
)
where python3 >nul 2>nul
if %errorlevel%==0 (
  python3 server.py
  goto :done
)

echo ERROR: Python was not found. Install Python 3 from https://www.python.org/downloads/
echo        and check "Add python.exe to PATH" in the installer, then run this file again.

:done
echo.
pause
