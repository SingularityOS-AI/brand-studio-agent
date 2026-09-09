"""
Brand Brain Section Definitions

Defines the nine brand sections for Bloque A — el Cerebro de Marca.

Follows spec_cerebro_9_nodos.md (CEO-signed 2026-09-09) as source of truth.
"""

from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Any
from enum import Enum


class KnowledgeLevel(Enum):
    """Knowledge triage levels for conversation targeting"""
    EXPERTO = "experto"
    ESTUDIANTE = "estudiante"


LEVEL_EXPERTO = KnowledgeLevel.EXPERTO
LEVEL_ESTUDIANTE = KnowledgeLevel.ESTUDIANTE


@dataclass
class FieldDefinition:
    """Definition of a single field within a section"""
    key: str
    label: str
    type: str
    required: bool = False


@dataclass
class SectionDefinition:
    """Complete definition of a brand brain section per spec"""
    id: str
    title: str
    description: str
    fields: List[FieldDefinition]
    is_contrastive: bool = False  # Used for two-column layout (contrarian)


# ========== NINE SECTION DEFINITIONS PER SPEC ==========

SECTIONS: List[SectionDefinition] = [
    SectionDefinition(
        id="diagnostico",
        title="Diagnóstico — Dónde estás parado",
        description="Triaje duro que gobierna todo lo que Brandy dice después. Fuente: Segués (5 etapas) + Ramiro (6 niveles) + Ralston (Banco de Credibilidad)",
        fields=[
            FieldDefinition(
                key="etapa",
                label="\U0001F512 Etapa (1-5: no ha empezado/profesional invisible/creador atascado/creador sin monetizar/referente)",
                type="string",
                required=True,  # spec §3 nodo 01: obligatorio. Es el eje del triaje duro.
            ),
            FieldDefinition(
                key="nivel_ramiro",
                label="Nivel Ramiro (1-6: invisibilidad/packaging/el puente/cuello de botella/CEO real/trascendencia)",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="sintoma_diagnostico",
                label="Síntoma observable para diagnosticar sin preguntar",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="habilidad_a_desbloquear",
                label="🔒 Habilidad a desbloquear (única cosa que importa)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="prohibicion",
                label="🔒 Prohibición (lo que tiene prohibido hacer)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="postura",
                label="🔒 Postura (experto/estudiante/hipotesis)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="justificacion_postura",
                label="Justificación de la postura (recibos)",
                type="string",
                required=False,
            ),
        ],
    ),
    SectionDefinition(
        id="brand_journey",
        title="Brand Journey — Tu destino",
        description="Framework de ingeniería inversa del fundador, no del cliente. Fuente: Ralston.",
        fields=[
            FieldDefinition(
                key="resultado_deseado",
                label="🔒 Resultado deseado (objetivo que justifica el sacrificio)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="de_que_ser_conocido",
                label="🔒 Reputación exacta necesaria",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="que_hacer",
                label="🔒 Qué tienes que HACER",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="que_aprender",
                label="🔒 Qué tienes que APRENDER",
                type="string",
                required=True,
            ),
        ],
    ),
    SectionDefinition(
        id="charco",
        title="El Charco — En qué hablas",
        description="Especialización por logros reales, no por ambición. Fuente: Ralston (Pond/Lake/Ocean) + Hormozi.",
        fields=[
            FieldDefinition(
                key="problema",
                label="🔒 Problema (síntoma donde el prospecto cae todos los días)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="nivel",
                label="🔒 Nivel (charco/lago/océano)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="logro_que_lo_respalda",
                label="🔒 Logro que lo respalda (recibo)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="costo_de_no_resolverlo",
                label="Costo de no resolverlo (dinero/tiempo/desgaste)",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="intentos_fallidos",
                label="Intentos fallidos anteriores",
                type="string",
                required=False,
            ),
        ],
    ),
    SectionDefinition(
        id="icp",
        title="ICP — A quién le mandas la factura",
        description="Comprador con poder de firma y presupuesto real. Fuente: Hormozi (100M Offers/100M Leads).",
        fields=[
            FieldDefinition(
                key="quien_decide",
                label="🔒 Quién decide (cargo exacto con poder de firma)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="tamano_empresa",
                label="Tamaño empresa (facturación/headcount/rango)",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="disparador_de_urgencia",
                label="🔒 Disparador de urgencia (qué lo hace comprar AHORA)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="poder_adquisitivo",
                label="🔒 Poder adquisitivo (presupuesto real)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="comite_de_compra",
                label="Quién más tiene que decir que sí (B2B)",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="a_quien_le_rinde_cuentas",
                label="A quién le rinde cuentas (alimenta resultado_sonado)",
                type="string",
                required=False,
            ),
        ],
    ),
    SectionDefinition(
        id="contrarian",
        title="Postura Contraria — Dos Columnas",
        description="Contrarianismo honesto que ayuda, no provocación barata. Fuente: Ralston, Método de las Dos Columnas.",
        fields=[
            FieldDefinition(
                key="creencia_comun",
                label="🔒 Creencia común (verdad aceptada del gremio)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="postura_opuesta",
                label="🔒 Postura opuesta (tu creencia alternativa)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="prueba",
                label="🔒 Prueba (evidencia de la verdad opuesta)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="por_que_no_es_provocacion",
                label="Por qué no es provocación (guardarraíl)",
                type="string",
                required=False,
            ),
        ],
        is_contrastive=True
    ),
    SectionDefinition(
        id="asociaciones",
        title="Asociaciones — Pairing",
        description="Marca como asociación mental, no como logo. Fuente: Ralston.",
        fields=[
            FieldDefinition(
                key="deseadas",
                label="🔒 Asociaciones deseadas (lista)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="prohibidas",
                label="🔒 Asociaciones prohibidas (lista)",
                type="string",
                required=True,
            ),
        ],
    ),
    SectionDefinition(
        id="identidad",
        title="Identidad — Mapa de identidad",
        description="Gobierna el empaquetado visual del render. Fuente: Matt Gray.",
        fields=[
            FieldDefinition(
                key="voz",
                label="🔒 Voz (3-5 palabras describiendo el tono)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="colores",
                label="🔒 Colores (2-4 colores)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="tipografias",
                label="🔒 Tipografías (1-2 tipografías)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="narrativa_de_origen",
                label="Narrativa de origen (historia personal)",
                type="string",
                required=False,
            ),
        ],
    ),
    SectionDefinition(
        id="oferta",
        title="Oferta — Ecuación de Valor Hormozi",
        description="Valor = (Resultado Soñado × Probabilidad Percibida) ÷ (Retraso × Esfuerzo). Fuente: Hormozi, 100M Offers.",
        fields=[
            FieldDefinition(
                key="resultado_sonado",
                label="🔒 Resultado soñado (B2B: ingresos/costos/riesgo/estatus)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="probabilidad_percibida",
                label="🔒 Probabilidad percibida (casos/testimonios/garantías)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="retraso",
                label="🔒 Retraso (tiempo hasta primer beneficio)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="esfuerzo",
                label="🔒 Esfuerzo (trabajo que queda al cliente)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="componentes",
                label="🔒 Componentes (específico: 3 emails/semana por 90 días)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="garantia",
                label="Garantía (condicional o incondicional)",
                type="string",
                required=False,
            ),
        ],
    ),
    SectionDefinition(
        id="lead_magnet",
        title="Lead Magnet — Primer paso gratis",
        description="Principio de revelación: resuelve A, revela B (oferta de pago). Fuente: Hormozi, 100M Leads.",
        fields=[
            FieldDefinition(
                key="tipo",
                label="🔒 Tipo (revelador/muestra/primer_paso)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="problema_A",
                label="🔒 Problema A (lo que resuelve gratis)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="problema_B_que_revela",
                label="🔒 Problema B que revela (enlace a oferta)",
                type="string",
                required=True,
            ),
            FieldDefinition(
                key="formato",
                label="Formato (PDF/herramienta/video/sesión)",
                type="string",
                required=False,
            ),
            FieldDefinition(
                key="captura",
                label="Captura (cómo se recogen datos)",
                type="string",
                required=False,
            ),
        ],
    ),
]

