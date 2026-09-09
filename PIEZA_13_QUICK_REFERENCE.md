# PIEZA 13 — Quick Reference

## Key Code Locations

### app/static/index.html

**Paywall Overlay HTML** (around line 249)
```html
<!-- Paywall Overlay -->
<div class="paywall-overlay" id="Paywall-Overlay" style="display:none">
  <div class="paywall-modal">
    <div class="paywall-header">
      <h2 class="paywall-title">You've used up your free credits</h2>
      <button class="paywall-close-btn" id="Paywall-CloseBtn">...</button>
    </div>
    <div class="paywall-body">
      <!-- 3 pricing cards (Starter, Pro, Studio) -->
    </div>
  </div>
</div>
```

**Paywall CSS Styles** (around line 440)
```css
.paywall-overlay { position:fixed; inset:0; ... z-index:10000; animation:fadeIn 0.2s ease; }
.paywall-modal { background:var(--surface); border-radius:16px; ... }
.paywall-cards { display:grid; grid-template-columns:repeat(3,1fr); ... }
.paywall-card.featured { border:2px solid var(--accent); ... }
.plan-btn { width:100%; ... transition:all 0.2s ease; }
/* + responsive styles for mobile */
```

### app/static/app.js

**Centralized 402 Handler in authenticatedFetch()** (around line 20)
```javascript
async function authenticatedFetch(url, options = {}) {
  if (!jwtToken) throw new Error('Not authenticated');
  options.headers = options.headers || {};
  options.headers['Authorization'] = `Bearer ${jwtToken}`;
  const response = await fetch(url, { ...options, credentials: 'same-origin' });

  // Centralized 402 handling - show paywall
  if (response.status === 402) {
    console.log('[Paywall] 402 response detected, showing paywall');
    showPaywall();
    throw new Error('PAYWALL_402');
  }

  return response;
}
```

**Paywall Functions** (around line 1150)
```javascript
function showPaywall() {
  if (paywallOverlay) paywallOverlay.style.display = 'flex';
}

function hidePaywall() {
  if (paywallOverlay) paywallOverlay.style.display = 'none';
}

function disableDepletedControls() {
  // Disable microphone
  if (micBtn) {
    micBtn.disabled = true;
    micBtn.style.background = 'var(--line)';
    micBtn.style.cursor = 'not-allowed';
    micBtn.title = 'No credits available - please purchase more to continue';
  }
  // Stop active session
  if (isSessionActive) stopSession();
}

function enableDepletedControls() {
  // Re-enable microphone
  if (micBtn) {
    micBtn.disabled = false;
    micBtn.style.background = '';
    micBtn.style.cursor = 'pointer';
    micBtn.title = '';
  }
}
```

**Updated updateCreditsUI() with Depleted State** (around line 1200)
```javascript
function updateCreditsUI(remaining, initial) {
  // ... existing UI update code ...

  // Check if depleted
  const wasDepleted = creditsDepleted;
  creditsDepleted = remaining <= 0;

  // If just became depleted, show paywall and disable controls
  if (!wasDepleted && creditsDepleted) {
    console.log('[Paywall] Credits depleted, enabling depleted mode');
    disableDepletedControls();
    showPaywall();
  } else if (wasDepleted && !creditsDepleted) {
    // If no longer depleted, re-enable controls
    console.log('[Paywall] Credits available again, disabling depleted mode');
    enableDepletedControls();
  }
}
```

**Placeholder Payment Buttons Handler** (around line 1180)
```javascript
document.querySelectorAll('.plan-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    const plan = btn.dataset.plan;
    alert(`Payments are not enabled yet. The ${plan} plan (${btn.textContent.trim()}) will be available when Stripe integration is added.`);
  });
});
```

## How It Works

### User Flow

1. **Credits reach 0**:
   ```
   updateCreditsUI(0, 250) called
   → creditsDepleted = true
   → disableDepletedControls()
   → showPaywall()
   ```

2. **User tries to start voice session**:
   ```
   toggleMicrophone() called
   → micBtn.disabled=true → no action
   ```

3. **User tries to generate Brand Soul**:
   ```
   generateBrandSoul() called
   → authenticatedFetch('/api/soul/generate')
   → response.status === 402
   → showPaywall()
   → throw Error('PAYWALL_402')
   ```

4. **User views existing Brand Soul**:
   ```
   GET /api/soul (no credits spent)
   → Works fine even with credits_balance=0
   ```

### 402 Response Flow

Any endpoint that returns 402:
```
/app/static/app.js
  authenticatedFetch('/api/voice/reserve', ...)
    response.status === 402
      → showPaywall()
      → throw Error('PAYWALL_402')

Caller receives error 'PAYWALL_402'
  → No alert shown (paywall already visible)
  → Graceful degradation
```

## Design Tokens

**Cool Paper Palette**:
- `--ground`: #E7EAF0 (background overlay)
- `--surface`: #FFFFFF (card backgrounds)
- `--ink`: #14181F (text)
- `--accent`: #2B4CD8 (buttons, links, featured border)
- `--line`: #D5DAE4 (borders)
- `--ink-soft`: #5C6675 (secondary text)

**Typography**:
- Display/Headings: 'Space Grotesk', Inter, sans-serif
- Body: Inter, -apple-system, Segoe UI, sans-serif
- Monospace: 'JetBrains Mono', ui-monospace, Consolas, monospace

## Test Commands

```bash
# Run all tests
pytest -v

# Run specific 402-related tests
pytest tests/test_voice_reserve.py::TestVoiceReserveEndpoint::test_reserve_voice_credits_402_insufficient_funds -v
pytest tests/test_guard_jwt.py::test_guard_jwt.py::test_budget_exhausted_returns_402 -v
```

## Manual Testing

```sql
-- Force credits to 0 in Supabase
UPDATE user_credits
SET credits_remaining = 0
WHERE user_id = 'YOUR_USER_ID';

-- Restore credits
UPDATE user_credits
SET credits_remaining = 250
WHERE user_id = 'YOUR_USER_ID';
```

Then test in browser:
1. Reload the page
2. Observe paywall appears
3. Try microphone (should be disabled)
4. Close paywall and try microphone again (paywall reappears)
5. If Brand Soul exists, view it (should work)
6. Try generating new Brand Soul (paywall appears)
