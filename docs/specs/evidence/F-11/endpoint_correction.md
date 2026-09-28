# F-11 Critical Fix: Correct `patchOverlays` Endpoint and Payload Mapping

## Issue
The `patchOverlays` function was targeting `/api/editing/{ideaId}/overlays`, which DOES NOT EXIST in the backend. This would cause 404 errors in production.

## Solution
Updated `patchOverlays` to target the correct endpoint `/api/editing/{ideaId}/settings` and properly map payload to backend's `SettingsPatchBody` schema.

## Endpoint Change
❌ **Old (incorrect)**: `/api/editing/${encodeURIComponent(ideaId)}/overlays`
✅ **New (correct)**: `/api/editing/${encodeURIComponent(ideaId)}/settings`

## Payload Mapping

### Input from Actions
- `delete_overlay` passes: `{ op: "delete", overlayKey: args.n }`
- `overlays_enabled` passes: `{ op: "enabled", enabled: args.value }`

### Transformed for Backend (SettingsPatchBody)
```javascript
// Delete overlay
{
  op: "overlay_delete",
  overlay_id: String(payload.overlayKey),
  expected_version: currentEditingState.edit_version || 1
}

// Toggle overlays
{
  op: "overlays_enabled",
  value: Boolean(payload.enabled),
  expected_version: currentEditingState.edit_version || 1
}
```

## Implementation
```javascript
async function patchOverlays(ideaId, payload) {
  let body = payload;
  if (payload.op === "delete") {
    body = {
      op: "overlay_delete",
      overlay_id: String(payload.overlayKey || payload.overlay_id),
      expected_version: (currentEditingState && currentEditingState.edit_version) || 1
    };
  } else if (payload.op === "enabled") {
    body = {
      op: "overlays_enabled",
      value: Boolean(payload.enabled !== undefined ? payload.enabled : payload.value),
      expected_version: (currentEditingState && currentEditingState.edit_version) || 1
    };
  }

  const res = await fetch(`/api/editing/${encodeURIComponent(ideaId)}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to patch overlays");
  }
  return res.json();
}
```

## Verification
- ✅ `node --check app/static/editing.js` - passes
- ✅ `node --test tests/agent_editing.test.js` - 20/20 tests pass
- ✅ Endpoint changed from `/overlays` to `/settings`
- ✅ Payload properly mapped to `SettingsPatchBody` schema
- ✅ Includes `expected_version` for concurrency control
- ✅ Committed and pushed to branch `agent/F-11-editing-tools`

## Backend Reference
This now correctly targets `PATCH /api/editing/{idea_id}/settings` in `app/editing/router.py` which handles overlay operations via `SettingsPatchBody`.
