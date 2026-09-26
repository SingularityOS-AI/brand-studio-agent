"""
F-01 - Brand Soul: consolidated long-form prose + end-to-end health check.

Two bugs sank this piece twice before (see docs/specs/F/pieces/F-01_brand_soul_prose.md):
1. The Executive Summary / closing sections were a dump of all 9 chapters
   concatenated with "---" markers, instead of short (120-200 word) prose.
2. The no-LLM fallback produced "field: value" dumps instead of readable prose.

This file guards against both regressions and proves the health check
(/api/brain extract -> /api/soul 404 -> /api/soul/generate -> /api/soul 200 ->
regenerate) still works end to end, with the network isolated and the LLM
mocked throughout.
"""

import html as html_module
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_soul import generator as soul_generator
from app.tools.brand_soul.generator import (
    CHAPTERS,
    _build_closing_note,
    _build_executive_summary,
    _fallback_prose,
    generate_brand_soul,
    validate_citations_in_html,
)
from app.tools.brand_soul.template import get_etapa_context

CHAPTER_HEADINGS = [heading for _, heading in CHAPTERS]

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "docs" / "specs" / "evidence" / "F-01"

# Field keys that must NEVER show up literally in the visible document -
# their presence means the fallback (or the LLM) fell back to a "key: value"
# dump instead of writing a sentence. Restricted to genuine snake_case
# identifiers (contain "_"): single-word keys like "etapa" or "voz" are
# plain Spanish words a founder's own answer can legitimately contain.
_FORBIDDEN_SNAKE_CASE_KEYS = [
    key
    for _, labels in soul_generator._FACT_LABELS.items()
    for _, key in labels
    if "_" in key
]


# =============================================================================
# FIXTURES
# =============================================================================


def _rich_sections_data() -> list[dict]:
    """A BrandBrain with all 9 sections confirmed, every field filled with
    realistic, multi-word content -- rich enough to exercise the fallback
    prose builders the way real founder answers would."""
    return [
        {
            "id": "diagnostico",
            "label": "Diagnóstico",
            "content": {
                "etapa": "creador atascado en la etapa tres",
                "nivel_ramiro": "cuatro, el cuello de botella",
                "sintoma_diagnostico": "el embudo se llena pero casi nada convierte en llamadas pagadas",
                "habilidad_a_desbloquear": "ingeniería de ofertas irresistibles",
                "prohibicion": "lanzar otro reel genérico sobre productividad",
                "postura": "experto",
                "justificacion_postura": "quince años operando agencias de marketing para pymes",
            },
            "citation_text": "Elvia diagnosticó que estoy en creador atascado, con el embudo lleno pero sin conversión real",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "brand_journey",
            "label": "Brand Journey",
            "content": {
                "resultado_deseado": "ser reconocido como el referente de ingeniería de ofertas para consultoras B2B",
                "de_que_ser_conocido": "el consultor que convierte prospectos fríos en clientes de retenedor alto",
                "que_hacer": "publicar tres casos de estudio detallados cada mes",
                "que_aprender": "diseño de garantías de riesgo invertido",
            },
            "citation_text": "Elvia me hizo decir en voz alta hacia dónde quiero que esta marca llegue en dos años",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "charco",
            "label": "El Charco",
            "content": {
                "problema": "pymes de servicios profesionales que generan tráfico pero no cierran ventas",
                "nivel": "charco",
                "logro_que_lo_respalda": "trescientas veces digitalizado embudos de pymes en los últimos cinco años",
                "costo_de_no_resolverlo": "miles de dólares en presupuesto de anuncios que nunca regresan como clientes",
                "intentos_fallidos": "contratar más vendedores junior sin arreglar la oferta",
            },
            "citation_text": "Elvia identificó que mi servicio es para pymes que no logran convertir el tráfico que ya tienen",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "icp",
            "label": "ICP",
            "content": {
                "quien_decide": "el CEO fundador de la pyme de servicios",
                "tamano_empresa": "entre veinte y cien empleados",
                "disparador_de_urgencia": "cuando el trimestre cierra por debajo de la meta de ventas",
                "poder_adquisitivo": "entre cincuenta mil y cien mil euros al año en marketing",
                "comite_de_compra": "el director financiero también tiene que aprobar el gasto",
                "a_quien_le_rinde_cuentas": "la junta directiva de la empresa",
            },
            "citation_text": "Elvia validó que mi cliente ideal es el CEO fundador de una pyme con presupuesto real",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "contrarian",
            "label": "Postura Contraria",
            "content": {
                "creencia_comun": "que necesitas publicar todos los días en redes sociales para crecer",
                "postura_opuesta": "que publicar menos pero con una oferta más fuerte convierte más que publicar todos los días",
                "prueba": "clientes que redujeron su frecuencia de publicación y duplicaron su tasa de cierre",
                "por_que_no_es_provocacion": "está respaldado por datos de conversión reales, no solo por una opinión llamativa",
            },
            "citation_text": "Elvia desafió la creencia de que hay que publicar todos los días para crecer",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "asociaciones",
            "label": "Asociaciones",
            "content": {
                "deseadas": "auténtico, riguroso, directo",
                "prohibidas": "genérico, agresivo, superficial",
            },
            "citation_text": "Elvia me hizo elegir con qué palabras quiero que la gente me describa a mis espaldas",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "identidad",
            "label": "Identidad",
            "content": {
                "voz": "directa, profesional, sin relleno",
                "colores": "#2563EB, #0F172A, #F8FAFC",
                "tipografias": "Inter para cuerpo, Space Grotesk para títulos",
                "narrativa_de_origen": "empecé arreglando el embudo roto de mi propia agencia antes de arreglar el de nadie más",
            },
            "citation_text": "Elvia dijo que mi marca es directa y profesional, nunca genérica ni agresiva",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "oferta",
            "label": "Oferta",
            "content": {
                "resultado_sonado": "duplicar la tasa de cierre de propuestas en noventa días",
                "probabilidad_percibida": "cincuenta casos de estudio verificados con nombre y cifra real",
                "retraso": "el primer resultado medible llega en treinta días",
                "esfuerzo": "dos horas por semana del equipo del cliente",
                "componentes": "auditoría de oferta, rediseño de propuesta, tres sesiones de cierre en vivo",
                "garantia": "garantía incondicional de devolución si no hay una propuesta nueva en treinta días",
            },
            "citation_text": "Elvia definió mi oferta con el resultado soñado y los componentes exactos que la sostienen",
            "citation_source": "usuario",
            "status": "confirmado",
        },
        {
            "id": "lead_magnet",
            "label": "Lead Magnet",
            "content": {
                "tipo": "revelador",
                "problema_A": "por qué las propuestas actuales no generan urgencia de compra",
                "problema_B_que_revela": "que el verdadero problema es la falta de garantía de riesgo invertido",
            },
            "citation_text": "Elvia propuso un lead magnet revelador como el primer paso gratuito hacia la oferta paga",
            "citation_source": "usuario",
            "status": "confirmado",
        },
    ]


