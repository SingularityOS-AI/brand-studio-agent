"""
Pieza 21 — El Brand Soul se cobra 20 creditos en total, no 70.

app/main.py:358 ya descuenta 20 creditos por generacion
(`guard.deduct_credits(session_token, amount=20)`). generator.py NO debe
cobrar un segundo descuento (el bug historico: `estimated_credits = 50`,
que sumaba un total de 70 — el 14% de la asignacion gratuita por un
documento cuyo costo real de LLM es 0,03 creditos).

Este test replica exactamente la secuencia de main.py (deduct 20, luego
generate_brand_soul) sin pasar por la capa HTTP/JWT, y fuerza TEST_MODE a
"false" durante la llamada a generate_brand_soul: el bug viejo vivia dentro
de un guard `if os.getenv("TEST_MODE") != "true"` que lo hacia invisible
bajo TEST_MODE=true (el default de toda la suite via tests/conftest.py).
Sin forzar ese entorno, este test pasaria en verde incluso con el bug
presente — que es justo como se coló las primeras tres veces.
"""

import pytest
from unittest.mock import patch

from app.tools.brand_brain.models import BrandBrain, Section
from app.guard import guard
from app.tools.brand_soul.generator import generate_brand_soul


@pytest.fixture
def complete_brain():
    """Brand brain minima con las 9 secciones confirmadas."""
    brain = BrandBrain()
    sections_data = [
        {"id": "diagnostico", "label": "Diagnostico", "content": {
            "etapa": "momentum", "sintoma_diagnostico": "X",
            "habilidad_a_desbloquear": "Y", "prohibicion": "Z", "postura": "experto"
        }, "citation_text": "Cita diagnostico", "citation_source": "usuario", "status": "confirmado"},
        {"id": "brand_journey", "label": "Brand Journey", "content": {
            "resultado_deseado": "X", "de_que_ser_conocido": "Y",
            "que_hacer": "Z", "que_aprender": "W"
        }, "citation_text": "Cita journey", "citation_source": "usuario", "status": "confirmado"},
        {"id": "charco", "label": "Charco", "content": {
            "problema": "Dolor", "nivel": "charco", "logro_que_lo_respalda": "Logro"
        }, "citation_text": "Cita charco", "citation_source": "usuario", "status": "confirmado"},
        {"id": "icp", "label": "ICP", "content": {
            "quien_decide": "CEO", "disparador_de_urgencia": "Q4", "poder_adquisitivo": "50k"
        }, "citation_text": "Cita icp", "citation_source": "usuario", "status": "confirmado"},
        {"id": "contrarian", "label": "Postura Contraria", "content": {
            "creencia_comun": "A", "postura_opuesta": "B", "prueba": "C"
        }, "citation_text": "Cita contrarian", "citation_source": "usuario", "status": "confirmado"},
        {"id": "asociaciones", "label": "Asociaciones", "content": {
            "deseadas": ["a"], "prohibidas": ["b"]
        }, "citation_text": "Cita asociaciones", "citation_source": "usuario", "status": "confirmado"},
        {"id": "identidad", "label": "Identidad", "content": {
            "voz": "X", "colores": "#FFF", "tipografias": "Y"
        }, "citation_text": "Cita identidad", "citation_source": "usuario", "status": "confirmado"},
        {"id": "oferta", "label": "Oferta", "content": {
            "resultado_sonado": "X", "probabilidad_percibida": "Y",
            "retraso": "Z", "esfuerzo": "W", "componentes": "V"
        }, "citation_text": "Cita oferta", "citation_source": "usuario", "status": "confirmado"},
        {"id": "lead_magnet", "label": "Lead Magnet", "content": {
            "tipo": "X", "problema_A": "Y", "problema_B_que_revela": "Z"
        }, "citation_text": "Cita lead magnet", "citation_source": "usuario", "status": "confirmado"},
    ]
    for section_data in sections_data:
        brain.sections.append(Section(**section_data))
    return brain


@patch("app.tools.brand_soul.generator._redact_section_content_with_llm")
@patch("app.tools.brand_soul.generator._save_cache")
@patch("app.tools.brand_soul.generator._check_cache")
@patch("app.tools.brand_soul.generator.get_brand_brain")
def test_brand_soul_generation_costs_exactly_20_credits_total(
    mock_get_brain, mock_check_cache, mock_save_cache, mock_redact,
    complete_brain, monkeypatch
):
    """
    Given a session with 100 credits and a complete brand brain,
    When the same sequence main.py's /api/soul/generate runs
    (deduct 20, then generate_brand_soul) is executed,
    Then exactly 20 credits are deducted in total (100 -> 80) — not 70.
    """
    mock_get_brain.return_value = complete_brain

    def fake_redact(section, all_citations):
        # citation must be the section's real citation_text or validate_citations_in_html
        # flags it as invented and refuses to return the document.
        return ({"content": "x", "citation": section.citation_text, "voice": "x",
                 "associations_desired": "x", "associations_prohibited": "x",
                 "knowledge_level": "x", "implication": "x",
                 "common_belief": "x", "contrarian_position": "x",
                 "equation": "x", "text": "x", "stages": "x"}, 10)

    mock_check_cache.return_value = None
    mock_save_cache.return_value = True
    mock_redact.side_effect = fake_redact

    session_token = guard.create_user_session("test_credit_cost_user", initial_credits=100)

    # main.py step 3: deduct 20 credits before generating.
    remaining = guard.deduct_credits(session_token, amount=20)
    assert remaining == 80

    # main.py step 4: generate the document. TEST_MODE forced to "false" here
    # reproduces the environment where the old ghost charge actually fired.
    monkeypatch.setenv("TEST_MODE", "false")
    try:
        html, cache_status = generate_brand_soul(session_token)
    finally:
        monkeypatch.setenv("TEST_MODE", "true")

    assert html is not None
    assert cache_status == "generated"

    final_credits = guard.get_session(session_token)["credits"]
    assert final_credits == 80, (
        f"Expected 100 - 20 = 80 credits remaining, got {final_credits}. "
        "If this is 30, the generator's ghost 50-credit charge is back."
    )
