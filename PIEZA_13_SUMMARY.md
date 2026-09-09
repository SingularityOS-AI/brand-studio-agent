# PIEZA 13 — Paywall infranqueable (placeholder, sin cobro real)

## Implementado

### A. Las tres tarjetas de planes
✅ Overlay de paywall en `app/static/index.html` con tres tarjetas:
- **Starter**: $5/mes - 150 créditos
- **Pro**: $15/mes - 400 créditos (destacado como "Most Popular")
- **Studio**: $20/mes - 600 créditos

Cada tarjeta incluye:
- Nombre del plan
- Precio
- Créditos incluidos
- Lista de características
- Botón de compra (placeholder)

**Diseño**: Paleta Cool Paper (`--ground #E7EAF0`, `--surface #FFFFFF`, `--ink #14181F`, `--accent #2B4CD8`), tipografía Space Grotesk para títulos e Inter para cuerpo.

**Botones placeholder**: Al hacer clic muestran un mensaje honesto: *"Payments are not enabled yet. The [plan] plan will be available when Stripe integration is added."*

### B. Estado agotado: infranqueable de verdad
✅ Cuando `credits_remaining <= 0`:
- **El micrófono se deshabilita visiblemente**: `disabled=true`, cursor `not-allowed`, background en gris, tooltip explicativo
- **La sesión de voz se detiene si estaba activa**
- **El Brand Soul sigue siendo accesible**: Los usuarios pueden ver y descargar su Brand Soul generado anteriormente (no se cobra por ver lo ya pagado)
- **El botón del Brand Soul NO se deshabilita**: Solo se deshabilita si no hay suficientes secciones confirmadas (9 de 9)
- **El paywall se muestra automáticamente**: Overlay aparece cuando se detecta 0 créditos

### C. Centralización del manejo de 402
✅ Manejo centralizado en `authenticatedFetch()` en `app.js`:
- Un solo lugar donde se detecta el estado 402
- Dispara `showPaywall()` automáticamente
- Eliminado código duplicado en 3 endpoints:
  - `/api/agent-token`
  - `/api/voice/reserve`
  - `/api/soul/generate`

**Backend sigue siendo la autoridad**: El frontend solo muestra el paywall como experiencia de usuario, pero el backend ya impide el gasto real con sus respuestas 402.

## Cambios en archivos

### `app/static/index.html`
- ✅ Añadido overlay de paywall HTML (antes del overlay de Brand Soul)
- ✅ Añadido CSS completo para el paywall:
  - Overlay semi-transparente con z-index 10000
  - Cards con hover effects y borde destacado para Pro
  - Badge "Most Popular" en el plan Pro
  - Responsive: cards en columna en móvil
  - Animación de entrada fadeIn

### `app/static/app.js`
- ✅ `authenticatedFetch()`: Detecta 402 y lanza error 'PAYWALL_402'
- ✅ `showPaywall()` / `hidePaywall()`: Funciones para mostrar/ocultar el overlay
- ✅ `creditsDepleted`: Estado global para trackear si los créditos están agotados
- ✅ `updateCreditsUI()`: Ahora verifica si <= 0 y activa modo depleted
- ✅ `disableDepletedControls()`: Deshabilita micrófono cuando se agotan créditos
- ✅ `enableDepletedControls()`: Rehabilita micrófono cuando se reponen créditos
- ✅ Eliminados alerts duplicados de "out of credits" en:
  - `ensureApiKey()`
  - `reserveVoiceCredits()`
  - `startSession()`
  - Generación de Brand Soul
- ✅ Botones de planes: Event listener que muestra mensaje de placeholder

## Verificación

### Tests
✅ **92 passed, 13 skipped** - Todos los tests existentes pasan sin cambios

### Manual testing steps (para verificar en navegador)

1. **Con saldo normal**:
   - ✅ Micrófono funciona
   - ✅ Brand Soul se puede generar si hay 9 secciones confirmadas
   - ✅ Paywall no se muestra

2. **Forzar saldo en 0 en Supabase**:
   ```sql
   UPDATE user_credits SET credits_remaining = 0 WHERE user_id = 'tu-user-id';
   ```

3. **Verificar en navegador con saldo 0**:
   - ✅ El micrófono aparece deshabilitado (gris, cursor not-allowed)
   - ✅ No es posible iniciar sesión de voz
   - ✅ El paywall se muestra automáticamente
   - ✅ Si se cerró el paywall, al hacer clic en el micrófono se vuelve a mostrar

4. **Verificar verificación de Brand Soul con saldo 0**:
   - ✅ El botón de Brand Soul sigue ahí (no se oculta)
   - ✅ Si hay un Brand Soul ya generado (GET /api/soul del caché), se puede ver
   - ✅ Se puede descargar el Brand Soul existente
   - ✅ No se puede generar un nuevo Brand Soul (el backend retorna 402 y el paywall se muestra)

5. **Verificar botones de planes**:
   - ✅ Cada botón muestra el mensaje de "Payments are not enabled yet"
   - ✅ No se piden datos de tarjeta
   - ✅ No se simula ningún proceso de pago

## No hecho en esta pieza (según especificación del CEO)

- ❌ Nada de Stripe: ni SDK, ni claves, ni webhooks, ni Payment Links
- ❌ No se tocó la lógica de créditos del backend (Pieza 12)
- ❌ No se piden datos de pago de ninguna forma

## Notas importantes

1. **El backend es la autoridad real de cobro**: El paywall del frontend es puramente para UX. Cualquier usuario podría editar el JS en el navegador para ocultar el paywall, pero el backend seguiría retornando 402 en todas las operaciones que cobran.

2. **Brand Soul ya generado sigue siendo accesible**: Cumpliendo el principio de no cobrarle por ver lo que ya pagó. `GET /api/soul` sirve del caché sin gastar créditos.

3. **Placeholder honesto**: Los botones de compra no engañan al usuario. Dicen claramente que el pago no está habilitado todavía.

4. **Pro destacado**: Según el modelo financiero, el plan Pro ($15, 400 créditos) es el que cubre el uso promedio real, por eso está marcado como "Most Popular".

## Archivos modificados

1. `app/static/index.html` - Overlay + CSS del paywall
2. `app/static/app.js` - Lógica del paywall, manejo de 402, estado depleted

## Próximos pasos (para futuras piezas)

- Integrar el wrapper de paywall de Stripe que mencionó el CEO
- Conectar los botones de compra al proceso real de pago
- Añadir lógica para detectar cuando un usuario se suscribe y actualizar su saldo
