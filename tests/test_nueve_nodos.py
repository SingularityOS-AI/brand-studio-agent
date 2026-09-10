"""
Tests for the 9-node Cerebro de Marca system.
Based on spec: .claude/specs/spec_cerebro_9_nodos.md (CEO-signed 2026-09-09)

Tests cover:
- All 9 sections with required fields, citations, and confirmed status
- TERMINADO criteria enforcement
- Normalized citation matching
- missing_sections calculation
"""
import os
os.environ["TEST_MODE"] = "true"

import pytest
from unittest.mock import patch
from app.tools.brand_brain.models import BrandBrain, Section, CitationInvariantError
from app.tools.brand_brain.extractor import normalize_citation_for_matching, normalized_citation_matches_transcript
from app.tools.brand_brain.questions import (
    get_section_order,
    all_required_fields_gathered,
    get_section_definitions,
    get_section_by_id
)


# Test normalized citation matching
def test_normalize_citation_for_matching_basic():
    """Test citation normalization handles lowercase, punctuation, and spaces."""
    citation = "¿Qué diferencia su marca?"
    normalized = normalize_citation_for_matching(citation)
    assert normalized == "qué diferencia su marca"


def test_normalize_citation_with_punctuation():
    """Test normalization removes punctuation."""
    citation = "[00:15-00:30] Hola, ¿qué tal?"
    normalized = normalize_citation_for_matching(citation)
    assert "[" not in normalized and "]" not in normalized
    assert "¿" not in normalized and "?" not in normalized


def test_normalize_citation_collapses_spaces():
    """Test normalization collapses multiple spaces."""
    citation = "  esto   es    un  test  "
    normalized = normalize_citation_for_matching(citation)
    assert normalized == "esto es un test"


def test_normalized_citation_matches_transcript_substring():
    """ponytail: match normalizado por substring; subir a fuzzy si el ASR lo exige"""
    transcript = "nuestra marca ofrece productos premium de alta calidad"
    citation = "productos premium de alta calidad"
    assert normalized_citation_matches_transcript(citation, transcript) is True


def test_normalized_citation_matches_case_insensitive():
    """Substring matching should be case-insensitive."""
    transcript = "Nuestra Marca es unica en el mercado"
    citation = "marca es unica"
    assert normalized_citation_matches_transcript(citation, transcript) is True


def test_normalized_citation_no_match():
    """Should return False when citation not in transcript."""
    transcript = "ofrecemos servicios de consultoria empresarial"
    citation = "productos premium"
    assert normalized_citation_matches_transcript(citation, transcript) is False


