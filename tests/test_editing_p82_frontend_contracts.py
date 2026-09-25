"""Static contract tests for Pieza 82 / 82B: Editing Studio Frontend Cableado."""
import re
import shutil
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_app_js_exposes_window_brand_studio():
    app_js_path = REPO_ROOT / "app" / "static" / "app.js"
    assert app_js_path.exists(), "app.js must exist"
    content = app_js_path.read_text(encoding="utf-8")
    assert "window.BrandStudio" in content, "app.js must expose window.BrandStudio"
    for key in [
        "authenticatedFetch",
        "showPaywall",
        "updateCreditsUI",
        "escapeHtml",
        "openRecordingStudio",
        "showAudiovisualView",
        "showBlockCView",
        "hideMainViews",
        "renderPipelineRail",
        "getCurrentScriptIdeaId",
    ]:
        assert key in content, f"window.BrandStudio must expose {key}"


def test_app_js_editing_riel_calls_show_editing():
    app_js_path = REPO_ROOT / "app" / "static" / "app.js"
    content = app_js_path.read_text(encoding="utf-8")
    assert "isAudiovisualComplete" in content, "app.js must define isAudiovisualComplete"
    assert "BrandStudioEditing.show" in content or "showEditingView" in content
    assert "showRailNotice('Editing — coming soon', null, null);" not in content
    assert re.search(r"id:\s*'editing'.*prevComplete:\s*scriptComplete", content), \
        "Editing step must have prevComplete: scriptComplete"
    assert "'Ready to edit'" in content


def test_app_js_hide_editing_view_calls():
    app_js_path = REPO_ROOT / "app" / "static" / "app.js"
    content = app_js_path.read_text(encoding="utf-8")

    funcs = ["showBlockAView", "showBlockBView", "showBlockCView", "showAudiovisualView"]
    for fn in funcs:
        start_idx = content.find(f"function {fn}")
        if start_idx == -1:
            start_idx = content.find(f"async function {fn}")
        assert start_idx != -1, f"Function {fn} must exist in app.js"
        fn_block = content[start_idx:start_idx + 400]
        assert "hideEditingView()" in fn_block, f"{fn} must call hideEditingView()"


def test_main_includes_editing_router():
    main_py_path = REPO_ROOT / "app" / "main.py"
    assert main_py_path.exists(), "main.py must exist"
    content = main_py_path.read_text(encoding="utf-8")
    assert "editing_router" in content, "main.py must reference editing_router"
    assert "app.include_router(editing_router)" in content


def test_index_html_has_editing_view():
    index_html_path = REPO_ROOT / "app" / "static" / "index.html"
    assert index_html_path.exists(), "index.html must exist"
    content = index_html_path.read_text(encoding="utf-8")
    assert 'id="Editing-View"' in content, "index.html must include #Editing-View"
    assert 'id="Editing-Guard"' in content, "index.html must include #Editing-Guard"
    assert 'id="Editing-Content"' in content, "index.html must include #Editing-Content"


def test_index_html_loads_editing_js_and_fonts():
    index_html_path = REPO_ROOT / "app" / "static" / "index.html"
    content = index_html_path.read_text(encoding="utf-8")
    assert 'src="/static/editing.js"' in content, "index.html must load editing.js"
    assert 'src="/static/editing_preview.js"' in content, "index.html must load editing_preview.js"
    
    pos_preview = content.find('src="/static/editing_preview.js"')
    pos_editing = content.find('src="/static/editing.js"')
    assert pos_preview != -1 and pos_editing != -1, "Both scripts must be included"
    assert pos_preview < pos_editing, "editing_preview.js must be loaded before editing.js"

    assert "gsap" not in content.lower(), "index.html must not load GSAP"

    fonts = ["Anton", "Bebas+Neue", "Inter", "Montserrat", "Poppins", "Roboto"]
    for font in fonts:
        assert font in content, f"index.html Google Fonts @import must include {font}"


def test_editing_js_defines_edit_actions():
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"
    assert editing_js_path.exists(), "editing.js must exist"
    content = editing_js_path.read_text(encoding="utf-8")
    assert "EDIT_ACTIONS" in content, "editing.js must define EDIT_ACTIONS"
    for action in [
        "toggle_face",
        "reset_face",
        "trim",
        "mute_music",
        "toggle_sfx",
        "fix_caption",
        "dress_all",
        "redress_scene",
        "build_raw",
        "render",
        "gen_metadata",
        "edit_metadata",
        "copy_share_link",
    ]:
        assert action in content, f"editing.js EDIT_ACTIONS must include {action}"


def test_editing_js_exposes_window():
    editing_js_path = REPO_ROOT / "app" / "static" / "editing.js"
    content = editing_js_path.read_text(encoding="utf-8")
    assert "window.BrandStudioEditing" in content, "editing.js must expose window.BrandStudioEditing"
    assert "run:" in content or "runEditAction" in content
    assert "show:" in content or "showEditingView" in content


def test_node_check_app_js():
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node is not available in PATH")
    app_js_path = REPO_ROOT / "app" / "static" / "app.js"
    result = subprocess.run([node_bin, "--check", str(app_js_path)], capture_output=True, text=True)
    assert result.returncode == 0, f"node --check app.js failed: {result.stderr}"
