"""
Tests for PIEZA 47 — Rebote del QA de la Pieza 46 (+ 2 hallazgos del QA en producción).

Static contracts test suite (no network, no browser):
1. Verifies that Brand Soul functions (buildMaskForValue, humanizeBrainField, BRAIN_FIELD_LABELS)
   are real executable JavaScript code in app.js and not swallowed by an unclosed block comment.
2. Verifies that there are no unclosed /** or /* block comments in app.js.
3. Verifies that script duration displayed in frontend uses estimated duration from scene end_s.
4. Verifies that _build_generation_prompt contains the B-roll mixing rules:
   (>=2 non-a_roll scenes, <=1 ai_video, hook/close_cta a_roll, stock query filmable in English).
5. Verifies responsive CSS contract in index.html for stacked layout (<= 820px).
"""
import re
from pathlib import Path

from app.catalog.ideas import CatalogIdea
from app.scripting.scripts import _build_generation_prompt

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML_PATH = REPO_ROOT / "app" / "static" / "index.html"


def _extract_media_query_body(html: str, query: str) -> str:
    start = html.find(query)
    if start == -1:
        return ""
    brace_start = html.find("{", start)
    if brace_start == -1:
        return ""
    depth = 1
    pos = brace_start + 1
    while pos < len(html) and depth > 0:
        if html[pos] == "{":
            depth += 1
        elif html[pos] == "}":
            depth -= 1
        pos += 1
    return html[brace_start + 1 : pos - 1]


def test_brand_soul_symbols_not_inside_block_comment():
    """
    Item 1 & 5: Ensure buildMaskForValue, humanizeBrainField, and BRAIN_FIELD_LABELS
    are active code, not trapped inside any /* ... */ block comment.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # Strip out all block comments /* ... */
    stripped = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    assert "function buildMaskForValue" in stripped, (
        "buildMaskForValue function is missing or trapped inside a block comment!"
    )
    assert "function humanizeBrainField" in stripped, (
        "humanizeBrainField function is missing or trapped inside a block comment!"
    )
    assert "const BRAIN_FIELD_LABELS" in stripped, (
        "BRAIN_FIELD_LABELS object is missing or trapped inside a block comment!"
    )


def test_no_unclosed_block_comments_in_app_js():
    """
    Item 1 & 5: Ensure there are no unclosed /** or /* comments in app.js.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # Verify that every /* is matched by a */
    in_comment = False
    comment_start_line = 0

    lines = content.split("\n")
    for line_idx, line in enumerate(lines, 1):
        col = 0
        while col < len(line):
            if not in_comment:
                found = line.find("/*", col)
                if found != -1:
                    in_comment = True
                    comment_start_line = line_idx
                    col = found + 2
                else:
                    break
            else:
                found = line.find("*/", col)
                if found != -1:
                    in_comment = False
                    col = found + 2
                else:
                    break

    assert not in_comment, f"Unclosed block comment starting at line {comment_start_line}"

    # Also check that all /** have a matching */
    doc_blocks = re.findall(r"/\*\*.*?(?:\*/|$)", content, flags=re.DOTALL)
    for block in doc_blocks:
        assert block.endswith("*/"), f"Found unclosed docblock: {block[:50]}..."


