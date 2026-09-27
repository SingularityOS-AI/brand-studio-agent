# E2-07 Evidence

## No-collision overlay layout in the IR

### Implementation Summary

This piece implements overlay-caption collision detection and resolution in the RenderIR.

### Changes Made

1. **render_service/manifest.py**:
   - Added `hide_captions: bool = False` field to `OverlayCue` model

2. **app/editing/ir.py**:
   - Added zone definitions (TOP, MIDDLE, BOTTOM)
   - Added collision detection functions:
     - `_calculate_caption_box()` - computes caption box from caption_y
     - `_boxes_intersect()` - 2D box intersection test
     - `_get_overlay_zone()` - determines zone from overlay position
     - `_move_overlay_to_zone()` - moves overlay to new zone
     - `_resolve_overlay_collisions()` - main collision resolution algorithm
   - Modified `build_ir_stage2()` to apply collision resolution

3. **tests/test_editing_e2_07_collision.py** (new file):
   - 206 tests covering unit tests and property testing

### Test Results

```
python -m pytest tests/test_editing_e2_07_collision.py -v
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
collected 206 items

tests/test_editing_e2_07_collision.py::test_boxes_intersect_overlapping PASSED
tests/test_editing_e2_07_collision.py::test_boxes_intersect_separate PASSED
tests/test_editing_e2_07_collision.py::test_calculate_caption_box_no_active_event PASSED
tests/test_editing_e2_07_collision.py::test_calculate_caption_box_single_line PASSED
tests/test_editing_e2_07_collision.py::test_get_overlay_zone PASSED
tests/test_editing_e2_07_collision.py::test_overlay_in_free_zone_no_collision PASSED
tests/test_editing_e2_07_collision.py::test_property_no_overlay_intersects_caption[0-199] PASSED (200 tests)

======================= 206 passed, 3 warnings in 0.72s =======================
```

### Code Quality

```
ruff check app/editing/ir.py render_service/manifest.py tests/test_editing_e2_07_collision.py
All checks passed!
```

### Property Test

200 random IRs tested - **all passed**, verifying:
- No overlay box intersects a caption box at the same time
- Collision detection works across all zones
- Overlays are repositioned or hide_captions is set as needed
