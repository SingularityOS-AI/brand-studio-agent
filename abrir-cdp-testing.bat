@echo off
:: SingularityOS — Chrome DevTools Protocol (Chrome for Testing)
:: NUNCA usa el Chrome principal del usuario
:: Perfil persistente: las cookies se guardan entre sesiones

set CHROME_FT=C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe
set CDP_PROFILE=C:\Users\gabri\AppData\Local\ChromeForTesting\CDP-Profile

netstat -an 2>nul | find "9222" | find "LISTENING" >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Chrome CDP ya activo en puerto 9222
    goto :verify
)

echo [SINGULARITYOS] Iniciando Chrome for Testing con CDP...
start "" "%CHROME_FT%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%CDP_PROFILE%" ^
    --no-first-run ^
    --no-default-browser-check ^
    --disable-background-timer-throttling ^
    --disable-renderer-backgrounding ^
    --window-size=1280,800 ^
    about:blank

timeout /t 3 /nobreak >nul

:verify
curl -s http://127.0.0.1:9222/json/version
echo.
echo [LISTO] MCP chrome_devtools puede conectarse ahora.