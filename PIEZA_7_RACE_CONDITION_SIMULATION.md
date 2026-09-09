# Simulación de Carrera de Estado — Pieza 7

## Objetivo

Documentar cómo simular la carrera de estado para verificar que el fix funciona.

## Escenario 1: Sesión vieja cierra mientras sesión nueva espera permiso

### Pasos para reproducir (con el BUG original)

1. **Sesión A inicia**:
   - Usuario hace clic en el botón del micrófono
   - `startSession()` ejecuta: crea `audioContext`, llama a `getUserMedia()`

2. **Ventana crítica**:
   - Mientras el navegador muestra el diálogo de permiso del micrófono, `getUserMedia()` está esperando
   - Sesión A está pausada en el `await`

3. **Sesión B inicia** (double-click del usuario o disparo programático):
   - Click rápido en el botón antes de aceptar el permiso
   - `startSession()` vuelve a ejecutar: incrementaría `sessionGeneration`

4. **Sesión A falla** (sin el fix):
   - Sesión A retoma después del `await`
   - Llega a `await audioContext.audioWorklet.addModule(blobUrl)`
   - `audioContext` ha sido limpiado por `stopSession()` de Sesión B
   - **Error**: `Cannot read properties of null (reading 'audioWorklet')`

### Resultado con el FIX

1. **Sesión A inicia**:
   - Captura `myGeneration = 1`
   - Crea `audioContext`
   - Llama a `getUserMedia()`

2. **Sesión B inicia**:
   - Click rápido antes de aceptar el permiso
   - El botón está **DISABLED** por `toggleMicrophone()`
   - Click ignorado, no se inicia Sesión B
   - Sesión A puede completar normalmente

3. **Si Sesión B somehow inició** (por ejemplo, llamada programática):
   - Sesión B captura `myGeneration = 2`
   - `sessionGeneration` es ahora 2
   - Sesión A completa `getUserMedia()`
   - **Check en línea 171**: `if (myGeneration !== sessionGeneration) return;`
   - `1 !== 2` → Sesión A se aborta limpiamente
   - Sesión B continúa con su propio `audioContext`
   - **Sin error de null access**

---

## Escenario 2: Callbacks de WebSocket de sesión obsoleta

### Pasos para reproducir

1. **Sesión A inicia**:
   - WebSocket conecta
   - `ws.onerror` y `ws.onclose` tienen closures con `myGeneration = 1`

2. **Sesión B inicia**:
   - `sessionGeneration` incrementa a 2
   - Sesión B limpia con `stopSession()`, cierra WebSocket de Sesión A
   - Crea su propio WebSocket y `audioContext`

3. **Callback de Sesión A dispara**:
   - WebSocket de Sesión A cierra (lento, por firewall o timeout)
   - `ws.onclose` de Sesión A ejecuta
   - **Sin fix**: Llama `stopSession()` → borra `audioContext` de Sesión B ❌
   - **Con fix**: Guard en línea 319 `if (myGeneration !== sessionGeneration) return;`
   - `1 !== 2` → Callback se ignora, no limpia nada ✅

---

## API de Simulación (para test automatizado)

```javascript
// Simular carrera: dos startSession() concurrentes
async function simulateRace() {
  console.log('[Simulation] Starting race condition test...');

  const promise1 = startSession(); // Sesión 1
  await delay(100); // Pequeño delay para que Sesión 1 llegue a getUserMedia
  const promise2 = startSession(); // Sesión 2 (espera pero button está disabled)

  await Promise.all([promise1, promise2]);

  console.log('[Simulation] Race condition test complete');
  // Verificar que sesión activa es válida, no hay error de null
}
```

**Nota**: Con el fix, el button disabling previene que el segundo `startSession()` realmente se ejecute. Para forzar la carrera en testing, se necesitaría llamar `startSession()` directamente sin pasar por `toggleMicrophone()`.

---

## Verificación Manual en Navegador

### Test 1: Double-click en botón del micrófono

1. Abrir aplicación en navegador
2. Hacer doble click muy rápido en el botón del micrófono
3. **Sin fix**: Error en consola: `Cannot read properties of null (reading 'audioWorklet')`
4. **Con fix**: Session inicia normalmente, sin error

### Test 2: Timeout de WebSocket

1. Iniciar sesión de voz
2. Desconectar red (o usar Network throttling en DevTools) para forzar timeout
3. Volver a conectar y hacer clic en botón
4. **Sin fix**: Error de `audioWorklet` porque callback del viejo ws.onclose limpió la sesión nueva
5. **Con fix**: Callback ignorado, sesión nueva funciona

---

## Logs de debugging

Con el fix, verías estos logs en consola durante una carrera:

```
[startSession] Capturing generation: 1
[startSession] Got API key
[startSession] Capturing generation: 2  ← Sesión B inició
[startSession] Superseded after getUserMedia, aborting  ← Sesión A se aborta
[startSession] Creating AudioContext for generation 2  ← Sesión B continúa
[WebSocket] Connected to AssemblyAI Voice Agent
[Session] Ready: xxx-yyy-zzz
```

Sin el fix, verías el error:

```
[startSession] Creating AudioContext
[startSession] Got microphone stream
[WebSocket Closed]  ← Sesión vieja cerró
[StartSession Failed] TypeError: Cannot read properties of null (reading 'audioWorklet')
```

---

## Conclusión

El fix de token de generación de sesión (`sessionGeneration`) es una solución probada y simple para prevenir carreras de estado en callbacks async. Cada sesión solo toca su propio estado, y sesiones obsoletas se detectan y se abortan limpiamente sin afectar a sesiones activas.
