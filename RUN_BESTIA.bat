@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo BRAND STUDIO AGENT - MODO BESTIA
echo ========================================

REM ============ FASE 1: LIMPIEZA ABSOLUTA ============
echo.
echo [FASE 1] Matando todos los procesos FastAPI/uvicorn en puertos 8000-9000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":80[0-9][0-9][0-9]" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] Limpieza completada

REM ============ FASE 2: VENV ============
echo.
if not exist .venv (
    echo [1/4] Creando entorno virtual...
    python -m venv .venv
) else (
    echo [1/4] Entorno virtual ya existe
)

REM ============ FASE 3: DEPENDENCIAS ============
echo.
echo [2/4] Instalando/actualizando dependencias...
.venv\Scripts\pip.exe install -q -r requirements.txt

REM ============ FASE 4: DETECTAR PUERTO LIBRE ============
echo.
echo [3/4] Buscando puerto libre...
set PORT_START=8010
set PORT_END=8030
set FOUND_PORT=0

for /L %%p in (%PORT_START%,1,%PORT_END%) do (
    netstat -ano | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 (
        set PORT=%%p
        set FOUND_PORT=1
        echo [OK] Puerto libre encontrado: %%p
        goto :PORT_FOUND
    )
)

:PORT_FOUND
if %FOUND_PORT%==0 (
    echo [ERROR] Ningún puerto libre entre %PORT_START%-%PORT_END%
    echo Abortando...
    pause
    exit /b 1
)

REM Guardar puerto usado
echo %PORT% > .port_used

REM ============ FASE 5: VERIFICAR .ENV ============
if not exist .env (
    echo.
    echo [WARN] No existe .env - usando TEST_MODE
    set TEST_MODE=true
)

REM ============ FASE 6: INICIAR SERVIDOR ============
echo.
echo [4/4] Iniciando servidor en puerto %PORT%...
echo.
echo ========================================
echo URL: http://127.0.0.1:%PORT%
echo DOCS: http://127.0.0.1:%PORT%/docs
echo Presiona Ctrl+C para detener
echo ========================================
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

REM ============ FIN ============
echo.
echo ========================================
echo SERVIDOR DETENIDO
echo Puerto usado: %PORT%
echo Presiona cualquier tecla para cerrar...
pause >nul
