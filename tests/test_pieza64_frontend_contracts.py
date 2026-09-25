"""
Static contract tests for PIEZA 64 — La confirmación de "Generate assets" solo suma lo que falta generar.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


def test_pieza64_static_contracts_in_app_js():
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    assert "credits_pending" in content, "app.js missing 'credits_pending'"
    assert "All assets ready" in content, "app.js missing 'All assets ready'"
    assert "written automatically when this scene is generated" in content, (
        "app.js missing 'written automatically when this scene is generated'"
    )