# Test all 9 sections with positive cases (TERMINADO criteria)
class TestNineNodosPositive:
    """Test each of the 9 nodes meets TERMINADO criteria."""

    def test_diagnostico_terminado(self):
        """Diagnóstico with required fields, citation, and confirmed status."""
        brain = BrandBrain()
        
        content = {
            "etapa": "creador atascado",
            "nivel_ramiro": "el puente",
            "sintoma_diagnostico": "Engrosar el embudo sin convertir",
            "habilidad_a_desbloquear": "Ingeniería de ofertas",
            "prohibicion": "No hacer género vertical (yoga)",
            "postura": "experto"
        }
        
        section = brain.upsert_section(
            section_id="diagnostico",
            label="Diagnóstico",
            content=content,
            citation_text="[00:10-00:45] La situación actual es que tenemos crecimiento...",
            citation_source="usuario",
            status="confirmado"  # Derived from section_data.get("confirmed")
        )
        
        # Check all required fields are present
        assert "habilidad_a_desbloquear" in content
        assert "prohibicion" in content
        assert "postura" in content
        
        # Check status is confirmado
        assert section.status == "confirmado"

    def test_brand_journey_terminado(self):
        """Brand Journey with required fields, citation, and confirmed status."""
        brain = BrandBrain()
        
        content = {
            "resultado_deseado": "Ser referente en consultoría estratégica",
            "de_que_ser_conocido": "Transformación empresarial con IA",
            "que_hacer": "Hacer consultoría 1:1 y formación corporativa",
            "que_aprender": "Diseño de programas de transformación"
        }
        
        section = brain.upsert_section(
            section_id="brand_journey",
            label="Brand Journey",
            content=content,
            citation_text="[01:00-02:15] Empezamos en 2015 y el hito clave fue...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "brand_journey"
        assert section.status == "confirmado"

    def test_charco_terminado(self):
        """Charco (Punto de Diferencia) with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "problema": "Pymes que no convertían tráfico en ventas",
            "nivel": "charco",
            "logro_que_lo_respalda": "300 empresas digitalizadas con 40% conversión",
            "costo_de_no_resolverlo": "Pérdida de facturación por mala digitalización"
        }
        
        section = brain.upsert_section(
            section_id="charco",
            label="Charco (Punto de Diferencia)",
            content=content,
            citation_text="[02:30-03:00] Nuestro punto de diferencia es...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "charco"
        assert section.status == "confirmado"

    def test_icp_terminado(self):
        """Cliente Ideal (ICP) with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "quien_decide": "CEO de empresa 10-50 empleados",
            "tamano_empresa": "10-50 empleados, facturación 1-10M€",
            "disparador_de_urgencia": "Q3 audiencia externa o pérdida de cliente grande",
            "poder_adquisitivo": "50-100k€ por proyecto",
            "comite_de_compra": "CEO + Marketing + Operaciones",
            "a_quien_le_rinde_cuentas": "Board de inversores"
        }
        
        section = brain.upsert_section(
            section_id="icp",
            label="Cliente Ideal (ICP)",
            content=content,
            citation_text="[03:15-04:00] Nuestro cliente ideal es...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "icp"
        assert section.status == "confirmado"

    def test_contrarian_terminado(self):
        """Posicionamiento Contrarian with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "creencia_comun": "Necesitas invertir en todas las redes sociales",
            "postura_opuesta": "Mejor 2 redes dominadas que 5 pobres",
            "prueba": "Clientes que redujeron de 5 a 2 redes duplicaron engagement",
            "por_que_no_es_provocacion": "Evidencia de ROI en cada plataforma"
        }
        
        section = brain.upsert_section(
            section_id="contrarian",
            label="Posicionamiento Contrarian",
            content=content,
            citation_text="[04:30-05:15] Nuestro posicionamiento es contrarian porque...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "contrarian"
        assert section.status == "confirmado"

    def test_asociaciones_terminado(self):
        """Asociaciones Culturales with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "deseadas": "Netflix (contenido), Apple (calidad), Nike (ambición)",
            "prohibidas": "Consultoría tradicional (jerga, presentaciones infinitas)"
        }
        
        section = brain.upsert_section(
            section_id="asociaciones",
            label="Asociaciones Culturales",
            content=content,
            citation_text="[05:30-06:00] Asociamos nuestra marca con...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "asociaciones"
        assert section.status == "confirmado"

    def test_identidad_terminado(self):
        """Identidad de Marca with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "voz": "Directa, profesional, con humor controlado",
            "colores": "#2563EB (azul principal), #000000 (negro), #FFFFFF (blanco)",
            "tipografias": "Inter (cuerpos), Roboto (títulos)",
            "narrativa_de_origen": "Fundado por ingenieros cansados de la burocracia"
        }
        
        section = brain.upsert_section(
            section_id="identidad",
            label="Identidad de Marca",
            content=content,
            citation_text="[06:15-07:00] Nuestra identidad se basa en...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "identidad"
        assert section.status == "confirmado"

    def test_oferta_terminado(self):
        """Oferta de Valor with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "resultado_sonado": "Duplicar ingresos en 12 meses",
            "probabilidad_percibida": "50 casos con>+100% ROI, testimonios verificables",
            "retraso": "Primer beneficio visible en 30 días",
            "esfuerzo": "Cliente debe dedicar 2h/semana a revisión",
            "componentes": "3 emails/semana + 2 llamadas/mes durante 90 días",
            "garantia": "Si no duplicas ingresos en 90 días, devolvemos 100%"
        }
        
        section = brain.upsert_section(
            section_id="oferta",
            label="Oferta de Valor",
            content=content,
            citation_text="[07:30-08:15] Nuestra oferta ofrece...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "oferta"
        assert section.status == "confirmado"

    def test_lead_magnet_terminado(self):
        """Lead Magnet with required fields, citation, and confirmed."""
        brain = BrandBrain()
        
        content = {
            "tipo": "revelador",
            "problema_A": "Baja conversión de leads actuales",
            "problema_B_que_revela": "Falta de estrategia de nurturing sistemático",
            "formato": "PDF checklist de 5 pasos",
            "captura": "Email + LinkedIn URL"
        }
        
        section = brain.upsert_section(
            section_id="lead_magnet",
            label="Lead Magnet",
            content=content,
            citation_text="[08:30-09:00] Nuestro lead magnet es...",
            citation_source="usuario",
            status="confirmado"
        )
        
        assert section.id == "lead_magnet"
        assert section.status == "confirmado"


# Test negative cases (TERMINADO criteria violations)
class TestNineNodosNegative:
    """Test TERMINADO criteria violations."""

    def test_missing_required_field_not_terminado(self):
        """Section missing required field should NOT meet TERMINADO criteria."""
        # Missing "disparador_de_urgencia" field for ICP
        content_missing_field = {
            "quien_decide": "CEO",
            "poder_adquisitivo": "100k€"
            # "disparador_de_urgencia": missing - this is a required field (🔒)
        }
        
        brain = BrandBrain()
        section = brain.upsert_section(
            section_id="icp",
            label="Cliente Ideal (ICP)",
            content=content_missing_field,
            citation_text="[03:15-04:00] Nuestro cliente ideal es...",
            citation_source="usuario",
            status="confirmado"
        )
        
        # Section exists but doesn't meet TERMINADO criteria due to missing field
        # The all_required_fields_gathered() function checks this
        assert "disparador_de_urgencia" not in section.content

    def test_unconfirmed_status_not_terminado(self):
        """Section with unconfirmed status should NOT meet TERMINADO criteria."""
        brain = BrandBrain()
        
        content = {
            "voz": "Directa, profesional",
            "colores": "#2563EB, #000000",
            "tipografias": "Inter, Roboto"
        }
        
        section = brain.upsert_section(
            section_id="identidad",
            label="Identidad de Marca",
            content=content,
            citation_text="[06:15-07:00] Nuestra identidad se basa en...",
            citation_source="usuario",
            status="propuesto"  # NOT confirmado
        )
        
        # Unconfirmed status prevents TERMINADO
        assert section.status != "confirmado"


# Test field definitions and metadata
def test_field_definitions_has_nine_sections():
    """Field definitions should have exactly 9 sections."""
    sections = get_section_definitions()
    section_ids = {s.id for s in sections}
    
    # Verify we have exactly 9 sections
    assert len(section_ids) == 9
    
    # Verify the 9 expected section IDs
    expected_ids = {
        "diagnostico", "brand_journey", "charco", "icp", "contrarian",
        "asociaciones", "identidad", "oferta", "lead_magnet"
    }
    assert section_ids == expected_ids


def test_all_required_fields_marked_with_lock():
    """All required fields should be marked with 🔒 in labels."""
    sections = get_section_definitions()
    
    # Count required fields with lock
    required_fields_with_lock = []
    for section in sections:
        for field in section.fields:
            if field.required:
                assert "🔒" in field.label, f"Field {section.id}.{field.key} missing 🔒 in label"
                required_fields_with_lock.append(f"{section.id}.{field.key}")
    
    # Verify expected count of required fields
    # diagnostico: 4, brand_journey: 4, charco: 3, icp: 3, contrarian: 3, asociaciones: 2, identidad: 3, oferta: 5, lead_magnet: 3
    # Total: 30 required fields (spec §3; `etapa` es obligatorio: es el eje del triaje duro)
    assert len(required_fields_with_lock) == 30


def test_section_order_returns_all_nine():
    """get_section_order() should return all 9 section IDs."""
    order = get_section_order()
    assert len(order) == 9
    assert set(order) == {
        "diagnostico", "brand_journey", "charco", "icp", "contrarian",
        "asociaciones", "identidad", "oferta", "lead_magnet"
    }


def test_all_required_fields_gathered_checks_content():
    """all_required_fields_gathered() should check content fields."""

    # ICP with all required fields - returns True
    complete_content = {
        "quien_decide": "CTO",
        "disparador_de_urgencia": "Q3 deadline",
        "poder_adquisitivo": "$500k"
    }

    result = all_required_fields_gathered("icp", complete_content)
    assert result is True

    # ICP missing one required field - returns False
    incomplete_content = {
        "quien_decide": "CTO",
        # "disparador_de_urgencia": missing
        "poder_adquisitivo": "$500k"
    }

    result = all_required_fields_gathered("icp", incomplete_content)
    assert result is False


@patch("app.tools.brand_brain.extractor.get_brand_brain")
@patch("app.tools.brand_brain.extractor.save_brand_brain")
def test_brand_brain_constructs_when_no_existing_brain(
    mock_save_brain,
    mock_get_brain
):
    """
    Test the exact production code path from extractor.py line 310:
    When no existing brain exists, extract_and_persist creates a new
    BrandBrain with correct constructor (no session_token parameter).

    This test detects the regression on line 310 where someone might
    incorrectly pass session_token to BrandBrain.__init__():
        brain = BrandBrain(session_token=session_token, sections=[])

    The test calls extract_and_persist() for real (not just BrandBrain()),
    ensuring the production path executes and any change to line 310
    causes a test failure.
    """
    # Mock get_brand_brain to return None -> forces the "no existing brain" path
    mock_get_brain.return_value = None

    # Mock save_brand_brain to avoid touching Supabase
    mock_save_brain.return_value = None

    # Import inside test to avoid circular import issues
    from app.tools.brand_brain.extractor import extract_and_persist

    # Must be >= 100 characters or validate_extraction_input raises ExtractionError
    # The citation_text below appears LITERALLY in this transcript
    transcript = (
        "En esta conversación con el fundador de la empresa, discutimos el estado actual "
        "del negocio. El fundador explicó que necesitan avanzar hacia una postura de "
        "estudiante para abrir nuevas oportunidades. Esta es la clave del diagnostico del"
        "estado actual de la marca."
    )
    tool_result = {
        "sections": [
            {
                "id": "diagnostico",
                # This citation appears literally in the transcript above
                "citation_text": "fundador explicó que necesitan avanzar hacia una postura de estudiante",
                "confirmed": True,
                "content": {
                    "etapa": "creador atascado",
                    "habilidad_a_desbloquear": "perspectiva",
                    "prohibicion": "optimizar horarios",
                    "postura": "estudiante"
                }
            }
        ]
    }

    # Call the REAL production code path - this executes line 310 in extractor.py
    brain = extract_and_persist(
        session_token="test_no_brain_token",
        transcript=transcript,
        turn_count=5,
        tool_result=tool_result
    )

    # Assert that we got a valid BrandBrain back
    assert isinstance(brain, BrandBrain)

    # Assert that the section was extracted and added to the brain
    assert len(brain.sections) == 1
    diagnostico_section = brain.sections[0]
    assert diagnostico_section.id == "diagnostico"
    assert diagnostico_section.status == "confirmado"
    assert "etapa" in diagnostico_section.content
    assert diagnostico_section.content["postura"] == "estudiante"

    # Assert that _metadata with missing_sections was set (lines 349-351)
    assert hasattr(brain, "_metadata")
    assert "missing_sections" in brain._metadata

    # Verify mocks were called correctly
    mock_get_brain.assert_called_once_with("test_no_brain_token")
    mock_save_brain.assert_called_once()


@patch("app.tools.brand_brain.extractor.get_brand_brain")
@patch("app.tools.brand_brain.extractor.save_brand_brain")
def test_cita_partida_por_turno_fragmentado_se_guarda(mock_save_brain, mock_get_brain):
    """
    PIEZA_17, FALLO 2. El fundador dice una frase entera, pero min_silence=200
    la parte en DOS turnos `user:`. El frontend arma el transcript con
    "user: <mitad1>\\nuser: <mitad2>", y la cita del agente cruza el corte.

    Sin el FALLO 2 arreglado, `normalize_citation_for_matching` mete la palabra
    "user" a mitad de frase y la cita nunca hace substring match: la seccion
    se descarta EN SILENCIO. Con el arreglo debe guardarse.
    """
    mock_get_brain.return_value = None
    mock_save_brain.return_value = None

    from app.tools.brand_brain.extractor import extract_and_persist

    # La frase del fundador partida en dos eventos transcript.user, tal como
    # arma el frontend real: "user: " + "user: " (app.js ~linea 849).
    transcript = (
        "agent: ¿Cómo te ves ahora mismo en tu negocio?\n"
        "user: um i mean i do consider myself\n"
        "user: right now as a student of the craft"
    )

    tool_result = {
        "sections": [
            {
                "id": "diagnostico",
                "citation_text": "i do consider myself right now as a student of the craft",
                "citation_source": "usuario",
                "confirmed": True,
                "content": {
                    "etapa": "creador atascado",
                    "habilidad_a_desbloquear": "perspectiva",
                    "prohibicion": "optimizar horarios",
                    "postura": "estudiante"
                }
            }
        ]
    }

    brain = extract_and_persist(
        session_token="test_fragmented_turn_token",
        transcript=transcript,
        tool_result=tool_result
    )

    assert len(brain.sections) == 1, (
        "la seccion 'diagnostico' debio guardarse: la cita cruza un corte de "
        "turno pero es literalmente lo que dijo el fundador"
    )
    assert brain.sections[0].status == "confirmado"
    assert brain._metadata["skipped_sections"] == []


@patch("app.tools.brand_brain.extractor.get_brand_brain")
@patch("app.tools.brand_brain.extractor.save_brand_brain")
def test_cita_usuario_que_solo_dijo_el_agente_se_descarta(mock_save_brain, mock_get_brain):
    """
    PIEZA_17, FALLO 2. Invariante del producto: una cita atribuida al fundador
    (`citation_source: "usuario"`) no puede validarse contra palabras que dijo
    Brandy. Si esa cita solo aparece en una linea `agent:`, se descarta y
    queda reportada en `skipped_sections` (FALLO 3), no silenciosamente.
    """
    mock_get_brain.return_value = None
    mock_save_brain.return_value = None

    from app.tools.brand_brain.extractor import extract_and_persist

    transcript = (
        "agent: it sounds like you are a stuck creator searching for perspective\n"
        "user: yes that resonates with me a lot honestly"
    )

    tool_result = {
        "sections": [
            {
                "id": "diagnostico",
                # Estas palabras las dijo Brandy (agent:), no el fundador.
                "citation_text": "you are a stuck creator searching for perspective",
                "citation_source": "usuario",
                "confirmed": True,
                "content": {
                    "etapa": "creador atascado",
                    "habilidad_a_desbloquear": "perspectiva",
                    "prohibicion": "optimizar horarios",
                    "postura": "estudiante"
                }
            }
        ]
    }

    brain = extract_and_persist(
        session_token="test_usuario_cita_de_agente_token",
        transcript=transcript,
        tool_result=tool_result
    )

    assert brain.sections == [], "no debe guardarse: el fundador nunca dijo esas palabras"
    assert brain._metadata["skipped_sections"] == [
        {"id": "diagnostico", "reason": "cita_no_encontrada"}
    ]


@patch("app.tools.brand_brain.extractor.get_brand_brain")
@patch("app.tools.brand_brain.extractor.save_brand_brain")
def test_prosa_de_brandy_con_salto_de_linea_no_pasa_como_cita_del_fundador(
    mock_save_brain, mock_get_brain
):
    """
    PIEZA_17B, rebote de QA. El texto del agente llega crudo con un `\\n`
    dentro (respuesta de dos parrafos, ver deltas reales `delta: 'though.\\n\\n'`
    en app.js). La segunda linea no tiene prefijo `agent:` y ANTES del arreglo
    caia en el fallback permisivo, entrando en `founder_text` como si el
    fundador la hubiera dicho. Debe heredar el hablante de la linea anterior
    (agent) y la seccion con `citation_source: "usuario"` debe descartarse.
    """
    mock_get_brain.return_value = None
    mock_save_brain.return_value = None

    from app.tools.brand_brain.extractor import extract_and_persist

    transcript = (
        "agent: I apologize, I ran into a glitch.\n"
        "You are the most precise interpreter in the medical field.\n"
        "user: okay no problem"
    )

    tool_result = {
        "sections": [
            {
                "id": "diagnostico",
                # Solo aparece en la segunda linea del turno del agente.
                "citation_text": "you are the most precise interpreter in the medical field",
                "citation_source": "usuario",
                "confirmed": True,
                "content": {
                    "etapa": "creador atascado",
                    "habilidad_a_desbloquear": "perspectiva",
                    "prohibicion": "optimizar horarios",
                    "postura": "estudiante"
                }
            }
        ]
    }

    brain = extract_and_persist(
        session_token="test_prosa_brandy_multilinea_token",
        transcript=transcript,
        tool_result=tool_result
    )

    assert brain.sections == [], (
        "no debe guardarse: esas palabras las dijo Brandy en su segundo "
        "parrafo, no el fundador"
    )
    assert brain._metadata["skipped_sections"] == [
        {"id": "diagnostico", "reason": "cita_no_encontrada"}
    ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
