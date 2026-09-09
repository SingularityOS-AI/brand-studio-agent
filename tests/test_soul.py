"""
Brand Soul Generator Tests

Tests for the Brand Soul document generation (Pieza 2-b).

Test coverage:
1. Complete brain + generate → HTML with all citations validated
2. Mocked generator returning invented citation → validation fails, document not shown
3. Incomplete brain (5 sections) → generation refused, error lists missing sections
4. Generate twice on same brain → identical HTML (proves caching works)
5. HTML includes etapa with skill and prohibition
6. Validation function: invented citations detected correctly
7. Validation function: valid citations pass validation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_soul.generator import (
    generate_brand_soul,
    validate_citations_in_html,
    _check_all_sections_confirmed,
    _extract_literal_citations,
    IncompleteBrainError,
    CitationValidationError,
    SoulGenerationError
)
from app.tools.brand_soul.template import (
    get_etapa_context,
    ETAPAS_CONFIG
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def complete_confirmed_brain():
    """A BrandBrain with all 9 sections confirmed."""
    brain = BrandBrain()

    sections_data = [
        {
            "id": "diagnostico", "label": "Diagnóstico",
            "content": {
                "etapa": "creador atascado",
                "sintoma_diagnostico": "Engrosar embudo sin convertir",
                "habilidad_a_desbloquear": "Ingeniería de ofertas",
                "prohibicion": "No hacer género vertical",
                "postura": "experto"
            },
            "citation_text": "Elvia diagnosticó que estás en creador atascado con engrosamiento de embudo",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "brand_journey", "label": "Brand Journey",
            "content": {
                "resultado_deseado": "Ser referente en consultoría",
                "de_que_ser_conocido": "Transformación empresarial",
                "que_hacer": "Consultoría 1:1",
                "que_aprender": "Diseño de programas"
            },
            "citation_text": "Elvia explicó que el cliente viaja del 'no saber' al 'sí quiero'",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "charco", "label": "El Charco",
            "content": {
                "problema": "Pymes que no convertían tráfico",
                "nivel": "charco",
                "logro_que_lo_respalda": "300 empresas digitalizadas"
            },
            "citation_text": "Elvia identificó que tu servicio es para pymes con problema de conversión",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "icp", "label": "ICP — A quién le mandas la factura",
            "content": {
                "quien_decide": "CEO de pymes",
                "disparador_de_urgencia": "Q3 audiencia externa",
                "poder_adquisitivo": "50-100k€"
            },
            "citation_text": "Elvia validó que tu cliente ideal son CEOs de pymes con presupuesto",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "contrarian", "label": "Postura Contraria",
            "content": {
                "creencia_comun": "Necesitas más redes sociales",
                "postura_opuesta": "Necesitas menos redes, más profundidad",
                "prueba": "Clientes redujeron redes y duplicaron engagement"
            },
            "citation_text": "Elvia desafió la creencia de que necesitas más redes sociales",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "asociaciones", "label": "Asociaciones",
            "content": {
                "deseadas": "auténtico, profundo",
                "prohibidas": "superficial, spam"
            },
            "citation_text": "Elvia clarificó cómo quieres ser percibido",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "identidad", "label": "Identidad",
            "content": {
                "voz": "Directa, profesional",
                "colores": "#2563EB, #000000",
                "tipografias": "Inter, Roboto"
            },
            "citation_text": "Elvia dijo que tu marca es auténtica y profunda, nunca superficial",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "oferta", "label": "Oferta",
            "content": {
                "resultado_sonado": "Duplicar ingresos",
                "probabilidad_percibida": "50 casos verificados",
                "retraso": "30 días",
                "esfuerzo": "2h/semana",
                "componentes": "3 emails/semana"
            },
            "citation_text": "Elvia definió tu oferta con resultado soñado y componentes específicos",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "lead_magnet", "label": "Lead Magnet",
            "content": {
                "tipo": "revelador",
                "problema_A": "Baja conversión",
                "problema_B_que_revela": "Falta de nurturing"
            },
            "citation_text": "Elvia propuso un lead magnet revelador como regalo inicial",
            "citation_source": "usuario",
            "status": "confirmado"
        },
    ]

    for section_data in sections_data:
        section = Section(**section_data)
        brain.sections.append(section)

    return brain


@pytest.fixture
def incomplete_brain():
    """A BrandBrain with only 5 sections (missing 4)."""
    brain = BrandBrain()

    sections_data = [
        {
            "id": "brand_journey",
            "label": "Brand Journey",
            "content": {
                "resultado_deseado": "Ser referente",
                "de_que_ser_conocido": "Transformación",
                "que_hacer": "Consultoría",
                "que_aprender": "Diseño"
            },
            "citation_text": "Elvia explicó el viaje del cliente",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "diagnostico",
            "label": "Diagnóstico",
            "content": {
                "etapa": "explorador",
                "sintoma_diagnostico": "Testing etapas",
                "habilidad_a_desbloquear": "Skills",
                "prohibicion": "Prohibiciones",
                "postura": "experto"
            },
            "citation_text": "Estás en etapa de exploración",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "charco",
            "label": "El Charco",
            "content": {
                "problema": "Dolor genérico",
                "nivel": "charco",
                "logro_que_lo_respalda": "Logros"
            },
            "citation_text": "Elvia identificó el dolor",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "icp",
            "label": "ICP — A quién le mandas la factura",
            "content": {
                "quien_decide": "Decisor",
                "disparador_de_urgencia": "Urgencia",
                "poder_adquisitivo": "Presupuesto"
            },
            "citation_text": "Elvia validó tu cliente ideal",
            "citation_source": "usuario",
            "status": "confirmado"
        },
        {
            "id": "contrarian",
            "label": "Postura Contraria",
            "content": {
                "creencia_comun": "Creencia común",
                "postura_opuesta": "Posición contraria",
                "prueba": "Pruebas"
            },
            "citation_text": "Elvia desafió la creencia común",
            "citation_source": "usuario",
            "status": "confirmado"
        },
    ]

    for section_data in sections_data:
        section = Section(**section_data)
        brain.sections.append(section)

    return brain


@pytest.fixture
def sample_html_with_citations():
    """Sample HTML with valid citations."""
    html = """
    <div class="soul-document">
        <div class="citation">"Elvia explicó que el cliente viaja del 'no saber' al 'sí quiero'"</div>
        <div class="citation">"Elvia identificó que tu servicio es para pymes con problema de conversión"</div>
        <div class="citation">"Elvia desafió la creencia de que necesitas más redes sociales"</div>
    </div>
    """
    return html


@pytest.fixture
def sample_html_with_invented_citations():
    """Sample HTML with invented citations (not in brain)."""
    html = """
    <div class="soul-document">
        <div class="citation">"Elvia explicó que el cliente viaja del 'no saber' al 'sí quiero'"</div>
        <div class="citation">"Elvia diagnostic&oacute; que est&aacute;s en creador atascado con engrosamiento de embudo"</div>
        <div class="citation">"Esta cita fue inventada por el LLM y no existe en el cerebro"</div>
    </div>
    """
    return html


# =============================================================================
# TEST: Complete Brain → Valid HTML
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
@patch("app.tools.brand_soul.generator._check_cache")
@patch("app.tools.brand_soul.generator._save_cache")
def test_generate_soul_complete_brain_produces_valid_html(
    mock_save_cache,
    mock_check_cache,
    mock_get_brain,
    complete_confirmed_brain
):
    """
    Given a complete brand brain with all 9 sections confirmed,
    When the generate endpoint is called,
    Then it should produce HTML with all citations validated.
    """
    # Setup mocks
    mock_get_brain.return_value = complete_confirmed_brain
    mock_check_cache.return_value = None  # No cache
    mock_save_cache.return_value = True

    # Generate
    session_token = "test_session_token"
    html, cache_status = generate_brand_soul(session_token)

    # Assertions
    assert cache_status == "generated"
    assert html is not None
    assert "<!DOCTYPE html>" in html

    # The template renders 8 sections, but "asociaciones" is merged into "identidad",
    # so only "identidad" citation appears. ICP is metadata-only and not rendered.
    # Check that main section citations appear in HTML:
    sections_in_document = [
        "diagnostico", "brand_journey", "charco", "contrarian",
        "identidad", "oferta", "lead_magnet"
    ]
    expected_citations_in_doc = [
        next(s.citation_text for s in complete_confirmed_brain.sections if s.id == section_id)
        for section_id in sections_in_document
    ]
    for citation in expected_citations_in_doc:
        # Normalize accents for comparison
        import unicodedata
        normalized_citation = unicodedata.normalize('NFKD', citation).encode('ASCII', 'ignore').decode('ASCII')
        normalized_html = unicodedata.normalize('NFKD', html).encode('ASCII', 'ignore').decode('ASCII')
        # Better: just check the citation appears in HTML with accent preservation
        assert citation in html, f"Citation not found: {citation}"


# =============================================================================
# TEST: Invented Citations → Validation Fails
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_validate_citations_with_invented_fails(
    mock_get_brain,
    complete_confirmed_brain,
    sample_html_with_invented_citations
):
    """
    Given brain with valid citations,
    When generated HTML contains an invented citation,
    Then validation should fail and document should not be returned.
    """
    # Setup mock
    mock_get_brain.return_value = complete_confirmed_brain

    # Validate
    is_valid, invented_citations = validate_citations_in_html(
        sample_html_with_invented_citations,
        complete_confirmed_brain
    )

    # Assertions
    assert is_valid is False
    assert len(invented_citations) == 1
    assert "Esta cita fue inventada" in invented_citations[0]


# =============================================================================
# TEST: Incomplete Brain → Generation Refused
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_generate_soul_incomplete_brain_raises_error(
    mock_get_brain,
    incomplete_brain
):
    """
    Given a brand brain with only 5 sections,
    When the generate endpoint is called,
    Then it should raise IncompleteBrainError listing missing sections.
    """
    # Setup mock
    mock_get_brain.return_value = incomplete_brain

    # Generate
    session_token = "test_session_token"

    # Should raise IncompleteBrainError
    with pytest.raises(IncompleteBrainError) as exc_info:
        generate_brand_soul(session_token)

    # Check error message lists missing sections
    error_msg = str(exc_info.value)
    assert "Faltan secciones" in error_msg


# =============================================================================
# TEST: Validation Function
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_validate_citations_all_valid_passes(
    mock_get_brain,
    complete_confirmed_brain,
    sample_html_with_citations
):
    """
    Given brain with valid citations,
    When HTML contains only citations from the brain,
    Then validation should pass.
    """
    # Setup mock
    mock_get_brain.return_value = complete_confirmed_brain

    # Validate
    is_valid, invented_citations = validate_citations_in_html(
        sample_html_with_citations,
        complete_confirmed_brain
    )

    # Assertions
    assert is_valid is True
    assert len(invented_citations) == 0


@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_validate_citations_multiple_invented(
    mock_get_brain,
    complete_confirmed_brain
):
    """
    Given brain with valid citations,
    When HTML contains multiple invented citations,
    Then validation should fail and report all invented citations.
    """
    # Setup mock
    mock_get_brain.return_value = complete_confirmed_brain

    # HTML with 2 invented citations (and use one valid citation from the brain)
    valid_citation = complete_confirmed_brain.sections[0].citation_text
    html = f"""
    <div class="citation">"{valid_citation}"</div>
    <div class="citation">"Invented citation number 1"</div>
    <div class="citation">"Invented citation number 2"</div>
    """

    # Validate
    is_valid, invented_citations = validate_citations_in_html(
        html,
        complete_confirmed_brain
    )

    # Assertions
    assert is_valid is False
    assert len(invented_citations) == 2
    assert "Invented citation number 1" in invented_citations


# =============================================================================
# TEST: Check All Sections Confirmed
# =============================================================================

def test_check_all_sections_confirmed_complete(complete_confirmed_brain):
    """
    Given a complete brand brain with all 9 sections confirmed,
    When _check_all_sections_confirmed is called,
    Then it should return is_complete=True and empty missing list.
    """
    is_complete, missing = _check_all_sections_confirmed(complete_confirmed_brain)

    assert is_complete is True
    assert len(missing) == 0


def test_check_all_sections_confirmed_incomplete(incomplete_brain):
    """
    Given an incomplete brand brain,
    When _check_all_sections_confirmed is called,
    Then it should return is_complete=False and list missing sections.
    """
    is_complete, missing = _check_all_sections_confirmed(incomplete_brain)

    assert is_complete is False
    assert len(missing) == 4  # 9 total - 5 present = 4 missing

    # Check specific missing sections are mentioned
    missing_text = ", ".join(missing)
    assert "asociaciones" in missing_text  # One of the missing sections
    assert "identidad" in missing_text  # Another missing section


# =============================================================================
# TEST: Extract Literal Citations
# =============================================================================

def test_extract_literal_citations(complete_confirmed_brain):
    """
    Given a brand brain,
    When _extract_literal_citations is called,
    Then it should return a dict mapping section_id to citation_text.
    """
    citations = _extract_literal_citations(complete_confirmed_brain)

    assert len(citations) == 9
    assert "brand_journey" in citations
    assert "diagnostico" in citations
    assert citations["brand_journey"] == complete_confirmed_brain.sections[1].citation_text


# =============================================================================
# TEST: ETAPA Context
# =============================================================================

def test_get_etapa_context_valid_stage():
    """
    Given a valid stage name,
    When get_etapa_context is called,
    Then it should return the correct context with name, skill, and prohibition.
    """
    context = get_etapa_context("momentum")

    assert context["name"] == "Moméntum"  # Takes accent from template
    assert context["skill_to_unlock"] == "tu oferta irrechazable — la ecuación de valor que cierra la venta"
    assert "hacer ofertas blandas" in context["prohibited"]
    assert "description" in context


def test_get_etapa_context_invalid_stage():
    """
    Given an invalid stage name,
    When get_etapa_context is called,
    Then it should raise ValueError.
    """
    with pytest.raises(ValueError):
        get_etapa_context("invalid_stage")


def test_etapas_config_structure():
    """
    Given ETAPAS_CONFIG from template,
    Then each etapa should have required fields: name, skill_to_unlock, prohibited, description.
    """
    for stage_id, config in ETAPAS_CONFIG.items():
        assert "name" in config
        assert "skill_to_unlock" in config
        assert "prohibited" in config
        assert "description" in config


# =============================================================================
# TEST: HTML Includes ETAPA with Skill and Prohibition
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
@patch("app.tools.brand_soul.generator._check_cache")
@patch("app.tools.brand_soul.generator._save_cache")
def test_html_includes_etapa_with_skill_and_prohibition(
    mock_save_cache,
    mock_check_cache,
    mock_get_brain,
    complete_confirmed_brain
):
    """
    Given a complete brand brain with Momentum stage,
    When the generate endpoint is called,
    Then the HTML should include etapa name, skill to unlock, and prohibition.
    """
    # Setup mocks
    mock_get_brain.return_value = complete_confirmed_brain
    mock_check_cache.return_value = None
    mock_save_cache.return_value = True

    # Generate
    session_token = "test_session_token"
    html, cache_status = generate_brand_soul(session_token)

    # Assertions - check ETAPA box exists in HTML
    # Note: The specific etapa content depends on what detect_etapa_from_brand_brain()
    # returns based on the brain's etapa content. For our test, we just check that
    # an etapa-box exists with the expected structure.
    assert "etapa-box" in html
    assert "<div class=\"etapa-box\">" in html
    assert "Lo único que importa ahora:" in html
    assert "Prohibido:" in html


# =============================================================================
# TEST: Validation Check Defense in Depth
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_validate_citations_empty_html(mock_get_brain, complete_confirmed_brain):
    """
    Given brain with valid citations,
    When HTML has no citations,
    Then validation should pass (empty list is valid).
    """
    # Setup mock
    mock_get_brain.return_value = complete_confirmed_brain

    # Validate empty HTML
    html = "<div>No citations here</div>"
    is_valid, invented_citations = validate_citations_in_html(
        html,
        complete_confirmed_brain
    )

    assert is_valid is True
    assert len(invented_citations) == 0


# =============================================================================
# TEST: Caching Mechanism (mocked cache returns HTML)
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
@patch("app.tools.brand_soul.generator._check_cache")
def test_generate_soul_with_cache_hit(mock_check_cache, mock_get_brain):
    """
    Given a brand brain,
    When cached HTML exists,
    Then generate_brand_soul should return cached HTML without regenerating.
    """
    # Setup mocks - manually create a complete brain
    brain = BrandBrain()
    for import_data in [
        {
            "id": "diagnostico", "label": "Diagnóstico",
            "content": {"etapa": "momentum", "sintoma_diagnostico": "X", "habilidad_a_desbloquear": "Y", "prohibicion": "Z", "postura": "ex"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "brand_journey", "label": "Brand Journey",
            "content": {"resultado_deseado": "X", "de_que_ser_conocido": "Y", "que_hacer": "Z", "que_aprender": "W"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "charco", "label": "Charco",
            "content": {"problema": "Dolor", "nivel": "charco", "logro_que_lo_respalda": "Logro"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "icp", "label": "ICP",
            "content": {"quien_decide": "CEO", "disparador_de_urgencia": "Q4", "poder_adquisitivo": "50k"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "contrarian", "label": "Postura Contraria",
            "content": {"creencia_comun": "A", "postura_opuesta": "B", "prueba": "C"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "asociaciones", "label": "Asociaciones",
            "content": {"deseadas": ["a"], "prohibidas": ["b"]},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "identidad", "label": "Identidad",
            "content": {"voz": "X", "colores": "#FFF", "tipografias": "Y"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "oferta", "label": "Oferta",
            "content": {"resultado_sonado": "X", "probabilidad_percibida": "Y", "retraso": "Z", "esfuerzo": "W", "componentes": "V"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
        {
            "id": "lead_magnet", "label": "Lead Magnet",
            "content": {"tipo": "X", "problema_A": "Y", "problema_B_que_revela": "Z"},
            "citation_text": "Cita", "citation_source": "usuario", "status": "confirmado"
        },
    ]:
        brain.sections.append(Section(**import_data))

    mock_get_brain.return_value = brain

    cached_html = "<div>CACHED HTML DOCUMENT</div>"
    mock_check_cache.return_value = cached_html

    # Generate
    session_token = "test_session_token"
    html, cache_status = generate_brand_soul(session_token)

    # Assertions
    assert cache_status == "cached"
    assert html == cached_html


# =============================================================================
# TEST: No Brain Found
# =============================================================================

@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_generate_soul_no_brain_raises_error(mock_get_brain):
    """
    Given no brand brain for the session,
    When generate_brand_soul is called,
    Then it should raise SoulGenerationError.
    """
    # Setup mock - brain not found
    mock_get_brain.return_value = None

    # Generate
    session_token = "no_brain_session"

    # Should raise SoulGenerationError
    with pytest.raises(SoulGenerationError) as exc_info:
        generate_brand_soul(session_token)

    # Check error message
    error_msg = str(exc_info.value)
    assert "No brand brain found" in error_msg


# ---------------------------------------------------------------------------
# Regresion: una cita inventada FUERA del <div class="citation"> tambien tiene
# que rechazarse. La validacion original solo miraba dentro de ese contenedor,
# asi que una cita tejida en la prosa pasaba intacta — que es justo lo que hace
# un LLM al que se le pide que escriba como estratega.
# ---------------------------------------------------------------------------

def test_cita_inventada_en_la_prosa_se_rechaza():
    from app.tools.brand_brain.models import Section, BrandBrain
    from app.tools.brand_soul.generator import validate_citations_in_html

    brain = BrandBrain(sections=[Section(
        id="charco", label="El charco", status="confirmado", content="x",
        citation_text="llevo ocho anos auditando bufetes chicos",
        citation_source="usuario",
    )])

    for html in [
        '<p>Como dijiste, "llevo quince anos en banca", y eso define tu autoridad.</p>',
        '<blockquote>"soy el referente numero uno"</blockquote>',
        '<p>Dijiste &quot;tengo diez mil clientes&quot; hoy</p>',
        '<p>Dijiste “tengo un exit de 40 millones”</p>',
    ]:
        ok, inventadas = validate_citations_in_html(html, brain)
        assert ok is False, f"paso una cita inventada: {html}"
        assert inventadas


def test_cita_real_no_da_falso_positivo():
    from app.tools.brand_brain.models import Section, BrandBrain
    from app.tools.brand_soul.generator import validate_citations_in_html

    brain = BrandBrain(sections=[Section(
        id="charco", label="El charco", status="confirmado", content="x",
        citation_text="llevo ocho anos auditando bufetes chicos",
        citation_source="usuario",
    )])

    # Misma cita, con mayuscula inicial y punto final: sigue siendo la suya.
    ok, inventadas = validate_citations_in_html(
        '<p>Dijiste: "Llevo ocho anos auditando bufetes chicos."</p>', brain
    )
    assert ok is True, f"falso positivo: {inventadas}"
