"""
Static contract tests for PIEZA 62 — Confirmar y bloquear el guion en UN solo paso.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


def test_pieza62_static_contracts_in_app_js():
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # 1. app.js contiene 'Confirm & Lock script' y ya no contiene 'Confirm & Move to Reviewed'
    assert "Confirm & Lock script" in content, "app.js missing 'Confirm & Lock script'"
    assert "Confirm & Move to Reviewed" not in content, "app.js still contains 'Confirm & Move to Reviewed'"

    # 2. app.js contiene 'Fix these before locking:'
    assert "Fix these before locking:" in content, "app.js missing 'Fix these before locking:'"

    # 3. Dentro de handleScriptConfirm aparecen las rutas del PATCH (/api/script/${) y del lock (/lock) — o la llamada a la función común que hace el lock
    confirm_pos = content.find("async function handleScriptConfirm")
    assert confirm_pos != -1, "app.js missing 'async function handleScriptConfirm'"

    # Find the bounds of handleScriptConfirm function
    confirm_end = content.find("async function ", confirm_pos + 20)
    if confirm_end == -1:
        confirm_end = content.find("function ", confirm_pos + 20)
    if confirm_end == -1:
        confirm_end = confirm_pos + 2000

    confirm_func_text = content[confirm_pos:confirm_end]
    assert "/api/script/" in confirm_func_text, "handleScriptConfirm missing '/api/script/'"
    assert "/lock" in confirm_func_text or "performLockScript" in confirm_func_text, (
        "handleScriptConfirm missing '/lock' or performLockScript"
    )

    # 4. Use "Confirm & Lock script" below aparece en app.js
    assert 'Use "Confirm & Lock script" below' in content, (
        'app.js missing \'Use "Confirm & Lock script" below\''
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
