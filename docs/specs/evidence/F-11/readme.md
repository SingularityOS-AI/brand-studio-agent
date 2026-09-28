# F-11 (Editing Voice Tools) - Implementation Evidence

## Scope
Piece F-11 implements 14 editing voice tools for the agentic mode.

Authorized Files:
- `app/static/agent.js` - EDIT_ACTION_SCHEMAS constant + toolsForStep integration
- `app/static/actions.js` - 14 editing action registrations with BrandStudioActions
- `app/static/editing.js` - EDIT_ACTIONS extensions, loadEditingState public API
- `tests/agent_editing.test.js` - Node harness tests
- `tests/test_agent_f11.py` - Python backend integration tests
- `docs/specs/evidence/F-11/*` - Evidence directory

## Key Technical Implementations

### 1. Action Registry Pattern (F-04)
All editing tools use `window.BrandStudioActions` wrapper:
- Free tools (`needsConfirm: false`): `edit_build_raw`, `edit_auto_edit`, `edit_scene_visual`, `edit_trim`, `edit_music`, `edit_sfx`, `edit_fix_caption`, `edit_caption_position`, `edit_overlay_delete`, `edit_overlays`, `edit_post_copy`, `edit_share_link`
- Paid tools (`needsConfirm: true`): `edit_try_another_take` (2 credits), `edit_render` (dynamic cost)

### 2. Confirmation Engine (F-06)
Two-step flow for paid actions:
1. Propose → Restatement with cost → Wait for explicit voice confirmation
2. Execute on confirmation

### 3. Dynamic Pricing
`edit_render` reads `state.render_price` at runtime:
- 20 credits for first render
- 5 credits for re-render
- 0 credits for engine update

### 4. Word Resolution
`edit_fix_caption` matches word string against `state.captions_words` to get `^s\d+w\d+$` word_id

### 5. Overlay Resolution
`edit_delete_overlay` resolves 1-based index or overlay_id from `state.ir.overlays`

### 6. Caption Position Mapping
- `top`: 520
- `middle`: 1080
- `bottom`: 1600

### 7. E2-11 Integration
`edit_auto_edit` accepts `style: "clean"|"standard"|"bold"` parameter (free up to 3 restyles)

## Test Results

### Node Test Harness (`tests/agent_editing.test.js`)
✅ 18/18 tests passed

Tests verify:
- EDIT_ACTION_SCHEMAS contains all 14 editing tools
- toolsForStep("editing") returns global + editing tools
- edit_build_raw calls run("build_raw")
- edit_auto_edit passes style parameter
- edit_scene_visual toggles face/broll/reset
- edit_trim applies start_ms/end_ms adjustments
- edit_music and edit_sfx toggle on/off
- edit_fix_caption resolves word to word_id
- edit_caption_position maps to correct Y values
- edit_overlay_delete/resolves index/overlay_id
- edit_overlays toggles overlays_enabled
- edit_post_copy generates metadata
- edit_share_link fetches share link
- edit_try_another_take costs 2 credits
- edit_render uses dynamic cost from state.render_price

### Python Backend Tests (`tests/test_agent_f11.py`)
✅ 9 test cases implemented (pytest ready)

Tests verify:
- toolsForStep('editing') returns correct tools (global + 14 editing)
- edit_auto_edit style parameter is free (E2-11)
- edit_try_another_take charges 2 credits
- edit_render uses dynamic cost from state.render_price
- edit_overlay_delete creates AgentAction record with audit
- edit_scene_visual toggles face on/off
- edit_caption_position maps to correct Y values
- edit_music and edit_sfx toggle correctly
- edit_fix_caption corrects caption words
- edit_post_copy generates metadata
- edit_share_link fetches share link

### Linting Results
✅ All clean

**Node --check:**
- `app/static/agent.js` - clean
- `app/static/actions.js` - clean
- `app/static/editing.js` - clean

**Ruff check:**
- `tests/test_agent_f11.py` - All checks passed!

## Files Modified

### app/static/actions.js
Added 14 editing tool registrations after `catalog.lock`:
```javascript
register('edit_build_raw', ...)      // Free
register('edit_auto_edit', ...)      // Free
register('edit_scene_visual', ...)   // Free
register('edit_trim', ...)           // Free
register('edit_music', ...)          // Free
register('edit_sfx', ...)            // Free
register('edit_fix_caption', ...)    // Free
register('edit_caption_position', ...) // Free
register('edit_overlay_delete', ...) // Free
register('edit_overlays', ...)       // Free
register('edit_post_copy', ...)      // Free
register('edit_share_link', ...)     // Free
register('edit_try_another_take', ...) // Paid (2 credits)
register('edit_render', ...)         // Paid (dynamic cost)
```

### app/static/editing.js
Extended `EDIT_ACTIONS` registry:
- Updated `fix_caption` to resolve word → word_id from `state.captions_words`
- Updated `dress_all` to accept `style` parameter (clean/standard/bold)
- Added `delete_overlay` action - resolves `n` (1-based) or `overlay_id` string
- Added `overlays_enabled` action - toggles overlays on/off
- Added `loadEditingState` public API for dynamic cost resolution
- Public API: `window.BrandStudioEditing = { show, onHide, run, EDIT_ACTIONS, hasFinalRender, loadEditingState }`

### app/static/agent.js
Added `EDIT_ACTION_SCHEMAS` constant with 14 tool definitions:
```javascript
const EDIT_ACTION_SCHEMAS = [
  { name: 'edit_build_raw', ... },
  { name: 'edit_auto_edit', ... },
  // ... 12 more tools
];

export const BrandStudioAgent = {
  ...
  EDIT_ACTION_SCHEMAS,
  toolsForStep(step) { ... }
};
```

## Evidence Files

1. `docs/specs/evidence/F-11/node_editing_tests.txt` - Node test output
2. `docs/specs/evidence/F-11/ruff_check.txt` - Linting results

## Integration Points

1. **Existing F-07 to F-10 tools preserved** - Verified no overwrites
2. **Edit-Scene-Visual** toggles face/broll via `toggle_face` + `reset_face` in `editing.js`
3. **Edit-Render** fetches `state.render_price` via `window.BrandStudioEditing.loadEditingState`
4. **Audit trail** - `X-Agent-Action-Id` header recorded in `agent_actions` table for all voice actions

## Product Rules Compliance

✅ **English UI** - All voice response strings are English
✅ **Same function as the button** - All voice tools call the same `window.BrandStudioEditing.run` functions as UI buttons via `EDIT_ACTIONS`
✅ **Credits** - No price changes; only on success paths defined
✅ **Contract order** - No render contract changes needed (UI changes only)
