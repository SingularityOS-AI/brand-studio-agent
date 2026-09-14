@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo BRAND STUDIO AGENT - RUN SCRIPT
echo ========================================

if not exist .venv (
    echo.
    echo [1/4] Creating virtual environment...
    python -m venv .venv
) else (
    echo.
    echo [1/4] Virtual environment already exists
)

echo.
echo [2/4] Installing dependencies...
.venv\Scripts\pip.exe install -q -r requirements.txt

if not exist .env (
    echo.
    echo [WARN] No .env file found - using TEST_MODE
    set TEST_MODE=true
)

echo.
echo [3/4] Finding free port (8010-8030)...
set PORT_START=8010
set PORT_END=8030
set FOUND_PORT=0

for /L %%p in (%PORT_START%,1,%PORT_END%) do (
    netstat -ano | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 (
        set PORT=%%p
        set FOUND_PORT=1
        echo [OK] Free port found: %%p
        goto :START_SERVER
    )
)

:START_SERVER
if %FOUND_PORT%==0 (
    echo [ERROR] No free port between %PORT_START%-%PORT_END%
    echo Aborting...
    pause
    exit /b 1
)

echo %PORT% > .port_used

echo.
echo [4/4] Starting server on port %PORT%...
echo.
echo ========================================
echo URL: http://127.0.0.1:%PORT%
echo DOCS: http://127.0.0.1:%PORT%/docs
echo Press Ctrl+C to stop
echo ========================================
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

echo.
echo ========================================
echo SERVER STOPPED
echo Port used: %PORT%
echo Press any key to close...
pause >nul
