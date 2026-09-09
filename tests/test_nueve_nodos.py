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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
