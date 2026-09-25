"""
Static contract tests for PIEZA 60 — Soundtrack endpoint and frontend state contracts.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "app" / "static" / "app.js"


def test_pieza60_static_contracts_in_app_js():
    assert APP_JS_PATH.exists(), f"app.js not found at {APP_JS_PATH}"
    content = APP_JS_PATH.read_text(encoding="utf-8")

    # 1. Contains /soundtrack endpoint path
    assert "/soundtrack" in content, "app.js missing /soundtrack endpoint path"

    # 2. Contains 'not chosen yet'
    assert "not chosen yet" in content, "app.js missing 'not chosen yet'"

    # 3. Contains 'couldn't choose one'
    assert "couldn't choose one" in content, "app.js missing 'couldn't choose one'"

    # 4. ensureSoundtrackLoaded excludes failed music jobs and triggers job polling on retry/success
    ensure_fn = content.split("async function ensureSoundtrackLoaded")[1].split("function")[0]
    assert "'failed'" in ensure_fn or '"failed"' in ensure_fn, "ensureSoundtrackLoaded missing 'failed' status check"
    assert "pollAudiovisualJobs(" in ensure_fn, "ensureSoundtrackLoaded missing pollAudiovisualJobs call"