# Section ID to definition mapping
_SECTION_BY_ID: Dict[str, SectionDefinition] = {s.id: s for s in SECTIONS}


def get_section_definitions() -> List[SectionDefinition]:
    """Return all nine section definitions in order"""
    return SECTIONS.copy()


def get_section_by_id(section_id: str) -> Optional[SectionDefinition]:
    """Get a section definition by its ID"""
    return _SECTION_BY_ID.get(section_id)


def all_required_fields_gathered(section_id: str, content: Dict[str, Any]) -> bool:
    """
    Validate that all required fields (🔒) for a section are present and non-empty.

    Citation validation is handled separately by Section.__post_init__ in models.py,
    which raises CitationInvariantError if citation_text is not in transcript.
    This function only checks required fields per spec_cerebro_9_nodos.md §1(a).

    Args:
        section_id: Section ID (e.g., "diagnostico", "brand_journey")
        content: Section content dict (NOT including metadata like citation_text)

    Returns:
        True if all required fields are present and non-empty
    """
    section = get_section_by_id(section_id)
    if not section:
        return False

    # Check each required field
    for field in section.fields:
        if field.required:
            value = content.get(field.key)
            if not value or (isinstance(value, str) and not value.strip()):
                return False

    return True


def get_section_order() -> List[str]:
    """Return the canonical order of section IDs for display (01-09 per spec)"""
    return [s.id for s in SECTIONS]
