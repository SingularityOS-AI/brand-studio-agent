name: chrome-devtools-mcp
description: >-
  Controla un Chrome for Testing separado (NUNCA el Chrome principal del
  usuario) via MCP chrome_devtools. Firmas CORREGIDAS para producción.
  Activar con /chrome-devtools para navegación automatizada, auditorías,
  debugging frontend y automatización web.

---

# SKILL: /chrome-devtools — Chrome DevTools MCP (PRODUCCIÓN)

## ACTIVACIÓN
Cuando el CEO invoca /chrome-devtools [tarea], o pide "automatiza X en el
navegador", "audita la web", "debuggea el frontend", "navega a Y".

## CONSTRAINT ABSOLUTO — LEE ESTO PRIMERO
**NUNCA** mates, detengas ni toques el Chrome del usuario.
El Chrome del usuario = C:\Program Files\Google\Chrome\Application\chrome.exe
Tu Chrome = C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe
Si no funciona, reporta: "Mijo, CDP 9222 no activo. Ejecuta abrir-cdp-testing.bat"

## CÓMO OBTENER EL pageId
### FLUJO OBLIGATORIO — SIEMPRE HACER PRIMERO:

1. **Llama list_pages()** — respuesta ejemplo:
   ```
   "1: about:blank [selected]"
   "2: Google (https://google.com)"
   "3: SingularityOS (https://...)"
   ```

2. **El número al inicio = pageId entero**
   - `1` → pageId=1
   - `2` → pageId=2
   - `3` → pageId=3

3. **"[selected]" = tab activo actual**

4. **Usa ese ENTERO en todas las tools siguientes**
   - NUNCA usar strings ("1", "2")
   - SIEMPRE usar números (1, 2, 3)

## CHROME QUE USAS (proceso separado, perfil persistente)
- **Binario:** C:\Users\gabri\AppData\Local\ChromeForTesting\chrome\win64-153.0.8010.52\chrome-win64\chrome.exe
- **Perfil (cookies):** C:\Users\gabri\AppData\Local\ChromeForTesting\CDP-Profile
- **Puerto CDP:** 9222
- **Script de arranque:** C:\Users\gabri\Desktop\SINGULARITYOS\.cromedebug\abrir-cdp-testing.bat
- **Cookies:** persisten entre sesiones
- **Chrome version:** 153.0.8010.52 (verificada en producción)

## VERIFICACIÓN CDP
```powershell
$r = Invoke-RestMethod http://127.0.0.1:9222/json/version -TimeoutSec 5
if ($r -and $r.Browser -match "Chrome/153") { "CDP activo" } else { "CDP inactivo" }
```

## TOOLS MCP DISPONIBLES (FIRMAS CORREGIDAS)

### HERRAMIENTAS BÁSICAS
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| list_pages() | `list_pages()` | Lista tabs, retorna "N: título [selected]" |
| new_page(url) | `new_page(url="https://...")` | Abre tab nuevo (NO usa pageId) |
| select_page(pageId) | `select_page(pageId=1)` | Cambia de tab (pageId entero) |
| close_page(pageId) | `close_page(pageId=1)` | Cierra tab específico (pageId entero) |

### NAVEGACIÓN
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| navigate_page(pageId, url) | `navigate_page(pageId=1, url="https://...")` | Navega URL (pageId entero) |
| take_screenshot(pageId) | `take_screenshot(pageId=1)` | Captura visual (pageId entero) |
| evaluate_script(pageId, script) | `evaluate_script(pageId=1, script="document.title")` | Ejecuta JS (pageId entero) |
| wait_for(pageId, selector) | `wait_for(pageId=1, selector=".btn")` | Espera elemento (pageId entero) |

### INTERACCIÓN
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| click(pageId, selector) | `click(pageId=1, selector=".btn")` | Click elemento (pageId entero) |
| fill(pageId, selector, value) | `fill(pageId=1, selector="#input", value="texto")` | Rellena input (pageId entero) |
| type_text(pageId, text) | `type_text(pageId=1, text="texto")` | Escribe texto (pageId entero) |
| press_key(pageId, key) | `press_key(pageId=1, key="Enter")` | Presiona tecla (pageId entero) |
| hover(pageId, selector) | `hover(pageId=1, selector=".link")` | Hover elemento (pageId entero) |
| handle_dialog(pageId, accept) | `handle_dialog(pageId=1, accept=True)` | Alertas (pageId entero) |
| upload_file(pageId, selector, path) | `upload_file(pageId=1, selector="[type=file]", path="C:/file.pdf")` | Sube archivo |

### DEBUGGING
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| list_console_messages(pageId) | `list_console_messages(pageId=1)` | Errores consola (pageId entero) |
| list_network_requests(pageId) | `list_network_requests(pageId=1)` | Requests red (pageId entero) |

### PERFORMANCE Y AUDITORÍA
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| performance_start_trace(pageId) | `performance_start_trace(pageId=1)` | Inicia traza (pageId entero) |
| performance_stop_trace(pageId, path) | `performance_stop_trace(pageId=1, path="trace.json")` | Stop traza (pageId entero) |
| lighthouse_audit(pageId, outputDir) | `lighthouse_audit(pageId=1, outputDir="audit/")` | Auditoría LH (pageId entero) |

### DEVICE Y RESIZE
| Tool | Firma Correcta | Uso |
|------|---------------|-----|
| emulate(pageId, viewport) | `emulate(pageId=1, viewport="375x812")` | Emula dispositivo (pageId entero) |
| resize_page(pageId, width, height) | `resize_page(pageId=1, width=1280, height=800)` | Cambia tamaño (pageId entero) |

## PROTOCOLO DE EJECUCIÓN

### PLAN OBLIGATORIO (antes de cualquier acción)
- TAREA: [qué harás]
- URL: [destino]
- pageId: [desde list_pages()]
- PASOS: 1. list_pages() → 2. navigate_page(pageId, url) → 3. ...

### LOOP DE ACCIÓN
1. **list_pages()** → identifica pageId del tab correcto
2. **Verifique pageId es ENTERO**: 1, 2, 3 (NO "1", "2", "3")
3. **Acción** → `action(pageId=ENTERO, otros_args)`
4. **take_screenshot(pageId=ENTERO)** → analiza resultado
5. Repite hasta completar tarea

### EJEMPLO COMPLETO
```text
TAREA: Navegar a Google y buscar "singularity"
PASOS:
1. list_pages() → "1: about:blank [selected]" → pageId=1
2. navigate_page(pageId=1, url="https://google.com")
3. take_screenshot(pageId=1) → verificar carga
4. click(pageId=1, selector="[name='q']")
5. fill(pageId=1, selector="[name='q']", value="singularity")
6. press_key(pageId=1, key="Enter")
7. take_screenshot(pageId=1) → ver resultados
```

## REGLAS CRÍTICAS
- **NUNCA usar strings para pageId**: Solo números 1, 2, 3...
- **SIEMPRE hacer list_pages() primero**
- **NUNCA Stop-Process Taskkill Chrome**
- **SIEMPRE plan antes de ejecutar**
- **Si endpoint 9222 no responde**: reporta "CDP inactivo"
- **Verificar con Invoke-RestMethod antes de actuar**

## TONO
Directo, español, modo copiloto. pageId = número entero.