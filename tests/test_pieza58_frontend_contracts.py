"""
Static contract tests for PIEZA 58 — Selector de tipo por escena, barra de progreso y soundtrack.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


def test_pieza58_static_contracts_in_app_js():
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # 1. Contains /asset_type route and PATCH method
    assert "/asset_type" in content, "app.js missing /asset_type route"
    assert "PATCH" in content, "app.js missing PATCH method for asset_type"

    # 2. Reads credits_by_type
    assert "credits_by_type" in content, "app.js does not reference credits_by_type"

    # 3. Does NOT contain hardcoded prices '150 credits' or '15 credits' inside renderSelectedSceneDetail template
    detail_func_match = re.search(
        r"function renderSelectedSceneDetail\s*\([^)]*\)\s*\{(.*?)\n  function ", content, flags=re.DOTALL
    )
    assert detail_func_match, "renderSelectedSceneDetail function not found in app.js"
    detail_func_body = detail_func_match.group(1)
    assert "150 credits" not in detail_func_body, "renderSelectedSceneDetail contains hardcoded '150 credits'"
    assert "15 credits" not in detail_func_body, "renderSelectedSceneDetail contains hardcoded '15 credits'"

    # 4. Contains "Suggested by your script"
    assert "Suggested by your script" in content, "app.js missing 'Suggested by your script'"

    # 5. Contains "you can keep working"
    assert "you can keep working" in content, "app.js missing 'you can keep working'"

    # 6. Contains "Soundtrack"
    assert "Soundtrack" in content, "app.js missing 'Soundtrack'"

    # 7. updateCreditsUI uses Math.max for denominator to prevent stuck meter
    update_credits_match = re.search(
        r"function updateCreditsUI\s*\([^)]*\)\s*\{(.*?)\n  \}", content, flags=re.DOTALL
    )
    assert update_credits_match, "updateCreditsUI function definition not found in app.js"
    func_body = update_credits_match.group(1)
    assert "Math.max(" in func_body, "updateCreditsUI does not use Math.max to compute denominator"

    # 8. All authenticated calls use authenticatedFetch, NO fetchWithAuth
    assert "fetchWithAuth" not in content, "Found forbidden fetchWithAuth function/call in app.js!"

    # 9. No hardcoded fallback object in app.js (Pieza 57B/58B)
    assert "ai_image: 15, ai_video: 150" not in content, "Found hardcoded fallback 'ai_image: 15, ai_video: 150' in app.js"

    # 10. fetchAudiovisualEstimate is called at least 2 times outside definition
    fetch_calls = [m.start() for m in re.finditer(r"fetchAudiovisualEstimate\(", content)]
    def_match = re.search(r"function\s+fetchAudiovisualEstimate\(", content)
    def_pos = def_match.start() if def_match else -1
    calls_outside_def = [p for p in fetch_calls if p != def_pos and p != def_pos + len("function ")]
    assert len(calls_outside_def) >= 2, f"fetchAudiovisualEstimate called only {len(calls_outside_def)} times outside definition (expected >= 2)"

    # 11. No double escaping in textContent assignments
    assert "textContent = escapeHtml(" not in content, "Found double escape 'textContent = escapeHtml(' in app.js"


def test_no_unclosed_comments_in_app_js():
    content = APP_JS_PATH.read_text(encoding="utf-8")

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

    doc_blocks = re.findall(r"/\*\*.*?(?:\*/|$)", content, flags=re.DOTALL)
    for block in doc_blocks:
        assert block.endswith("*/"), f"Found unclosed docblock starting with: {block[:50]}..."


def test_render_audiovisual_view_no_hardcoded_prices_and_defines_credits_by_type():
    """
    Regression test: renderAudiovisualView() crashed with
    `ReferenceError: creditsByType is not defined` because the variable was
    only declared inside renderSelectedSceneDetail(), and the card fallback
    used invented hardcoded prices (150 / 15). Prices must come exclusively
    from currentAudiovisualEstimate.credits_by_type.
    """
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # (a) No hardcoded fallback prices for ai_video/ai_image anywhere in app.js
    assert "? 150 :" not in content, "Found forbidden hardcoded fallback price '? 150 :' in app.js"
    assert "'ai_video' ? 150" not in content, "Found forbidden hardcoded price tied to 'ai_video' ? 150"
    assert "ai_image: 15" not in content, "Found forbidden hardcoded price 'ai_image: 15' in app.js"

    # (b) Extract the body of renderAudiovisualView (up to the next top-level
    # `function ` declaration at the same 2-space indentation level).
    match = re.search(
        r"function renderAudiovisualView\([^)]*\)\s*\{(.*?)\n  function ",
        content,
        flags=re.DOTALL,
    )
    assert match, "renderAudiovisualView function not found in app.js"
    body = match.group(1)

    decl_match = re.search(r"const\s+creditsByType\b", body)
    assert decl_match, "renderAudiovisualView does not declare 'const creditsByType'"

    first_use_match = re.search(r"creditsByType\[", body)
    assert first_use_match, "renderAudiovisualView never uses creditsByType[...]"

    assert decl_match.start() < first_use_match.start(), (
        "creditsByType is used before it is declared inside renderAudiovisualView "
        f"(decl at {decl_match.start()}, first use at {first_use_match.start()})"
    )
