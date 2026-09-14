# Stripo Webhook Setup - Production Deployment Guide

## Current State
- **Test Mode**: Currently using Stripe test keys (`sk_test_`/`pk_test_`)
- **Webhook Secret**: Placeholder in .env (`whsec_PEGA_AQUI_LO_QUE_TE_DE_STRIPE_LISTEN`)
- **Production URL**: `https://brand-studio-agent.onrender.com`

---

## Steps to Configure Live Mode Webhook

### Step 1: Switch to Live Mode in Stripe Dashboard
1. Login to [Stripe Dashboard](https://dashboard.stripe.com)
2. Click the toggle at the top left to switch **"Test mode" → "Live"**
3. Navigate to **Developers → Webhooks**

### Step 2: Create Live Mode Webhook
1. Click **"Add endpoint"** button
2. **Endpoint URL**: `https://brand-studio-agent.onrender.com/api/stripe/webhook`
3. **Events to listen for**:
   - ✓ `checkout.session.completed`
   - ✓ `payment_intent.succeeded`
4. Click **"Add endpoint"**

### Step 3: Get the Webhook Secret
1. After creating the endpoint, click on it to view details
2. Scroll down to **"Signing secret"**
3. Click **"Reveal"** (or copy directly)
4. The secret will be in format: `whsec_live_...`
5. **Copy this secret** - you'll need it for Render

### Step 4: Configure Render Dashboard (Environment Variables)
Login to [Render Dashboard](https://dashboard.render.com) and go to **brand-studio-agent** service → **Environment**

Add these environment variables:

| Key | Value | Sync |
|-----|-------|------|
| `STRIPE_SECRET_KEY` | `sk_live_...` (your live secret key) | No |
| `STRIPE_PUBLISHABLE_KEY` | `pk_live_...` (your live publishable key) | No |
| `STRIPE_WEBHOOK_SECRET` | `whsec_live_...` (from Step 3) | No |

### Step 5: Verify Webhook is Working
After Render deployment completes:

1. **Test webhook delivery**:
   - In Stripe Dashboard → Webhooks → Click your endpoint
   - Click **"Send test webhook"** (select `checkout.session.completed`)
   - Check Render logs: should show `[WEBHOOKS] Received event: ...`

2. **Real payment test** (WARNING: Real charges with Live mode):
   - Use a real credit card
   - Complete checkout flow
   - Verify credits are added in Supabase

---

## Important Notes

⚠️ **WARNING**: Live mode accepts real payments
- Test cards (`4242 4242 4242 4242`) will NOT work in Live mode
- Any payment attempt will charge a real credit card
- This triggers IRS tax reporting requirements

🔒 **Security**:
- Never expose webhook secrets in code or git
- Only store in Render Environment Variables
- Use `sync: false` for all secrets in render.yaml

📝 **Webhook Events**:
Currently handled:
- `checkout.session.completed` → Adds credits to user
- `payment_intent.succeeded` → Fallback handler

---

## Troubleshooting

### Webhook fails with "Invalid signature"
- Verify `STRIPE_WEBHOOK_SECRET` matches exactly what's in Stripe Dashboard
- Check no extra spaces or line breaks

### Webhook not receiving events
- Verify Render service is running (green status)
- Check endpoint URL is correct: `https://brand-studio-agent.onrender.com/api/stripe/webhook`
- View webhook delivery logs in Stripe Dashboard

### Credits not updating after payment
- Check Render logs for webhook processing
- Verify Supabase connection (`SUPABASE_URL`, `SUPABASE_KEY`)
- Check webhook event type is handled

---

## Next Steps After Configuration

Once webhook is verified working:
1. [ ] Update local .env with live keys for testing (optional)
2. [ ] Run end-to-end test with small payment amount
3. [ ] Verify credits appear in Supabase
4. [ ] Test user stays logged in after payment (no flicker)
5. [ ] Test logout button functionality
6. [ ] **FULL IN PRODUCTION DEPLOYMENT READY** ✅