def test_estimated_duration_contract_in_app_js():
    """
    Item 2: Script duration shown to founder must be estimated duration (end_s of last scene),
    not target_seconds declared by the LLM.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    # Helper function exists
    assert "function getEstimatedDurationText" in stripped

    # renderAudiovisualView uses getEstimatedDurationText
    assert "durationText = getEstimatedDurationText(currentScriptData)" in stripped

    # Script metadata in renderScriptView uses getEstimatedDurationText
    assert "${getEstimatedDurationText(currentScriptData)}" in stripped

    # updateScriptMetadata updates scriptDuration textContent with getEstimatedDurationText
    assert "if (scriptDuration) scriptDuration.textContent = getEstimatedDurationText(currentScriptData);" in stripped


def test_generation_prompt_contains_b_roll_mix_rules():
    """
    Item 3 & 5: Ensure _build_generation_prompt contains the B-roll mixing rules:
    - >= 2 scenes non-a_roll (B-roll, stock preferred with filmable English query)
    - <= 1 scene ai_video (most expensive asset)
    - hook and close_cta almost always a_roll (founder on camera)
    - scenes with B-roll still have spoken_text
    """
    idea = CatalogIdea(
        id="idea_test_broll",
        master_category="posicionamiento_narrativa",
        subcategory="Tesis contraria",
        title="Why your B2B ICP definition is holding you back",
        demand_signal="Demand signal with sufficient character count for validation requirements",
        status="approved",
    )
    prompt = _build_generation_prompt(
        brand_context="Brand context here",
        idea=idea,
        interview_transcript="Founder speaks about market positioning.",
        source_mode="brand_brain",
        script_kind="opinion",
    )

    # 1. B-roll requirement (>= 2 scenes non a_roll / B-roll)
    assert "≥2" in prompt or "At least 2" in prompt or "at least 2" in prompt
    assert "B-roll" in prompt

    # 2. AI video constraint (<= 1 scene ai_video)
    assert "≤1" in prompt or "Maximum 1" in prompt or "maximum 1" in prompt
    assert "ai_video" in prompt

    # 3. Founder takes (hook and close_cta almost always a_roll)
    assert "hook" in prompt and "close_cta" in prompt
    assert "a_roll" in prompt

    # 4. Filmable stock query example
    assert "doctor video call tablet clinic" in prompt

    # 5. Spoken text instruction over B-roll
    assert "spoken_text" in prompt


def test_responsive_layout_css_contract():
    """
    Item 4: In stacked layout (<= 820px), main.doc must not be crushed into a 20vh slit
    with its own tiny scrollbar. It must occupy natural height (min-height: 70vh) and visible overflow.
    """
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    media_css = _extract_media_query_body(html, "@media(max-width:820px)")
    assert media_css, "Media query @media(max-width:820px) not found in index.html"

    # html/body must allow vertical scrolling (not locked with overflow-y: hidden)
    assert "overflow-y: auto" in media_css

    # .doc or main.doc must have min-height: 70vh and overflow-y: visible
    assert "min-height: 70vh" in media_css
    assert "overflow-y: visible" in media_css


def test_brand_soul_door_and_action_bar_contract():
    """
    PIEZA 49: Contract tests for Brand Soul Door & Action Bar, Audiovisual Carousel, and Doc Loading.
    1. Verifies that BrandSoul-Overlay exists in index.html.
    2. Verifies that openBrandSoulViewer exists in app.js and opens brandSoulOverlay without charging credits.
    3. Verifies that the Brand Soul action bar (renderBrandSoulActionBar / BrandSoul-ActionBar-Container)
       renders the primary view button '📖 View your Brand Soul' (BrandSoul-ViewBtn) and clickable notice
       wired to openBrandSoulViewer.
    4. Verifies silent check of GET /api/soul (checkBrandSoulStatus) on view load.
    5. Verifies timeline strip has ‹ › navigation buttons and smooth centering scrollIntoView.
    6. Verifies Doc-LoadingIndicator exists in index.html and app.js manages showDocLoading/hideDocLoading.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"

    js_content = APP_JS_PATH.read_text(encoding="utf-8")
    stripped_js = re.sub(r"/\*.*?\*/", "", js_content, flags=re.DOTALL)
    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Overlay exists in index.html
    assert 'id="BrandSoul-Overlay"' in html_content
    assert 'id="BrandSoul-ActionBar-Container"' in html_content

    # 2. openBrandSoulViewer exists and opens overlay
    assert "function openBrandSoulViewer" in stripped_js
    assert "brandSoulOverlay.style.display = 'flex'" in stripped_js

    # 3. Primary view button & clickable unlock notice
    assert "BrandSoul-ViewBtn" in stripped_js
    assert "📖 View your Brand Soul" in stripped_js
    assert "BrandSoul-ActionRegenerateBtn" in stripped_js
    assert "BrandSoul-GenerateActionBtn" in stripped_js
    assert "BrandSoul-UnlockNotice" in stripped_js
    assert "openBrandSoulViewer" in stripped_js

    # 4. Silent check of GET /api/soul
    assert "function checkBrandSoulStatus" in stripped_js
    assert "brandSoulExists" in stripped_js

    # 5. Timeline carousel & smooth centering scroll
    assert "AV-Timeline-PrevBtn" in stripped_js
    assert "AV-Timeline-NextBtn" in stripped_js
    assert "scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })" in stripped_js

    # 6. Doc loading indicator
    assert 'id="Doc-LoadingIndicator"' in html_content
    assert "function showDocLoading" in stripped_js
    assert "function hideDocLoading" in stripped_js


