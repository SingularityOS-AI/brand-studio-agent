@echo off
chcp 65001 >nul
title BRAND STUDIO AGENT — VOICE AGENT MOCKUP (ASSEMBLYAI)

echo ==============================================================================
echo   SINGULARITYOS AI LLC — BRAND STUDIO AGENT VOICE AGENT MOCKUP (ASSEMBLYAI API)
echo ==============================================================================
echo.

cd /d "%~dp0"

REM Find Python executable
set PYTHON_EXE=python
if exist "C:\Python312_Neural\python.exe" (
    set PYTHON_EXE=C:\Python312_Neural\python.exe
)

REM Load environment variables from parent .env if exists
if exist ".env" (
    echo [OK] Cargando variables desde .env file...
    for /f "tokens=*" %%a in ('type ".env" ^| findstr /v "^#"') do set %%a
)

if "%ASSEMBLYAI_API_KEY%"=="" (
    echo [AVISO] Variable ASSEMBLYAI_API_KEY no detectada.
    echo Ingrese su API Key de AssemblyAI o presione ENTER si ya esta en el sistema:
    set /p USER_KEY="API Key: "
    if not "%USER_KEY%"=="" (
        set ASSEMBLYAI_API_KEY=%USER_KEY%
    )
)

echo.
echo [1/2] Levantando Servidor FastAPI en http://localhost:8088 ...
echo [2/2] Abriendo navegador web con AudioWorklet 24kHz y Hardware AEC...
echo.

start http://localhost:8088

"%PYTHON_EXE%" server.py

pause
