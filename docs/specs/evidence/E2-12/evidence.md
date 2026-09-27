# E2-12 Evidence: Recording Guide Silhouette Overlay

## Overview
Implementation of piece **E2-12 (Recording Guide Silhouette Overlay)** for the Brand Studio Agent recording studio. This overlay guides the user during A-roll recording to ensure tight head-and-shoulders framing and proper lighting at 45° to avoid glasses glare.

## Requirements Verification

| Requirement | Implementation Detail | Status |
|-------------|-----------------------|--------|
| **1. SVG Silhouette** | `<svg id="Studio-GuideSilhouette">` outline overlay: stroke only (`fill="none"`), 40% opacity (`rgba(255, 255, 255, 0.4)`), top of head at ~18% (`cy="32" ry="14"` -> 18% from top), shoulders reaching bottom (`y=100`). | ✅ PASSED |
| **2. Text Overlay** | `'Frame head and shoulders. Light at 45°, not straight at your glasses.'` | ✅ PASSED |
| **3. Toggle Button** | `'Hide guide'` / `'Show guide'` toggle button (`#Studio-GuideToggleBtn`) bound to `toggleStudioRecordingGuide()`. English only. | ✅ PASSED |
| **4. Stream Isolation** | `MediaRecorder` receives raw webcam `studioCameraStream` (`getUserMedia`), which does NOT include DOM elements or overlays rendered in the browser viewport. | ✅ PASSED |

## Test Suite Results

Test file: `tests/test_recording_e2_12_guide.py`

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\gabri\Desktop\SINGULARITYOS\_PROYECTOS_SUELTOS_SIN_CLASIFICAR\hackaton lablab assemly IA voice agent\brand-studio-agent
configfile: pytest.ini
collected 4 items

tests/test_recording_e2_12_guide.py::test_index_html_guide_overlay_elements PASSED [ 25%]
tests/test_recording_e2_12_guide.py::test_app_js_guide_logic_and_toggle PASSED [ 50%]
tests/test_recording_e2_12_guide.py::test_overlay_outside_recorded_stream_path PASSED [ 75%]
tests/test_recording_e2_12_guide.py::test_guide_overlay_english_only PASSED [100%]

============================== 4 passed in 3.95s ==============================
```

## Files Modified
- `app/static/index.html`: Added `#Studio-GuideOverlay`, SVG silhouette, guide text, `#Studio-GuideToggleBtn`, and CSS rules.
- `app/static/app.js`: Added `initStudioRecordingGuide()` and `toggleStudioRecordingGuide()`, wired into `openRecordingStudio()`.
- `tests/test_recording_e2_12_guide.py`: New static and architecture assertion tests for E2-12.
- `docs/specs/evidence/E2-12/evidence.md`: Evidence documentation.
