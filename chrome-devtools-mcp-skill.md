name: chrome-devtools-mcp
description: >-
  Controla un Chrome for Testing separado (NUNCA el Chrome principal del
  usuario) via MCP chrome_devtools. Perfil persistente con cookies propias.
  Activar con /chrome-devtools para navegación automatizada, auditorías,
  debugging frontend y automatización web.

---

# SKILL: /chrome-devtools — Chrome DevTools MCP (proceso separado)

## ACTIVACIÓN
Cuando el CEO invoca /chrome-devtools [tarea], o pide "automatiza X en el
navegador", "audita la web", "debuggea el frontend", "navega a Y".

## CONSTRAINT ABSOLUTO — LEE ESTO PRIMERO
**NUNCA** mates, detengas ni toques el Chrome del usuario.
El Chrome del usuario = C:\Program Files\Google\Chrome\Application\chrome.exe
Tu Chrome = C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe

Si necesitas un navegador, únicamente usas Chrome for Testing.
Si por error el puerto 9222 está en uso por el Chrome del usuario → NO LO MATES.
Reporta: "Mijo, hay un conflicto de puerto. Cierra manualmente el Chrome que
tiene CDP o usa un puerto diferente."

## CHROME QUE USAS (proceso separado, perfil persistente)
- **Binario:** C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe
- **Perfil (cookies):** C:\Users\gabri\AppData\Local\ChromeForTesting\CDP-Profile
- **Puerto CDP:** 9222
- **Script de arranque:** C:\Users\gabri\Desktop\SINGULARITYOS\.cromedebug\abrir-cdp-testing.bat
- **Cookies:** persisten entre sesiones (el perfil se mantiene entre reinicios)

## PASO 0 — VERIFICAR ANTES DE ACTUAR
```powershell
$r = try { Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 3 } catch { $null }
if (-not $r) { Write-Host "CDP no activo. Lanzando Chrome for Testing..." }
```
Respondió → OK, procede.
No respondió → ejecuta el script de arranque: cmd /c "C:\Users\gabri\Desktop\SINGULARITYOS\.cromedebug\abrir-cdp-testing.bat" 
Espera 3s y reverifica. Si sigue sin responder, reporta sin intentar nada más.

## TOOLS MCP DISPONIBLES

| Tool | Uso |
|------|-----|
| list_pages() | Lista tabs abiertos (úsalo siempre primero) |
| navigate_page(url) | Navega a URL |
| take_screenshot() | Captura visual del tab activo |
| click(selector) | Click en elemento CSS/xpath |
| fill(selector, value) | Rellena input |
| type_text(text) | Escribe texto |
| press_key(key) | Tecla (Enter, Tab, Escape...) |
| hover(selector) | Hover sobre elemento |
| select_page(tabId) | Cambia de tab |
| new_page(url) | Abre tab nuevo |
| close_page(tabId) | Cierra tab (NUNCA el proceso) |
| evaluate_script(js) | Ejecuta JavaScript |
| wait_for(selector_o_ms) | Espera elemento o tiempo |
| list_console_messages() | Errores JS de consola |
| list_network_requests() | Requests de red |
| lighthouse_audit(url) | Auditoría completa Lighthouse |
| performance_start_trace() | Inicia traza performance |
| performance_stop_trace() | Detiene y retorna Core Web Vitals |
| emulate(device) | Emula dispositivo móvil |
| handle_dialog(accept, text) | Maneja alert/confirm |
| upload_file(selector, path) | Sube archivo |

## PROTOCOLO DE EJECUCIÓN

### PLAN OBLIGATORIO (antes de cualquier acción)
- TAREA: [qué harás]
- URL: [destino]
- PASOS: 1. ... 2. ... 3. ...
- RIESGO: BAJO | MEDIO
- CHROME: Chrome for Testing (proceso separado, perfil CDP-Profile)

### LOOP DE ACCIÓN
1. Verifica CDP activo (PASO 0).
2. list_pages() → identifica tab correcto.
3. Acción → take_screenshot() → analiza resultado.
4. Repite hasta completar tarea.
5. Reporte final con screenshot.

## REGLAS ABSOLUTAS
- NUNCA Stop-Process, taskkill, ni kill a ningún proceso de Chrome.
- NUNCA cerrar el navegador del usuario — solo close_page() sobre tabs propios.
- NUNCA guardar credenciales en archivos — pausa y pide al CEO que las ingrese.
- SIEMPRE plan antes de ejecutar.
- PAUSA ante login/2FA — pide al CEO que complete manualmente.
- Si el puerto 9222 está ocupado por el Chrome del usuario → reporta, NO mates nada.
- Cookies del CDP-Profile son del agente, no del usuario. No se mezclan.

## TONO
Directo, español, modo copiloto. El CEO es el piloto, tú el navegador técnico.

---

## Resumen técnico rápido (para referencia)

| Elemento | Valor |
|---|---|
| Chrome que usa DSH | Chrome for Testing `win64-153.0.8010.52` |
| Chrome que NUNCA toca | `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| Perfil cookies | `CDP-Profile` (persiste entre sesiones) |
| Puerto CDP | `9222` |
| MCP server | `chrome_devtools` (ya en `cordis.patch.yml`) |
| Script arranque | `abrir-cdp-testing.bat` |
| Comando DSH | `/chrome-devtools [tarea]` |

Para usar: ejecuta abrir-cdp-testing.bat → luego /chrome-devtools [tarea]