@pytest.fixture
def rich_confirmed_brain() -> BrandBrain:
    brain = BrandBrain()
    for section_data in _rich_sections_data():
        brain.sections.append(Section(**section_data))
    return brain


# =============================================================================
# HELPERS
# =============================================================================


def _visible_text(html: str) -> str:
    """What a founder would actually read: no <style>/<script>, no tags."""
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _assert_no_dump_patterns(visible_text: str) -> None:
    """The exact regressions that sank this piece twice: JSON-looking text,
    "label: value" lines, and raw snake_case field names leaking through."""
    assert "{" not in visible_text
    assert "}" not in visible_text
    assert '":' not in visible_text
    for key in _FORBIDDEN_SNAKE_CASE_KEYS:
        assert key not in visible_text, f"raw field key '{key}' leaked into the visible document"


# =============================================================================
# UNIT TESTS: deterministic (no-LLM) fallback prose, per chapter
# =============================================================================


@pytest.mark.parametrize("section_id,heading", CHAPTERS)
def test_fallback_prose_is_readable_and_in_range(section_id, heading, rich_confirmed_brain):
    """Every no-LLM fallback chapter is 2-4 paragraphs of 150-350 words of
    prose -- never a 'field: value' dump."""
    section = rich_confirmed_brain.get_section(section_id)
    etapa_context = get_etapa_context("invisible")

    prose = _fallback_prose(section, etapa_context)
    paragraphs = [p for p in prose.split("\n\n") if p.strip()]

    assert 2 <= len(paragraphs) <= 4, f"{section_id}: expected 2-4 paragraphs, got {len(paragraphs)}"

    word_count = _word_count(prose)
    assert 150 <= word_count <= 350, f"{section_id}: expected 150-350 words, got {word_count}"

    _assert_no_dump_patterns(prose)
    assert "\n-" not in prose and "\n•" not in prose, f"{section_id}: bullet dump detected"


