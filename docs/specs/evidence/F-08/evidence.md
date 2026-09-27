# Evidence for F-08 — Audiovisual Voice Tools

## Overview
Piece F-08 adds full voice tool support for the Audiovisual step in Brand Studio Agent, enabling Brandy to inspect scenes, set asset types, calculate estimates, generate all pending assets, regenerate individual assets with custom instructions, and open the recording studio.

## Implemented Tools & Registration
Registered in `app/static/actions.js` and `app/static/agent.js` (`AUDIOVISUAL_TOOL_SCHEMAS`):

1. **`av_read_scene {scene_n}`** (free)
   - Action ID: `av_read_scene` / `audiovisual.read_scene`
   - Handler: `BrandStudioAgent.avReadScene`
   - Returns scene text, asset type, and generation status.

2. **`av_set_scene_type {scene_n, type}`** (free)
   - Action ID: `av_set_scene_type` / `audiovisual.change_scene_type`
   - Sets asset type (`a_roll`, `stock`, `ai_video`, `motion_graphic`) and restates change.

3. **`av_estimate`** (free)
   - Action ID: `av_estimate` / `audiovisual.estimate`
   - Fetches estimate breakdown for pending assets.

4. **`av_generate_all`** (confirm, cost = estimate total)
   - Action ID: `av_generate_all` / `audiovisual.generate_all`
   - Requires confirmation. Confirmation restatement includes exact estimate total.
   - Long generation jobs return immediately with status `'queued'` and appear in Production Panel.

5. **`av_regenerate_asset {scene_n, instruction?}`** (confirm, per-unit cost)
   - Action ID: `av_regenerate_asset` / `audiovisual.regenerate_one`
   - Requires confirmation.
   - Accepts optional `instruction` parameter (e.g. "someone using a phone") passed to POST `/api/audiovisual/{idea_id}/scenes/{scene_n}/regenerate`.

6. **`av_open_recording {scene_n}`** (free)
   - Action ID: `av_open_recording` / `audiovisual.open_recording_studio`
   - Opens recording studio for scene.

## Verification Evidence
- Node test harness: `tests/agent_audiovisual.test.js` passed (100% clean exit).
- Pytest integration test: `tests/test_agent_f08.py` passed (5/5 tests passed).

```
ok - AUDIOVISUAL_TOOL_SCHEMAS contains all 6 tools
ok - toolsForStep("audiovisual") returns global + audiovisual tools
ok - av_read_scene action returns scene status and asset type
ok - av_read_scene action returns error for invalid scene number
ok - Action registry looks up av_read_scene action
ok - Action registry looks up av_set_scene_type action
ok - Action registry looks up av_estimate action
ok - Action registry looks up av_generate_all action with exact estimate total cost
ok - Action registry looks up av_regenerate_asset with per-unit cost
ok - Action registry looks up av_open_recording action
ok - av_regenerate_asset passes instruction parameter to run handler
ok - av_generate_all returns immediately with queued status

All F-08 audiovisual checks passed.
```