def test_recording_studio_scene_header_and_camera_retry_contract():
    """
    PIEZA 51B: Rebote corto del QA del estudio de grabación.
    1. Header displays take position and scene number with 'Take ' prefix (e.g. 'Take 1 of 1 · Scene 1 · Hook').
    2. Button 'Try camera again' exists in index.html to request camera access again.
    3. Record button falls back to 'Camera needed' when stream is not available.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"

    js_content = APP_JS_PATH.read_text(encoding="utf-8")
    stripped_js = re.sub(r"/\*.*?\*/", "", js_content, flags=re.DOTALL)
    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. 'Take ' appears in studio scene info header
    assert "Take " in html_content
    assert "Take ${" in stripped_js

    # 2. Button 'Try camera again' exists
    assert "Try camera again" in html_content
    assert "Studio-RetryCameraBtn" in html_content
    assert "Studio-RetryCameraBtn" in stripped_js
    assert "Camera needed" in html_content
    assert "Camera needed" in stripped_js


def test_hyperframes_player_and_motion_graphic_contract():
    """
    PIEZA 54B: Rebote del QA de la P54: player de HyperFrames y preview de motion graphics.
    1. index.html script tag src contains /+esm.
    2. app.js uses URL.createObjectURL for motion graphics player.
    3. app.js uses revokeObjectURL to clean up blob URLs.
    4. app.js renders hyperframes-player without src and with data-motion-scene.
    5. app.js escapes template name with escapeHtml.
    """
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"

    js_content = APP_JS_PATH.read_text(encoding="utf-8")
    stripped_js = re.sub(r"/\*.*?\*/", "", js_content, flags=re.DOTALL)
    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Script tag in index.html contains /+esm
    assert "/+esm" in html_content
    assert 'src="https://cdn.jsdelivr.net/npm/@hyperframes/player@0/+esm"' in html_content

    # 2. app.js uses URL.createObjectURL for motion graphics player
    assert "URL.createObjectURL" in stripped_js
    assert "player.setAttribute('src', blobUrl)" in stripped_js

    # 3. app.js uses revokeObjectURL
    assert "revokeObjectURL" in stripped_js

    # 4. hyperframes-player rendered without src and with data-motion-scene
    assert "data-motion-scene" in stripped_js

    # 5. template name escaped
    assert "${escapeHtml(template)}" in stripped_js





def test_every_awaited_fetch_helper_is_defined():
    """A call to an undefined fetch helper (e.g. 'fetchWithAuth') ships as a
    ReferenceError that node --check cannot see: it broke the recording upload
    and the job list in production (Pieza 51/52). Every `await <name>Fetch(`
    or `await fetch<Name>(` helper used in app.js must be defined in app.js."""
    js = APP_JS_PATH.read_text(encoding="utf-8")
    called = set(re.findall(r"await\s+([A-Za-z_]\w*[Ff]etch\w*)\s*\(", js))
    called |= set(re.findall(r"await\s+(fetch[A-Z]\w*)\s*\(", js))
    called.discard("fetch")
    missing = sorted(
        name for name in called
        if not re.search(rf"(async\s+)?function\s+{name}\s*\(|(const|let|var)\s+{name}\s*=", js)
    )
    assert missing == [], f"Fetch helpers called but never defined in app.js: {missing}"
