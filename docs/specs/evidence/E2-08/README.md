# E2-08 — Editing UX: 3 steps, English, Auto-edit, loading screen

## Evidence

### 1. Pytest Output: tests/test_editing_e2_08_ux.py

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.0 -- C:\Python312_Neural\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\gabri\Desktop\SINGULARITYOS\_PROYECTOS_SUELTOS_SIN_CLASIFICAR\hackaton lablab assemly IA voice agent\brand-studio-agent
configfile: pytest.ini
plugins: anyio-4.12.1, asyncio-1.4.0, mock-3.15.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_fixture_loop_scope=None

collected 15 items

tests/test_editing_e2_08_ux.py::TestEditingE208Static::test_no_spanish_accents_or_characters PASSED [  6%]
tests/test_editing_e2_08_ux.py::TestEditingE208Static::test_no_vestir_or_dress_literal PASSED [ 13%]
tests/test_editing_e2_08_ux.py::TestEditingE208Static::test_english_labels_exist PASSED [ 20%]
tests/test_editing_e2_08_ux.py::TestEditingE208Static::test_edit_action_labels_english PASSED [ 26%]
tests/test_editing_e2_08_ux.py::TestEditingE208Static::test_node_check_editing_js_valid PASSED [ 33%]
tests/test_editing_e2_08_ux.py::TestEditingE208NodeDom::test_stepper_renders_three_steps PASSED [ 40%]
tests/test_editing_e2_08_ux.py::TestEditingE208NodeDom::test_dress_action_labels_english PASSED [ 46%]
tests/test_editing_e2_08_ux.py::TestEditingE208NodeDom::test_render_price_label_english PASSED [ 53%]
tests/test_editing_e2_08_ux.py::TestEditingE208NodeDom::test_loading_indicator_integration PASSED [ 60%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_step_1_is_cut PASSED [ 66%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_step_2_is_auto_edit PASSED [ 73%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_step_3_is_export PASSED [ 80%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_dress_status_labels_english PASSED [ 86%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_redress_label_english PASSED [ 93%]
tests/test_editing_e2_08_ux.py::TestEditingE208Requirements::test_no_spanish_in_scene_buttons PASSED [100%]

============================= 15 passed in 0.55s =============================
```

### 2. Node.js Syntax Check: app/static/editing.js

```
(no output - clean exit)
```

### 3. Ruff Check: tests/test_editing_e2_08_ux.py

```
All checks passed!
```

### 4. Existing Tests Compatibility: tests/test_editing_p82c_editing_js.py

All 5 tests pass, including the 13-action contract validation.

```
tests/test_editing_p82c_editing_js.py::test_node_check_editing_js PASSED
tests/test_editing_p82c_editing_js.py::test_editing_js_static_assertions PASSED
tests/test_editing_p82c_editing_js.py::test_editing_js_router_ops_contract PASSED
tests/test_editing_p82c_editing_js.py::test_editing_js_router_endpoints_contract PASSED
tests/test_editing_p82c_editing_js.py::test_node_load_and_expose_edit_actions PASSED
```

## Summary of Changes

### app/static/editing.js

1. **Label renames:**
   - `Vestir todo · free` → `Auto-edit · free`
   - `Your cut changed — dress again · free` → `Your cut changed — auto-edit again · free`
   - `Otra versión · 2 credits` → `Try another take on this scene · 2 credits`
   - `Dressed ✓` → `Auto-edited ✓`

2. **3-step Stepper:** Added visual stepper in `renderEditingContent()`:
   - Step 1: **Cut** (active when raw video is not fresh)
   - Step 2: **Auto-edit** (active when raw is done but dressing is not fresh)
   - Step 3: **Export** (active when dressing is fresh)

3. **Loading screen:** Added `Doc-LoadingIndicator` show/hide in `showEditingView()`:
   - Shows `.doc-loading-content` + `.doc-loading-spinner` with text `Loading your edit…`
   - Hidden in `finally` block after `loadEditingState()` completes

### tests/test_editing_e2_08_ux.py

New test file covering:
- Static assertions: no Spanish characters, no "Vestir" in visible strings
- DOM assertions: stepper HTML structure, loading indicator integration
- Contract assertions: 13 EDIT_ACTIONS preserved, render_price usage
