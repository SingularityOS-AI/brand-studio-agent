"""
Static contract tests for PIEZA 61 — Guion: pantalla de carga, botón Lock que se entiende, y paso directo a Audiovisual.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"
INDEX_HTML_PATH = REPO_ROOT / "app" / "static" / "index.html"


def test_pieza61_static_contracts_in_index_html():
    assert INDEX_HTML_PATH.exists(), f"index.html not found at {INDEX_HTML_PATH}"
    content = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. index.html contains CSS rule with .btn:disabled and cursor:not-allowed
    assert ".btn:disabled" in content, "index.html missing '.btn:disabled' CSS rule"
    assert "cursor:not-allowed" in content, "index.html missing 'cursor:not-allowed' CSS property"


def test_pieza61_static_contracts_in_app_js():
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # 2. app.js contains 'Brandy is writing your script' and 'clearInterval(' inside generate handler window
    gen_pos = content.find("/api/script/generate?idea_id=")
    assert gen_pos != -1, "app.js missing /api/script/generate route"

    handler_start = content.rfind("scriptGenerateBtn.addEventListener", 0, gen_pos)
    if handler_start == -1:
        handler_start = max(0, gen_pos - 1000)

    # find the closing }); of the addEventListener block (after gen_pos)
    close_pos = content.find("  // PIEZA 36 (bug 2)", gen_pos)
    if close_pos == -1:
        close_pos = content.find("});", gen_pos + 500)

    window_text = content[handler_start:close_pos]
    assert "Brandy is writing your script" in window_text, (
        "generate handler in app.js does not contain 'Brandy is writing your script'"
    )
    assert "clearInterval(" in window_text, (
        "generate handler in app.js does not contain 'clearInterval('"
    )

    # 3. app.js contains Script-LockHint, Step 1 of 2, and Step 2 of 2
    assert "Script-LockHint" in content, "app.js missing 'Script-LockHint'"
    assert "Step 1 of 2" in content, "app.js missing 'Step 1 of 2'"
    assert "Step 2 of 2" in content, "app.js missing 'Step 2 of 2'"

    # 4. app.js contains Script-OpenAudiovisualBtn and in ~40 following lines showAudiovisualView()
    btn_pos = content.rfind("Script-OpenAudiovisualBtn")
    assert btn_pos != -1, "app.js missing 'Script-OpenAudiovisualBtn'"

    snippet_lines = content[btn_pos:].split("\n")[:40]
    snippet_text = "\n".join(snippet_lines)
    assert "showAudiovisualView()" in snippet_text, (
        "showAudiovisualView() not found within ~40 lines of Script-OpenAudiovisualBtn"
    )


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
