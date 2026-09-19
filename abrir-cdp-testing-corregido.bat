@echo off
:: SingularityOS — Chrome DevTools Protocol (Chrome for Testing) - CORREGIDO
:: NUNCA usa el Chrome principal del usuario
:: CORRECCION: --no-sandbox, --disable-gpu + pause >nul para Windows
:: Perfil persistente: las cookies se guardan entre sesiones

set CHROME_FT=C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe
set CDP_PROFILE=C:\Users\gabri\AppData\Local\ChromeForTesting\CDP-Profile

echo [SINGULARITYOS] Verificando Chrome for Testing...

:: Verificar que existe Chrome for Testing
if not exist "%CHROME_FT%" (
    echo [ERROR] Chrome for Testing no encontrado: %CHROME_FT%
    pause >nul
    exit /b 1
)

:: Verificar si CDP ya está activo
netstat -an 2>nul | find "9222" | find "LISTENING" >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Chrome CDP ya activo en puerto 9222
    goto :verify
)

echo [SINGULARITYOS] Iniciando Chrome for Testing con CDP corregido...

:: CORRECCIÓN: Flags necesarios para Chrome for Testing en Windows
start "" "%CHROME_FT%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%CDP_PROFILE%" ^
    --no-first-run ^
    --no-default-browser-check ^
    --no-sandbox ^
    --disable-gpu ^
    --disable-background-timer-throttling ^
    --disable-renderer-backgrounding ^
    --window-size=1280,800 ^
    --disable-dev-shm-usage ^
    about:blank

timeout /t 3 /nobreak >nul

:verify
echo [VERIFICACION] Probando endpoint CDP...
curl -s http://127.0.0.1:9222/json/version

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] CDP no responde en puerto 9222
    echo [SOLUCION] Verifica que no haya otro proceso usando puerto 9222
    pause >nul
    exit /b 1
)

echo.
echo [LISTO] MCP chrome_devtools puede conectarse ahora.
echo [INFO] pageId sera numero entero (1, 2, 3...)
echo [INFO] Usar list_pages() primero para obtener pageId activo.
echo [INFO] Firmas corregidas: navigate_page(pageId=1, url="...")

pause >nul