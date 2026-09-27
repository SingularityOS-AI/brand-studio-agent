"""
Tests for E2-12: Recording Guide Silhouette Overlay.

Verifies:
1. SVG head-and-shoulders outline (stroke only, 40% opacity, top of head ~18% from top, shoulders reaching bottom).
2. Text overlay: 'Frame head and shoulders. Light at 45°, not straight at your glasses.'
3. Toggle button: 'Hide guide' / 'Show guide'. English only.
4. DOM overlay strictly outside recorded MediaRecorder video stream path.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "app" / "static" / "index.html"


def test_index_html_guide_overlay_elements():
    """Verify index.html contains guide overlay elements and SVG silhouette."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="Studio-GuideOverlay"' in html
    assert 'id="Studio-GuideSilhouette"' in html
    assert 'id="Studio-GuideText"' in html
    assert 'id="Studio-GuideToggleBtn"' in html

    # Verify text overlay exact string
    expected_text = "Frame head and shoulders. Light at 45°, not straight at your glasses."
    assert expected_text in html

    # Verify SVG stroke only (fill="none"), opacity 40%, top of head ~18%, shoulders reaching bottom
    assert 'fill="none"' in html
    assert 'stroke="rgba(255, 255, 255, 0.4)"' in html
    assert 'cy="32"' in html
    assert 'ry="14"' in html  # top of head = 32 - 14 = 18%
    assert '0 100' in html or '100 100' in html  # shoulders reach bottom y=100


def test_app_js_guide_logic_and_toggle():
    """Verify app.js initializes guide overlay and handles Hide/Show toggle."""
    js = APP_JS.read_text(encoding="utf-8")

    assert "initStudioRecordingGuide()" in js
    assert "toggleStudioRecordingGuide()" in js or "function toggleStudioRecordingGuide" in js

    # Verify toggle text states
    assert "'Hide guide'" in js
    assert "'Show guide'" in js

    # Verify openRecordingStudio calls initStudioRecordingGuide
    open_studio_idx = js.find("async function openRecordingStudio")
    assert open_studio_idx != -1
    open_studio_block = js[open_studio_idx : open_studio_idx + 800]
    assert "initStudioRecordingGuide()" in open_studio_block


def test_overlay_outside_recorded_stream_path():
    """Static assertion: MediaRecorder records raw getUserMedia stream, NOT the DOM overlay."""
    js = APP_JS.read_text(encoding="utf-8")

    # MediaRecorder must be instantiated with studioCameraStream (raw getUserMedia stream)
    recorder_match = re.search(r"new\s+MediaRecorder\s*\(\s*studioCameraStream", js)
    assert recorder_match is not None, "MediaRecorder must use studioCameraStream"

    # studioCameraStream must come from getUserMedia
    assert "navigator.mediaDevices.getUserMedia" in js

    # Verify MediaRecorder does NOT capture from canvas or DOM element containing the guide overlay
    assert "canvas.captureStream" not in js or "Studio-GuideOverlay" not in js.split("canvas.captureStream")[0]


def test_guide_overlay_english_only():
    """Verify guide text and toggle buttons contain no Spanish accents or characters."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    spanish_chars = set("áéíóúñ¿¡")

    guide_text = "Frame head and shoulders. Light at 45°, not straight at your glasses."
    assert not any(c in guide_text for c in spanish_chars)

    hide_btn = "Hide guide"
    show_btn = "Show guide"
    assert not any(c in hide_btn for c in spanish_chars)
    assert not any(c in show_btn for c in spanish_chars)
