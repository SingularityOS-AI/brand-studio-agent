# File Attribution: F-11 vs E2-13

Current branch: `feat/E2-13-animated-overlays` (MIXED - contains both E2-13 and F-11 changes)

## F-11 (Editing Voice Tools) - Authorized Files

### Direct F-11 Files (NEW):
1. ✅ `tests/agent_editing.test.js` - NEW (Node harness tests for F-11)
2. ✅ `tests/test_agent_f11.py` - NEW (Python backend tests for F-11)
3. ✅ `docs/specs/evidence/F-11/` - NEW (Evidence directory)

### Modified for F-11 (AUTHORIZED):
1. ✅ `app/static/agent.js` - Added `EDIT_ACTION_SCHEMAS` constant (14 tools)
2. ✅ `app/static/actions.js` - Added 14 editing tool registrations
3. ✅ `app/static/editing.js` - Extended `EDIT_ACTIONS` registry (delete_overlay, overlays_enabled, loadEditingState)

## E2-13 (Animated Overlays) - Authorized Files (different piece)

### Modified for E2-13 (NOT F-11):
1. ⚠️ `app/editing/catalog/catalog_v1.json` - Animated overlay catalog (E2-13)
2. ⚠️ `app/editing/dressing.py` - DDR logic for animated overlays (E2-13)
3. ⚠️ `app/editing/ir.py` - Overlay model changes (E2-13)
4. ⚠️ `app/main.py` - New endpoints for animated overlays (E2-13)
5. ⚠️ `app/static/editing_preview.js` - Overlay preview logic (E2-13)
6. ⚠️ `render_service/ffmpeg_dress.py` - Render overlay animations (E2-13)
7. ⚠️ `render_service/manifest.py` - IR serialization for overlays (E2-13)

### New for E2-13 (NOT F-11):
1. ⚠️ `render_service/overlay_templates/` - Overlay template files (E2-13)

### Evidence for E2-13 (NOT F-11):
1. ⚠️ `docs/reviews/` - Review artifacts (E2-13)
2. ⚠️ `docs/specs/E2/plan e.md` - E2-13 planning (E2-13)

## Recommendation for PR

For a clean F-11-only PR, we should:
1. Create branch `agent/F-11-editing-tools` from `main`
2. Cherry-pick only F-11 authroized changes:
   - `app/static/agent.js` (EDIT_ACTION_SCHEMAS addition)
   - `app/static/actions.js` (14 tool registrations)
   - `app/static/editing.js` (EDIT_ACTIONS extensions)
   - `tests/agent_editing.test.js` (new)
   - `tests/test_agent_f11.py` (new)

OR if this is an intentional combined branch for E2-13 + F-11, document both pieces in PR description.
