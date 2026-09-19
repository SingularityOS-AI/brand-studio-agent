# Corrección urgente sobre el error "The browser is already running for chrome-devtools-mcp\chrome-profile"

## DIAGNÓSTICO EXACTO (resuelto por Antigravity):

El error ocurre porque el MCP chrome_devtools tiene DOS modos de operación y estabas usando el modo INCORRECTO:

### MODO A — Self-managed (INCORRECTO para DSH):
- args: ['chrome-devtools-mcp', '--headless']
- El MCP lanza su PROPIO Chrome usando el perfil por defecto:
  `C:\Users\gabri\.cache\chrome-devtools-mcp\chrome-profile`
- **PROBLEMA:** si ese Chrome queda vivo entre sesiones (zombie), la siguiente vez que DSH inicia el MCP falla con "profile already in use".
- También usa el Chrome del SISTEMA (Program Files), no Chrome for Testing.

### MODO B — browserUrl (CORRECTO para DSH):
- args: ['chrome-devtools-mcp', '--browserUrl', 'http://127.0.0.1:9222']
- El MCP NO lanza ningún Chrome propio. Se conecta al Chrome externo ya corriendo en puerto 9222. Cero conflictos de perfil. Sin zombies.
- El Chrome externo = Chrome for Testing con perfil persistente (cookies).

## CORRECCIÓN YA APLICADA en cordis.patch.yml:
El config ahora usa `--browserUrl http://127.0.0.1:9222` (Modo B).

## FLUJO OBLIGATORIO PARA USAR chrome_devtools TOOLS:

1. **Ejecutar PRIMERO el BAT:**
   `C:\Users\gabri\Desktop\SINGULARITYOS\.cromedebug\abrir-cdp-testing.bat`
   → Lanza Chrome for Testing en puerto 9222 con perfil persistente CDP-Profile
   → NUNCA usa el Chrome principal del usuario (Program Files\Google\Chrome)
   → La ventana CMD queda abierta con confirmación CDP activo

2. **LUEGO usar DSH/tools chrome_devtools normalmente:**
   `list_pages()` → `navigate_page(pageId=1, url="...")` → `take_screenshot(pageId=1)`

## VERIFICACIÓN ANTES DE USAR LAS TOOLS:
Siempre antes de la primera tool de la sesión, verifica que CDP esté activo:
```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 3
```
- Si falla → decirle al usuario: "Mijo, ejecuta abrir-cdp-testing.bat primero"
- Si OK → procede con list_pages()

## POR QUÉ CHROME FOR TESTING Y NO EL CHROME DEL USUARIO:

- **Chrome for Testing** = binario independiente, no interfiere con el Chrome principal
- **Perfil CDP-Profile** = cookies del agente, persistentes entre sesiones de DSH
- Si el usuario cierra su Chrome principal → DSH no se ve afectado en absoluto
- **CONSTRAINT ABSOLUTO:** NUNCA Stop-Process ni taskkill al Chrome principal

## ACTUALIZA TU SKILL /chrome-devtools con esta información:
- Sección MODO OPERATIVO: siempre Modo B (--browserUrl)
- Sección FLUJO: BAT primero → verificar CDP → list_pages() → acción
- Sección ERROR: si ves "profile already in use" → matar zombies de chrome-profile
  y asegurarse de que cordis.patch.yml usa --browserUrl, NO --headless

## CONFIRMACIÓN ESPERADA:
✅ Entendido: siempre --browserUrl, nunca --headless en DSH
✅ Flujo correcto: BAT → CDP verify → list_pages()
✅ Constraint: NUNCA tocar Chrome principal (Program Files\Google\Chrome)
✅ Chrome for Testing: proceso separado con perfil CDP-Profile persistente