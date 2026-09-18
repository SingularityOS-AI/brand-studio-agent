"""
Unit tests for PIEZA 35 BUG 4 fixes (Script Kind derivation and prompt integration).

Tests:
- BUG 4a: `_derive_script_kind()` correctly maps subcategories to script kinds
- BUG 4b: `_build_generation_prompt()` includes script_kind in the prompt
- BUG 4c: `generate_script()` derives script kind from idea when idea_kind not provided
- BUG 4d: `generate_script()` uses provided idea_kind when given
"""
import pytest
from unittest.mock import Mock, patch
from app.scripting.scripts import _derive_script_kind


@pytest.mark.asyncio
async def test_derive_script_kind_tutorial():
    """
    BUG 4a: Subcategory 'Top N/Listículo técnico' maps to script kind 'tutorial'.
    """
    idea = Mock()
    idea.subcategory = "Top N/Listículo técnico"
    result = _derive_script_kind(idea)
    assert result == "tutorial"


@pytest.mark.asyncio
async def test_derive_script_kind_case_study():
    """
    BUG 4a: Subcategory 'Desglose de caso de éxito' maps to script kind 'case_study'.
    """
    idea = Mock()
    idea.subcategory = "Desglose de caso de éxito"
    result = _derive_script_kind(idea)
    assert result == "case_study"


@pytest.mark.asyncio
async def test_derive_script_kind_story():
    """
    BUG 4a: Subcategory 'Tesis Contrarian' maps to script kind 'story'.
    """
    idea = Mock()
    idea.subcategory = "Tesis Contrarian"
    result = _derive_script_kind(idea)
    assert result == "story"


@pytest.mark.asyncio
async def test_derive_script_kind_promo():
    """
    BUG 4a: Subcategory 'Mito vs Realidad' maps to script kind 'promo'.
    """
    idea = Mock()
    idea.subcategory = "Mito vs Realidad"
    result = _derive_script_kind(idea)
    assert result == "promo"


@pytest.mark.asyncio
async def test_derive_script_kind_comparison():
    """
    BUG 4a: Subcategory 'Pregunta de debate' maps to script kind 'comparison'.
    """
    idea = Mock()
    idea.subcategory = "Pregunta de debate"
    result = _derive_script_kind(idea)
    assert result == "comparison"


@pytest.mark.asyncio
async def test_derive_script_kind_metricas_is_case_study():
    """
    BUG 4a: 'Antes/Después con métricas' (validacion_resultados) -> 'case_study'.

    QA Pieza 35: este test se llamaba "_testimony" pero asertaba 'case_study'.
    El mapeo real NUNCA devuelve "testimony" -- solo aparecia en el docstring.
    Renombrado para que el nombre diga lo que el test hace.
    """
    idea = Mock()
    idea.subcategory = "Antes/Después con métricas"
    result = _derive_script_kind(idea)
    assert result == "case_study"


@pytest.mark.asyncio
async def test_derive_script_kind_never_returns_testimony():
    """
    QA Pieza 35: invariante -- ninguna subcategoria real produce "testimony".
    Si alguien lo agrega al mapeo, que este test obligue a actualizar el docstring.
    """
    from app.catalog.ideas import MASTER_CATEGORIES

    for cat in MASTER_CATEGORIES:
        for sub in cat["subcategories"]:
            idea = Mock()
            idea.subcategory = sub
            idea.master_category = cat["id"]
            assert _derive_script_kind(idea) != "testimony", (
                f"'{sub}' devolvio 'testimony'; actualiza el docstring de _derive_script_kind"
            )


@pytest.mark.asyncio
async def test_derive_script_kind_falls_back_by_master_category():
    """
    QA Pieza 35: el camino de respaldo por master_category no estaba cubierto.
    Subcategoria desconocida + master_category conocida debe usar el default de
    esa categoria, NO caer al "tutorial" global.
    """
    idea = Mock()
    idea.subcategory = "subcategoria que no existe"
    idea.master_category = "validacion_resultados"
    assert _derive_script_kind(idea) == "case_study"

    idea2 = Mock()
    idea2.subcategory = "otra que no existe"
    idea2.master_category = "discusion_industria"
    assert _derive_script_kind(idea2) == "comparison"


@pytest.mark.asyncio
async def test_derive_script_kind_unknown_fallback():
    """
    BUG 4a: Unknown subcategory falls back to 'tutorial'.
    """
    idea = Mock()
    idea.subcategory = "unknown_category"
    result = _derive_script_kind(idea)
    assert result == "tutorial"


@pytest.mark.asyncio
async def test_build_generation_prompt_includes_script_kind():
    """
    BUG 4b: Verify that _build_generation_prompt() includes script_kind in the prompt.
    """
    from app.scripting.scripts import _build_generation_prompt
    import json

    brand_context = Mock()
    brand_context.model_dump.return_value = {"section": "value"}

    idea = Mock()
    idea.model_dump.return_value = {"id": "123", "text": "Test idea"}

    interview_transcript = "Mock interview transcript"

    source_mode = "interview"

    script_kind = "case_study"

    # Call the function with all required 5 arguments
    prompt = _build_generation_prompt(brand_context, idea, interview_transcript, source_mode, script_kind)

    # Verify script kind appears in prompt
    assert "case_study" in prompt
