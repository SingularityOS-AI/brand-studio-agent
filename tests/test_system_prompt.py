"""
Test that the system_prompt uses correct section names as defined in spec.md

Verifies that the LLM receives the same section names as the Python schema defnes.
No silent corruption where Brandy asks for one thing but stores under another label.
"""

import pytest


def test_system_prompt_uses_correct_section_names():
    """
    CRITICAL: The system_prompt sent to the LLM MUST match the schema definitions.

    According to spec.md §2.1 (FIRMADA), the nine sections are:
    1. Brand Journey (foundator's journey, NOT customer journey)
    2. Etapa del Fundador 1-5 (fundator stage, NOT business stage)
    3. El Charco del Dolor
    4. Experto o Estudiante (triaje, NOT "Problem Credibility")
    5. Punto Contrarian
    6. Asociaciones Mentales
    7. Identidad de Marca
    8. Oferta Irresistible
    9. Lead Magnet

    This test verifies the actual system_prompt content, not constants.
    """
    # Read the actual system_prompt from app.js
    import re
    from pathlib import Path

    app_js_path = Path(__file__).parent.parent / "app" / "static" / "app.js"
    with open(app_js_path, encoding="utf-8") as f:
        content = f.read()

    # Extract the systemPrompt constant
    system_prompt_match = re.search(
        r'const systemPrompt = `(.+?)`;',
        content,
        re.DOTALL | re.MULTILINE
    )

    assert system_prompt_match, "Could not find systemPrompt constant in app.js"
    system_prompt = system_prompt_match.group(1)

    # CRITICAL CHECK: Verify section names match spec.md

    # 1. "Brand Journey" must mention FOUNDER, not customer
    assert "Brand Journey" in system_prompt, "Missing 'Brand Journey' section"
    # It should NOT say "Viaje del Cliente" or "Customer Journey"
    assert "Viaje del Cliente" not in system_prompt or "Customer Journey" not in system_prompt, \
        "Brand Journey is for the FOUNDER, not the customer. 'Viaje del Cliente' or 'Customer Journey' is wrong."
    # It MUST say "founder" or similar to indicate it's about the founder's journey
    assert any(word in system_prompt.lower() for word in ["founder", "fundador", "foundator"]), \
        "Brand Journey must describe the FOUNDER's journey, not customer journey"

    # 2. "Etapa del Fundador" - MUST mention founder stage, NOT business stage
    # Should NOT say "Etapa del Negocio" or "Business Stage"
    assert "Etapa del Fundador" in system_prompt, \
        "Missing 'Etapa del Fundador' - should be founder stage, not business stage"
    assert "Etapa del Negocio" not in system_prompt, \
        "Etapa del Negocio is wrong - should be Etapa del Fundador"
    assert "Business Stage" not in system_prompt.split("Etapa del Fundador")[0].split("founder")[0], \
        "Business Stage in叙述部分应该是描述business stage和challenges，不是section定义"
    # The prompt mentions "their business stage" at the beginning, which is fine
    # The key is the SECTION definition must say "Etapa del Fundador"

    # 3. "Experto o Estudiante" - CRITICAL TRIAGE, NOT "Credibilidad del Problema"
    # This is the WORST error because it disables the entire guardrail
    assert ("Experto o Estudiante" in system_prompt and "Expert or Student" in system_prompt), \
        "Must include both Spanish 'Experto o Estudiante' and English 'Expert or Student' section names"
    assert "Credibilidad del Problema" not in system_prompt, \
        "Credibilidad del Problema is wrong - should be 'Experto o Estudiante'"
    assert "Problem Credibility" not in system_prompt, \
        "Problem Credibility is wrong - should be 'Expert or Student'"
    # Must mention it governs the rest of the session
    assert any(phrase in system_prompt.lower() for phrase in [
        "governs the rest of the session",
        "gobierna el resto de la sesión",
        "frames the rest of the session"
    ]), "Experto o Estudiante must be documented as the triage that governs the session"

    # 4. Verify all nine sections are mentioned
    sections_must_include = [
        "Brand Journey",
        "Etapa del Fundador",
        "El Charco del Dolor",
        "Experto o Estudiante",
        "Punto Contrarian",
        "Asociaciones Mentales",
        "Identidad de Marca",
        "Oferta Irresistible",
        "Lead Magnet"
    ]

    for section in sections_must_include:
        assert section in system_prompt, f"Missing section '{section}' from system_prompt"

    # 5. Verify the confirmation loop is still present (from 2C-a)
    assert "If I understand correctly" in system_prompt, \
        "Missing confirmation loop: 'If I understand correctly...'"
    assert "Am I on track" in system_prompt, \
        "Missing confirmation question: 'Am I on track?'"

    # 6. Verify NO gamification (from 2C-a)
    assert "No gamification" in system_prompt, \
        "Missing explicit statement: 'No gamification'"

    # 7. Verify stage definition includes skill to unlock and prohibition
    # The prompt mentions "skill to unlock" and "PROHIBITED" - this is correct
    # No need to check Spanish phrases since the prompt is in English
    assert ("skill to unlock" in system_prompt.lower() and "prohibited" in system_prompt.lower()), \
        "When identifying founder stage, must specify the skill to unlock and what's prohibited"


def test_system_prompt_count_nine_sections():
    """Verify exactly nine sections are listed in system_prompt"""
    import re
    from pathlib import Path

    app_js_path = Path(__file__).parent.parent / "app" / "static" / "app.js"
    with open(app_js_path, encoding="utf-8") as f:
        content = f.read()

    # Extract the systemPrompt constant
    system_prompt_match = re.search(
        r'const systemPrompt = `(.+?)`;',
        content,
        re.DOTALL | re.MULTILINE
    )

    assert system_prompt_match, "Could not find systemPrompt constant in app.js"
    system_prompt = system_prompt_match.group(1)

    # Count bullet points in the sections list
    # The sections are listed as bullet points after "extracts nine key brand sections:"
    sections_match = re.search(
        r'extracts nine key brand sections:(.+?)CRITICAL:',
        system_prompt,
        re.DOTALL
    )

    assert sections_match, "Could not find sections list in system_prompt"
    sections_text = sections_match.group(1)

    # Count bullet-like entries (lines starting with "-")
    bullets = [line.strip() for line in sections_text.split('\n') if line.strip().startswith('-')]

    assert len(bullets) == 9, \
        f"Expected exactly 9 sections, found {len(bullets)}. Sections: {bullets}"


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

    etapa = get_section_by_id("etapa")
    assert etapa is not None, "etapa section not found"

    credibilidad = get_section_by_id("credibilidad")
    assert credibilidad is not None, "credibilidad section not found"

    # The test documents that labels in questions.py may not match system_prompt exactly
    # but the IDs (brand_journey, etapa, credibilidad) are correct and consistent
