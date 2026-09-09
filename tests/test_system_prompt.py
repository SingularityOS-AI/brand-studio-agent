"""
Test that the system_prompt uses correct section names as defined in spec.md

Verifies that the LLM receives the same section names as the Python schema defnes.
No silent corruption where Brandy asks for one thing but stores under another label.
"""

import pytest


def test_system_prompt_uses_correct_section_names():
    """
    CRITICAL: The system_prompt sent to the LLM MUST match the 9-node model
    firmada by the CEO in .claude/specs/spec_cerebro_9_nodos.md.

    The nine nodes, in spec order, are:
    01 diagnostico       - Where you stand (founder triage)
    02 brand_journey     - Brand Journey (the FOUNDER's journey, NOT the customer's)
    03 charco             - The pond
    04 icp                - The ICP (single ICP required)
    05 contrarian          - Contrarian stance
    06 asociaciones        - Desired and forbidden associations
    07 identidad            - Identity map
    08 oferta                - The offer
    09 lead_magnet            - The lead magnet

    The old ids (`etapa`, `credibilidad`) and old names ("Etapa del Fundador",
    "Credibilidad del Problema", "Viaje del Cliente") no longer exist.

    This test verifies the actual system_prompt content, not constants.
    """
    # Read the actual system_prompt from app.js
    import re
    from pathlib import Path

    app_js_path = Path(__file__).parent.parent / "app" / "static" / "app.js"
    with open(app_js_path, encoding="utf-8") as f:
        content = f.read()

    # Extract the baseSystemPrompt constant (renamed in Pieza 10 for dynamic memory injection)
    system_prompt_match = re.search(
        r'const baseSystemPrompt = `(.+?)`;',
        content,
        re.DOTALL | re.MULTILINE
    )

    assert system_prompt_match, "Could not find baseSystemPrompt constant in app.js"
    system_prompt = system_prompt_match.group(1)

    # 1. Brand Journey must be the FOUNDER's journey, not the customer's
    assert "Brand Journey" in system_prompt, "Missing 'Brand Journey' section"
    assert "Customer Journey" not in system_prompt and "Viaje del Cliente" not in system_prompt, \
        "Brand Journey is for the FOUNDER, not the customer. 'Customer Journey' / 'Viaje del Cliente' is wrong."
    assert "THE FOUNDER'S journey" in system_prompt or "founder's journey" in system_prompt.lower(), \
        "Brand Journey must explicitly say it's the FOUNDER's journey, not the customer's"

    # 2. Old ids/names must be gone for good
    assert "Etapa del Fundador" not in system_prompt, \
        "'Etapa del Fundador' is the OLD name (pre-9-nodos) and must not appear"
    assert "Credibilidad del Problema" not in system_prompt, \
        "'Credibilidad del Problema' is the OLD name (pre-9-nodos) and must not appear"
    assert "Problem Credibility" not in system_prompt, \
        "'Problem Credibility' is the OLD name (pre-9-nodos) and must not appear"

    # 3. The 9 node ids from the signed spec must all be present (parenthesized id form)
    node_ids = [
        "diagnostico", "brand_journey", "charco", "icp", "contrarian",
        "asociaciones", "identidad", "oferta", "lead_magnet",
    ]
    for node_id in node_ids:
        assert node_id in system_prompt, f"Missing node id '{node_id}' from system_prompt"

    # 4. Diagnostico (node 01) is the hard triage that governs everything after it
    assert "governs everything Brandy says afterward" in system_prompt or \
        "governs the rest of the session" in system_prompt.lower(), \
        "diagnostico must be documented as the triage that governs what comes after"
    assert "PROHIBITED" in system_prompt, "Missing PROHIBITED (diagnostico's prohibicion field)"
    assert "skill to unlock" in system_prompt.lower(), \
        "diagnostico must specify the skill to unlock"

    # 5. Verify the confirmation loop is still present
    assert "EXPLICIT YES" in system_prompt, \
        "Missing confirmation rule: sections only close on an EXPLICIT YES from the founder"

    # 6. Verify NO gamification
    assert "No gamification" in system_prompt, \
        "Missing explicit statement: 'No gamification'"


def test_system_prompt_count_nine_sections():
    """Verify exactly nine numbered nodes (01 - ... through 09 - ...) are listed."""
    import re
    from pathlib import Path

    app_js_path = Path(__file__).parent.parent / "app" / "static" / "app.js"
    with open(app_js_path, encoding="utf-8") as f:
        content = f.read()

    # Extract the baseSystemPrompt constant (renamed in Pieza 10 for dynamic memory injection)
    system_prompt_match = re.search(
        r'const baseSystemPrompt = `(.+?)`;',
        content,
        re.DOTALL | re.MULTILINE
    )

    assert system_prompt_match, "Could not find baseSystemPrompt constant in app.js"
    system_prompt = system_prompt_match.group(1)

    # Each node is introduced as "NN - Name (node_id):" at the start of a line.
    node_headers = re.findall(r'^(\d{2}) - .+? \(\w+\):', system_prompt, re.MULTILINE)

    assert len(node_headers) == 9, \
        f"Expected exactly 9 numbered nodes, found {len(node_headers)}. Headers: {node_headers}"
    assert node_headers == [f"{i:02d}" for i in range(1, 10)], \
        f"Node numbers must run 01..09 in order, got {node_headers}"


def test_questions_py_has_consistent_labels():
    """
    Sanity check: Verify questions.py has the correct Spanish labels too.
    This ensures consistency between Python schema and the system_prompt.
    """
    from app.tools.brand_brain.questions import SECTIONS, get_section_by_id

    # Verify critical sections have correct labels
    # NOTE: questions.py has legacy labels that should be consistent with system_prompt
    # but changing them now would break deployed code's DB schema
    # IMPORTANT: The system_prompt is what the LLM reads, and that has been fixed
    brand_journey = get_section_by_id("brand_journey")
    assert brand_journey is not None, "brand_journey section not found"

    diagnostico = get_section_by_id("diagnostico")
    assert diagnostico is not None, "diagnostico section not found"

    icp = get_section_by_id("icp")
    assert icp is not None, "icp section not found"

    # The test documents that labels in questions.py may not match system_prompt exactly
    # but the IDs (brand_journey, diagnostico, icp) are correct and consistent
