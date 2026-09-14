# Test Mode Webhook Setup - Guide Ready for Production

## Current State - TEST MODE (No Real Charges)
✅ Stripe Test Mode activated
✅ Test card `4242 4242 4242 4242` works
✅ Credits update correctly after payment
✅ Webhook signature verification working

---

## When Ready for LIVE MODE Production

### Paso 1: Cambiar a Live Mode en el Dashboard de Stripe
1. Ve a [Stripe Dashboard](https://dashboard.stripe.com)
2. En la esquina superior izquierda, cambia el toggle de **"Test mode"** a **"Live"**
3. Navega a **Developers → Webhooks**

### Paso 2: Crear el Webhook en Live Mode
1. Haz clic en botón **"Add endpoint"** (añadir endpoint)
2. **Endpoint URL**: `https://brand-studio-agent.onrender.com/api/stripe/webhook`
3. **Eventos a escuchar** (selecciona estos dos):
   - ☑ `checkout.session.completed`
   - ☑ `payment_intent.succeeded`
4. Haz clic en **"Add endpoint"** (añadir endpoint)

### Paso 3: Obtener el Webhook Secret
1. Después de crear el endpoint, haz clic en él para ver los detalles
2. Desplázate hacia abajo hasta **"Signing secret"** (secreto de firma)
3. Haz clic en **"Reveal"** (o cópialo directamente)
4. El secreto estará en formato: `whsec_live_...`
5. **❗ COPIA ESTE SECRETO** - lo necesitará para Render

### Paso 4: Configurar en Render Dashboard
Ve a [Render Dashboard](https://dashboard.render.com) → servicio `brand-studio-agent` → **Environment**

Añade estas variables de entorno:

| Variable de entorno | Valor | Sincronizar |
|---------------------|-------|-------------|
| `STRIPE_SECRET_KEY` | `sk_live_...` (tu secret key de Live mode) | ❌ No |
| `STRIPE_PUBLISHABLE_KEY` | `pk_live_...` (tu publishable key de Live mode) | ❌ No |
| `STRIPE_WEBHOOK_SECRET` | `whsec_live_...` (del Paso 3) | ❌ No |

**Para obtener las claves de Live mode:**
- En Stripe Dashboard (Live mode) → **Developers → API keys**
- Copia "Publishable key" (pk_live_...) para `STRIPE_PUBLISHABLE_KEY`
- Copia "Secret key" (sk_live_...) para `STRIPE_SECRET_KEY`

---

## ⚠️ ADVERTENCIA MUY IMPORTANTE - LIVE MODE COBRARÁ DINERO REAL

**El modo Live de Stripe acepta pagos REALES:**
- ❌ Las tarjetas de prueba (`4242 4242 4242 4242`) NO funcionan
- ✅ Solo se aceptan tarjetas de crédito verdaderas
- ❌ Cualquier pago se cobrará de verdad
- ❌ Esto activa reportes de impuestos al IRS (estadounidenses)

**Antes de activar Live mode:**
1. Asegúrate de estar listo para recibir pagos reales
2. Configura las tax rates de Stripe si necesitas manejar impuestos
3. Prueba el flujo completo en modo Test con la tarjeta `4242 4242 4242 4242`
4. Verifica que los créditos se agreguen correctamente

---

## Verificación del Webhook

Una vez activado Live mode y configurado en Render:

### 1. Probar webhook desde Stripe Dashboard
- En Stripe Dashboard → Webhooks → tu endpoint
- Haz clic en **"Send test webhook"** (enviar webhook de prueba)
- Selecciona `checkout.session.completed`
- Ve a los logs de Render: debería mostrar `[WEBHOOKS] Received event: ...`

### 2. Prueba de pago real (PRECAUCIÓN: cobro verdadero)
- Usa una tarjeta de crédito real
- Completa el flujo de checkout
- Verifica que los créditos aparezcan en Supabase
- Confirma que el usuario permanezca logueado después del pago

---

## Troubleshooting (Solución de problemas)

### Error: "Webhook signature verification failed"
- Verifica que `STRIPE_WEBHOOK_SECRET` coincida EXACTAMENTE con el del Dashboard de Stripe
- Revisa que no haya espacios extra o saltos de línea
- Confirma que estás usando el secreto de LIVE mode, no de test mode

### El webhook no recibe eventos
- Verifica que el servicio en Render esté ejecutándose (estado verde)
- Confirma que la URL del endpoint sea correcta: `https://brand-studio-agent.onrender.com/api/stripe/webhook`
- Revisa los logs de entrega del webhook en el Dashboard de Stripe

### Los créditos no se actualizan después del pago
- Revisa los logs de Render para ver si el webhook se procesó
- Verifica la conexión con Supabase (`SUPABASE_URL`, `SUPABASE_KEY`)
- Confirma que el tipo de evento del webhook se esté manejando

---

## Eventos del Webhook Soportados

Actualmente el código maneja estos eventos:
- ✅ `checkout.session.completed` - Agrega créditos al usuario
- ✅ `payment_intent.succeeded` - Handler de fallback

---

## Checklist para Producción

Antes de declarar "FULL IN PRODUCTION":

- [ ] Obtener secretos de Live mode (sk_live_..., pk_live_..., whsec_live_...)
- [ ] Crear webhook en Live mode apuntando a `https://brand-studio-agent.onrender.com/api/stripe/webhook`
- [ ] Configurar las 3 variables de entorno en Render Dashboard
- [ ] Probar webhook con evento de prueba desde Stripe Dashboard
- [ ] Verificar logs de Render muestran procesamiento del webhook
- [ ] Prueba de pago real (monto pequeño) con tarjeta real
- [ ] Confirmar que los créditos aparecen en Supabase
- [ ] Confirmar que el usuario permanece logueado después del pago
- [ ] Probar botón de logout en la interfaz
- [ ] ✅ **FULL IN PRODUCTION DEPLOYMENT READY**

---

## Recursos Útiles

- [Stripe Dashboard](https://dashboard.stripe.com/test/dashboard) - Cambiar a Live mode en la esquina superior izquierda
- [Stripe Webhooks Documentation](https://stripe.com/docs/webhooks)
- [Render Dashboard](https://dashboard.render.com) - Configuración de Environment Variables
- [Render Free Plan Documentation](https://render.com/docs/free)

---

**Estado actual: Manteniendo Test Mode hasta aprobación del CEO para Live mode** ⚠️
