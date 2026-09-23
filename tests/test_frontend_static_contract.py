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
