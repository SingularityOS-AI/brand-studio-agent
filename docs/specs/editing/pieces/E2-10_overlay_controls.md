# Piece E2-10: Overlay Controls (delete / edit text / on-off)

## Summary

Allow founders to control overlays in their videos by:
1. Deleting individual overlays
2. Editing overlay text
3. Toggling all overlays on/off

All operations are FREE (0 credits).

## User-Facing Behavior

### Delete Overlay
- Founder can delete any overlay from the video
- Deleted overlays are marked with `{deleted: true}` in settings
- Founder can restore a deleted overlay at any time
- Deleting is reversible - no permanent data loss

### Edit Overlay Text
- Founder can edit the text of any overlay
- Text is limited to 80 characters maximum
- Text is sanitized using the caption sanitizer (E2-06)
- Text is fitted using the card fit algorithm (E2-04) with `<br>` line breaks
- Editing does not affect other overlays

### Toggle Overlays On/Off
- Founder can toggle ALL overlays on or off with a global switch
- When off: IR has 0 overlays, overlay pop sound effects are dropped
- When on: All active (non-deleted) overlays appear in the video
- This is useful for A/B testing or preview without overlays

## Changes to Data Model

### edit.settings.overlays

All overlay controls write to `edit.settings.overlays`.

Structure:
```javascript
{
  "overlays": {
    "ov_s{n}_{k}": {
      "deleted": true  // Mark overlay as deleted
    }
    // OR
    "ov_s{n}_{k}": {
      "text": "Edited text here"  // Edit overlay text (max 80 chars)
    }
  },
  "overlays_enabled": true  // Global toggle (default: true)
}
```

Key constraint: `edit.dressing` is NEVER modified. All changes go through `settings.overlays`.

## Backend API Operations

### overlay_delete (FREE)
- **URL**: `POST /api/editing/settings`
- **Body**: `{ "operation": "overlay_delete", "overlay_id": "ov_s{n}_{k}" }`
- **Behavior**: Sets `{ "deleted": true }` in `edit.settings.overlays[overlay_id]`
- **Cost**: 0 credits
- **Validation**: overlay_id must exist and be a valid overlay id (`ov_s{n}_{k}` format)

### overlay_text (FREE)
- **URL**: `POST /api/editing/settings`
- **Body**: `{ "operation": "overlay_text", "overlay_id": "ov_s{n}_{k}", "text": "New text" }`
- **Behavior**: Sets `{ "text": sanitized_value }` in `edit.settings.overlays[overlay_id]`
- **Cost**: 0 credits
- **Validation**:
  - overlay_id must exist and be valid
  - text must be ≤ 80 characters (returns 422 if exceeded)

### overlays_enabled (FREE)
- **URL**: `POST /api/editing/settings`
- **Body**: `{ "operation": "overlays_enabled", "value": true/false }`
- **Behavior**: Sets `edit.settings.overlays_enabled` to boolean
- **Cost**: 0 credits

## RenderIR Changes (Stage 2)

In `app/editing/ir.py`, during RenderIR stage 2 overlay application:

1. **Parse overlay settings** from `edit.settings.overlays`
2. **Apply overrides** to each overlay:
   - If `{deleted: true}`: Skip this overlay entirely
   - If `{text: "..."}`: Use edited text (sanitized + fitted)
3. **Apply global toggle**:
   - If `settings.overlays_enabled === false`: Remove all overlays from IR
   - If `settings.overlays_enabled === true`: Add all active (non-deleted) overlays

### Text Processing for Edited Overlays

Edited overlay text must be processed in this order:
1. Sanitize with caption sanitizer (`sanitize_text()` from `metadata.py`)
2. Fit with card fit algorithm (`fit_card_text()` from render service) with `<br>` line breaks

### Overlay Sound Effects

Overlay pop SFX are only added when `settings.overlays_enabled === true`.
If disabled, all overlay pop SFX are dropped from the audio timeline.

## Frontend Changes

### Editing.js Actions

Add three new `EDIT_ACTIONS` (all with `credits: 0`):

```javascript
{
  action: "delete_overlay",
  credits: 0,
  params: { overlay_id: "ov_s{n}_{k}" }
}

{
  action: "edit_overlay_text",
  credits: 0,
  params: { overlay_id: "ov_s{n}_{k}", text: "New text" }
}

{
  action: "toggle_overlays",
  credits: 0,
  params: { value: true/false }
}
```

### UI Elements

Add to the overlays section in editing UI:

1. **Overlay List**:
   - For each overlay, show:
     - Timestamp overlay appears in the video
     - Delete/Restore button
     - Edit text button