def test_executive_summary_is_short_prose_not_a_chapter_dump(rich_confirmed_brain):
    summary = _build_executive_summary(rich_confirmed_brain)

    word_count = _word_count(summary)
    assert 100 <= word_count <= 220, f"expected ~120-200 words, got {word_count}"

    _assert_no_dump_patterns(summary)
    assert "---" not in summary
    # The regression this guards against: dumping all 9 chapters together.
    for _, heading in CHAPTERS:
        assert heading not in summary


def test_closing_note_is_short_prose_not_a_chapter_dump(rich_confirmed_brain):
    closing = _build_closing_note(rich_confirmed_brain)

    word_count = _word_count(closing)
    assert 60 <= word_count <= 220, f"expected short prose, got {word_count} words"

    _assert_no_dump_patterns(closing)
    assert "---" not in closing
    for _, heading in CHAPTERS:
        assert heading not in closing


# =============================================================================
# INTEGRATION: full document, LLM unavailable (fallback path only)
# =============================================================================


@patch("app.tools.brand_soul.generator._get_vertex_ai_client", return_value=None)
@patch("app.tools.brand_soul.generator._save_cache", return_value=True)
@patch("app.tools.brand_soul.generator._check_cache", return_value=None)
@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_generate_soul_no_llm_produces_consolidated_prose_document(
    mock_get_brain, mock_check_cache, mock_save_cache, mock_client, rich_confirmed_brain
):
    """
    Given a complete brand brain and NO LLM available (Vertex AI client is
    None, exactly like a dev box without credentials),
    generate_brand_soul must still produce a full long-form prose document:
    Executive Summary, 9 English-titled chapters, closing note, all
    citations validated, and no JSON/key:value dumps anywhere.
    """
    mock_get_brain.return_value = rich_confirmed_brain

    html, cache_status = generate_brand_soul("session-f01-no-llm")

    assert cache_status == "generated"
    assert "<!DOCTYPE html>" in html

    visible = _visible_text(html)

    assert "Executive Summary" in visible
    assert "How Brandy Will Use This" in visible
    for heading in CHAPTER_HEADINGS:
        assert heading in visible, f"missing chapter heading: {heading}"

    _assert_no_dump_patterns(visible)
    assert "---" not in visible

    is_valid, invented = validate_citations_in_html(html, rich_confirmed_brain)
    assert is_valid, f"invented citations: {invented}"

    for section in rich_confirmed_brain.sections:
        assert section.citation_text in html


# =============================================================================
# INTEGRATION: full document, LLM available and used per chapter
# =============================================================================


@patch("app.tools.brand_soul.generator._call_llm_for_redaction")
@patch("app.tools.brand_soul.generator._save_cache", return_value=True)
@patch("app.tools.brand_soul.generator._check_cache", return_value=None)
@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_generate_soul_threads_llm_chapter_prose_into_document(
    mock_get_brain, mock_check_cache, mock_save_cache, mock_llm, rich_confirmed_brain
):
    """When the LLM redaction call succeeds, its output -- not the fallback
    -- must be what ends up in the document."""
    mock_get_brain.return_value = rich_confirmed_brain

    def _fake_llm(prompt: str, fallback_text: str) -> str:
        # A distinguishable marker per call, with no quotes (so it never
        # trips citation validation) and no forbidden dump patterns.
        return f"LLM-WRITTEN CHAPTER PROSE MARKER. {fallback_text.split('.')[0]}."

    mock_llm.side_effect = _fake_llm

    html, _ = generate_brand_soul("session-f01-llm")
    visible = _visible_text(html)

    assert visible.count("LLM-WRITTEN CHAPTER PROSE MARKER.") == len(CHAPTERS)

    is_valid, invented = validate_citations_in_html(html, rich_confirmed_brain)
    assert is_valid, f"invented citations: {invented}"


# =============================================================================
# HEALTH CHECK — walk the whole Brand Soul path through TestClient
# =============================================================================


