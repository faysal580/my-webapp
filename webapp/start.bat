@echo off
REM ── Visual Team Console launcher ──────────────────────────────────────
REM Double-click this file any time (after a restart, etc.) to start the
REM local dashboard. It activates the virtual environment if one exists,
REM starts the Flask app in its own window, and opens your browser once
REM the server is ready.
REM
REM To stop the app later, just close the "Visual Team Console" window
REM that pops up (or press Ctrl+C inside it).

cd /d "%~dp0"

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

echo Starting Visual Team Console...
start "Visual Team Console" cmd /k python app.py

timeout /t 3 /nobreak >nul
start "" http://localhost:5000

echo.
echo ============================================================
echo  Other devices on the SAME wifi/LAN can reach this app too.
echo  Use one of the addresses below (not "localhost") on your
echo  phone/laptop/tablet's browser:
echo ============================================================
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4 Address"') do (
    echo    http://%%A:5000
)
echo ============================================================
echo  If other devices can't connect, check that Windows Firewall
echo  is allowing Python/port 5000 on your private network.
echo.
