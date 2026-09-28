# F-11 Bug Fix: Add Missing `patchOverlays` Function

## Issue
Two voice actions (`delete_overlay` and `overlays_enabled`) were calling `patchOverlays()` function that did not exist, causing `ReferenceError: patchOverlays is not defined` at runtime.

## Fix Applied
Added `patchOverlays` function to `app/static/editing.js` at line 231, following the same pattern as other async API wrappers.

### Function Signature
```javascript
async function patchOverlays(ideaId, payload) {
  const res = await fetch(`/api/editing/${encodeURIComponent(ideaId)}/overlays`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to patch overlays");
  }
  return res.json();
}
```

### Usage in Voice Actions
1. **delete_overlay** (line 455):
```javascript
return await patchOverlays(args.ideaId, {
  op: "delete",
  overlayKey: args.n
});
```

2. **overlays_enabled** (line 465):
```javascript
return await patchOverlays(args.ideaId, {
  op: "enabled",
  enabled: args.value
});
```

## Verification
- Syntax check: `node --check app/static/editing.js` → ✅ Clean
- Test suite: `node --test tests/agent_editing.test.js` → ✅ 20/20 tests passed
- Git diff confirms function is committed and pushed

## Backend API
The function calls `PATCH /api/editing/{ideaId}/overlays` which exists in router.py:987-1023.