@pytest.fixture
def in_memory_brand_brain_store(monkeypatch):
    """
    TEST_MODE always makes app.tools.brand_brain.store.get_brand_brain /
    save_brand_brain return None/False (no Supabase in tests), so an HTTP
    walk through /api/brain/extract would never actually persist anything
    between calls. Swap in one in-memory dict, patched at every import site
    that holds its own reference to these two functions.
    """
    storage: dict[str, BrandBrain] = {}
    html_cache: dict[str, str] = {}

    def _get(session_token):
        return storage.get(session_token)

    def _save(session_token, brain):
        storage[session_token] = brain
        return True

    def _check_cache(brain, session_token):
        return html_cache.get(session_token)

    def _save_cache(brain, html, session_token):
        html_cache[session_token] = html
        return True

    monkeypatch.setattr("app.tools.brand_brain.extractor.get_brand_brain", _get)
    monkeypatch.setattr("app.tools.brand_brain.extractor.save_brand_brain", _save)
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", _get)
    monkeypatch.setattr("app.tools.brand_brain.store.save_brand_brain", _save)
    monkeypatch.setattr("app.tools.brand_soul.generator.get_brand_brain", _get)
    monkeypatch.setattr("app.tools.brand_soul.generator._check_cache", _check_cache)
    monkeypatch.setattr("app.tools.brand_soul.generator._save_cache", _save_cache)
    monkeypatch.setattr("app.tools.brand_soul.generator._get_vertex_ai_client", lambda: None)
    return storage


def _extract_tool_result() -> dict:
    """One tool_result section per node, citation matching the transcript below."""
    sections = []
    for data in _rich_sections_data():
        sections.append(
            {
                "id": data["id"],
                "citation_text": data["citation_text"],
                "citation_source": data["citation_source"],
                "confirmed": True,
                "content": data["content"],
            }
        )
    return {"sections": sections}


def _extract_transcript() -> str:
    lines = ["agent: Cuéntame sobre tu marca, vamos nodo por nodo."]
    for data in _rich_sections_data():
        lines.append(f"user: {data['citation_text']}")
        lines.append("agent: Entendido, anoto eso y seguimos con el siguiente nodo.")
    return "\n".join(lines)


def test_health_check_brand_soul_path_end_to_end(
    in_memory_brand_brain_store, monkeypatch
):
    """
    Walks: POST /api/brain/extract -> GET /api/soul (404) -> POST
    /api/soul/generate (LLM mocked, via in_memory_brand_brain_store) -> GET
    /api/soul (200) -> POST /api/soul/generate again (regenerate).

    Records every status code as evidence in
    docs/specs/evidence/F-01/health_check.md (literal output, no verdicts).
    """
    monkeypatch.setenv("TEST_MODE", "true")

    from fastapi.testclient import TestClient

    from app.guard import guard
    from app.main import app
    from tests.jwt_helpers import create_test_jwt

    user_id = "550e8400-e29b-41d4-a716-446655440099"
    jwt_token = create_test_jwt(user_id)
    session_token = guard.create_user_session(user_id, initial_credits=250)
    guard._sessions[session_token] = {
        "credits": 250,
        "created_at": None,
        "user_id": user_id,
    }

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {jwt_token}"})

    results: list[tuple[str, int]] = []

    # 1. /api/brain/extract - persist all 9 confirmed sections
    extract_response = client.post(
        "/api/brain/extract",
        json={"transcript": _extract_transcript(), "tool_result": _extract_tool_result()},
    )
    results.append(("POST /api/brain/extract", extract_response.status_code))
    assert extract_response.status_code == 200, extract_response.text
    assert extract_response.json()["sections_count"] == 9
    assert extract_response.json()["skipped_sections"] == []

    # 2. /api/soul before generation -> 404
    soul_404 = client.get("/api/soul")
    results.append(("GET /api/soul (before generate)", soul_404.status_code))
    assert soul_404.status_code == 404

    # 3. /api/soul/generate - LLM mocked (Vertex AI client patched to None)
    generate_response = client.post("/api/soul/generate", json={"regenerate": False})
    results.append(("POST /api/soul/generate", generate_response.status_code))
    assert generate_response.status_code == 200, generate_response.text
    generated_html = generate_response.json()["html"]

    # 4. /api/soul after generation -> 200
    soul_200 = client.get("/api/soul")
    results.append(("GET /api/soul (after generate)", soul_200.status_code))
    assert soul_200.status_code == 200

    # 5. /api/soul/generate again - regenerate
    regenerate_response = client.post("/api/soul/generate", json={"regenerate": True})
    results.append(("POST /api/soul/generate (regenerate)", regenerate_response.status_code))
    assert regenerate_response.status_code == 200, regenerate_response.text

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    table_lines = ["| Step | Status code |", "|---|---|"]
    table_lines += [f"| {step} | {code} |" for step, code in results]
    (EVIDENCE_DIR / "health_check.md").write_text("\n".join(table_lines) + "\n", encoding="utf-8")
    (EVIDENCE_DIR / "generated_sample.html").write_text(generated_html, encoding="utf-8")
    (EVIDENCE_DIR / "extract_response.json").write_text(
        json.dumps(extract_response.json(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