2. **Delete/Restore**:
   - When deleted: Show "Restore" button, strikethrough style, reduced opacity
   - When active: Show "Delete" button

3. **Edit Text**:
   - Inline editing in the overlay element
   - Press Enter to save
   - Press Escape to cancel
   - Validate length (≤ 80 chars) before saving

4. **Global Toggle**:
   - "All overlays: [ON]" / "All overlays: [OFF]" switch
   - Toggle affects all overlays immediately

### String Requirements (English UI Only)

All user-facing strings must be in English:
- "Delete" / "Restore" button text
- "Edit" button text
- "All overlays" switch label
- Any validation error messages

## Allowed Files

You may ONLY touch these files:

- `app/editing/router.py` - Add the three new operations to allowed_ops
- `app/editing/ir.py` - Parse and apply overlay settings in stage 2
- `app/static/editing.js` - Add UI controls and EDIT_ACTIONS
- `tests/test_editing_e2_10_overlay_controls.py` - Test suite (see Tests section)
- `docs/specs/evidence/E2-10/evidence.md` - Evidence documentation
- `docs/specs/evidence/E2-10/pytest_output.txt` - Literal pytest output

## Tests

Create `tests/test_editing_e2_10_overlay_controls.py` with these test cases:

1. **test_overlay_delete**
   - Call `overlay_delete` operation
   - Verify `{ "deleted": true }` is set in `edit.settings.overlays[overlay_id]`
   - Verify `edit.dressing` is not modified

2. **test_overlay_text_edit**
   - Call `overlay_text` operation with valid text
   - Verify text is saved and sanitized in `edit.settings.overlays[overlay_id]`
   - Verify `edit.dressing` is not modified

3. **test_overlay_text_max_length**
   - Call `overlay_text` operation with text > 80 characters
   - Verify HTTP 422 (Unprocessable Entity) is returned
   - Verify text is NOT saved

4. **test_overlays_enabled_toggle**
   - Call `overlays_enabled` operation with `true`
   - Verify `edit.settings.overlays_enabled` is `true`
   - Call again with `false`
   - Verify `edit.settings.overlays_enabled` is `false`

5. **test_overlay_settings_do_not_modify_dressing**
   - Call all three operations
   - Verify `edit.dressing` is never modified
   - Only `edit.settings.overlays` and `edit.settings.overlays_enabled` are modified

6. **test_overlay_delete_restore**
   - Call `overlay_delete` to delete an overlay
   - Verify overlay is marked as deleted
   - Delete the `{ "deleted": true }` setting (simulate restore)
   - Verify overlay is no longer deleted

7. **test_overlays_disabled_no_sfx**
   - Create an edit with overlays
   - Set `overlays_enabled` to `false`
   - Verify IR has 0 overlays
   - Verify overlay pop SFX are not in the SFX list

### Test Pattern (Copy from E2-05)

Use the TestClient pattern from E2-05:
- Import router and dispatch modules directly
- Use FastAPI TestClient
- Autouse fixture mocking:
  - `supabase_auth.get_user_id` → return "u1"
  - `guard.get_or_create_user_session` → return "tok_test"
  - `_check_script` → return dummy script object (use real Script model, not MockScript)

**WARNING**: DO NOT create a MockScript class. Use the real `Script` model from the domain, instantiated with valid fixture data (as dictionaries).

## Definition of Done

- ✅ All three API operations work correctly
- ✅ Tests pass (7/7 for E2-10 specific tests)
- ✅ Ruff clean on all modified .py files
- ✅ Node --check clean on editing.js
- ✅ Evidence saved in `docs/specs/evidence/E2-10/` with literal output:
  - `pytest -v` output in `pytest_output.txt`
  - `ruff check` output in `evidence.md`
  - `node --check` output in `evidence.md`
- ✅ No XSS vulnerabilities (no innerHTML with user data)
- ✅ All user-facing strings are in English
- ✅ NO files modified beyond allowed list
- ✅ NO MockScript in tests (use real Script model)

## Edge Cases

- Deleting an overlay that doesn't exist: Return 400
- Editing text of a deleted overlay: Allow, but won't show until restored
- Editing text with special characters: Sanitize before saving
- Editing text with line breaks: Convert to `<br>` using fit_card_text
- Toggle overlays while editing: Apply immediately to preview

## Related Pieces

- **E2-04**: Text fit algorithm (used when editing overlay text)
- **E2-05**: TestClient pattern (use same autouse fixture pattern)
- **E2-06**: Caption sanitizer (used when editing overlay text)
