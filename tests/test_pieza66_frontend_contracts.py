"""
Static contract test for PIEZA 66 frontend integration in app/static/app.js.
Verifies app.js calls /prepare endpoint and assigns result to currentScriptData.scenes.
"""
from pathlib import Path


def test_frontend_prepare_contract():
    app_js_path = Path("app/static/app.js")
    assert app_js_path.exists(), "app/static/app.js must exist"

    content = app_js_path.read_text(encoding="utf-8")

    assert "/prepare" in content, "app.js must contain endpoint call to /prepare"

    # Find position of /prepare
    idx = content.find("/prepare")
    assert idx != -1

    # Extract the snippet following the occurrence of /prepare
    snippet = content[idx : idx + 2000]
    assert "currentScriptData.scenes" in snippet, (
        "app.js must assign to currentScriptData.scenes in the ~40 lines following /prepare call"
    )
