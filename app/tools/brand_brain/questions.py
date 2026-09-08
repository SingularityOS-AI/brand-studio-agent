"""
Brand Brain Section Definitions

Defines the nine brand sections for Bloque A — el Cerebro de Marca.

Each section includes:
- id: unique identifier (used in database and UI)
- label: display name for the section
- description: what this section captures
- deducible_requirements: what the agent must know to deduce this
- validation_rules: how to validate extracted content
"""

from dataclasses import dataclass
from typing import List, Dict, Set, Optional
from enum import Enum


class KnowledgeLevel(Enum):
    """Knowledge triage levels for conversation targeting"""
    EXPERTO = "experto"
    ESTUDIANTE = "estudiante"


LEVEL_EXPERTO = KnowledgeLevel.EXPERTO
LEVEL_ESTUDIANTE = KnowledgeLevel.ESTUDIANTE


@dataclass
class DeductionRequirement:
    """What evidence the agent needs to deductively infer a section"""
    section_id: str
    결_필요한_evidence: List[str]  # The specific signals in user's speech


@dataclass
class SectionDefinition:
    """Complete definition of a brand brain section"""
    id: str
    label: str
    description: str
    deducible_requirements: List[str]
    validation_rules: List[str]
    is_contrastive: bool = False  # Some sections need two-column contrast layout


# ========== NINE SECTION DEFINITIONS ==========

SECTIONS: List[SectionDefinition] = [
    SectionDefinition(
        id="brand_journey",
        label="Viaje del Cliente (Ralston)",
        description="Las 5 etapas por las que pasa tu cliente desde 'no tengo problema' hasta 'compro ahora'",
        deducible_requirements=[
            "Qué problema resuelves para el cliente",
            "El estado actual del cliente antes de tu solución",
            "Cómo se entera de soluciones como la tuya",
            "Por qué dudarían de soluciones como la tuya",
            "Qué causa finalmente la decisión de compra"
        ],
        validation_rules=[
            "Debe describir las 5 etapas: unaware, problem_aware, solution_aware, product_aware, most_aware",
            "Debe incluir la etapa actual donde está tu audiencia target"
        ]
    ),
    SectionDefinition(
        id="etapa",
        label="Etapa del Negocio (Segués)",
        description="En qué fase está tu negocio hoy según el modelo de Segués",
        deducible_requirements=[
            "Cuánto tiempo llevas operando",
            "Cuántos clientes tienes o has tenido",
            "Si tienes ingresos recurrentes",
            "Si tienes equipo o eres solo",
            "Cuáles son tus prioridades principales"
        ],
        validation_rules=[
            "Debe identificar una etapa: seed, startup, growth, expansion, maturity",
            "Debe incluir rango de ingresos si está disponible"
        ]
    ),
    SectionDefinition(
        id="charco",
        label="El Charco del Dolor",
        description="El problema específico y urgente que tu cliente necesita resolver YA",
        deducible_requirements=[
            "El síntoma visible que experimenta el cliente",
            "La frecuencia o urgencia del problema",
            "Las consecuencias de no resolverlo",
            "Qué ha intentado antes que no funcionó"
        ],
        validation_rules=[
            "Debe describir el problema en términos visibles para el cliente",
            "No debe describir tu solución (eso es para otra sección)"
        ]
    ),
    SectionDefinition(
        id="credibilidad",
        label="Credibilidad del Problema",
        description="Por qué este problema es REAL, no inventado — evidencia de que existe",
        deducible_requirements=[
            "Datos, estadísticas o evidencia del problema",
            "Referencias a estudios o reportajes",
            "Ejemplos de personas que lo viven",
            "Comentarios de clientes sobre el problema"
        ],
        validation_rules=[
            "Debe incluir evidencia específica (no puramente anécdota)",
            "Debe citar fuentes cuando posible (usuario o análisis público)"
        ]
    ),
    SectionDefinition(
        id="contrarian",
        label="Punto Contrarian",
        description="Lo que TODO el mundo en tu industria dice, pero tú crees lo opuesto",
        deducible_requirements=[
            "Qué creencia común domina tu industria",
            "Por qué esa creencia está equivocada",
            "Qué prueba tienes de la verdad opuesta",
            "Cómo esa diferencia te hace único"
        ],
        validation_rules=[
            "Debe identificar claramente la creencia común",
            "Debe posicionarse en contra (oposición clara)",
            "Layout de dos columnas: creencia común vs tu opuesto"
        ],
        is_contrastive=True
    ),
    SectionDefinition(
        id="asociaciones",
        label="Asociaciones Mentales",
        description="Qué viene a la mente de tu cliente cuando piensa en tu categoría",
        deducible_requirements=[
            "Qué marcas compiten en tu espacio",
            "Qué adjetivos describen tu categoría",
            "Qué expectativas tienen los clientes de soluciones como la tuya",
            "Dónde te ubicas en el mapa mental"
        ],
        validation_rules=[
            "Debe incluir ejemplos específicos de marcas o conceptos",
            "Debe reflejar la perspectiva del cliente, no del dueño"
        ]
    ),
    SectionDefinition(
        id="identidad",
        label="Identidad de Marca",
        description="Quién eres y qué valoras como marca — tu raison d'être",
        deducible_requirements=[
            "Qué principios guían tus decisiones",
            "Qué valores que no sacrificarías nunca",
            "Cómo quieres que te perciban",
            "Qué tipo de relación buscas con clientes"
        ],
        validation_rules=[
            "Debe ser interno (quién eres), no externo (qué vendes)",
            "Debe sentirse auténtico a la voz del dueño"
        ]
    ),
    SectionDefinition(
        id="oferta",
        label="Oferta Irresistible",
        description="Qué entregas exactamente, cómo y con qué garantías",
        deducible_requirements=[
            "Qué componentes incluyes en tu oferta",
            "Resultado final que garantizas",
            "Formato de entrega (digital, físico, híbrido)",
            "Garantías o de riesgo inverso"
        ],
        validation_rules=[
            "Debe ser específico (no 'servicios de marketing' sino '3 Emails por semana por 90 días')",
            "Debe incluir el formato de entrega"
        ]
    ),
    SectionDefinition(
        id="lead_magnet",
        label="Lead Magnet",
        description="El primer paso gratis que convierte extraños en leads",
        deducible_requirements=[
            "Qué das gratis que resuelve un problema real",
            "Qué formato (PDF, video, curso, checklist, herramienta)",
            "Qué resultado específico logra",
            "Cómo el usuario lo obtiene"
        ],
        validation_rules=[
            "Debe ser gratis (sin pago)",
            "Debe entregar valor independiente de la oferta completa",
            "Debe pedir algo a cambio (email, teléfono, registro)"
        ]
    )
]

# Section ID to definition mapping
_SECTION_BY_ID: Dict[str, SectionDefinition] = {s.id: s for s in SECTIONS}


def get_section_definitions() -> List[SectionDefinition]:
    """Return all nine section definitions in order"""
    return SECTIONS.copy()


def get_section_by_id(section_id: str) -> Optional[SectionDefinition]:
    """Get a section definition by its ID"""
    return _SECTION_BY_ID.get(section_id)


def can_deduce_content(section_id: str, user_trust_buffer: List[str]) -> Dict[str, any]:
    """
    Evaluate if the agent has enough context to deductively infer a section.

    Args:
        section_id: The section to evaluate
        user_trust_buffer: List of user speech segments from the conversation

    Returns:
        Dict with keys:
        - can_deduce: bool
        - missing_evidence: List[str] of what's still needed
        - confidence_score: float 0-1
    """
    section = get_section_by_id(section_id)
    if not section:
        return {"can_deduce": False, "missing_evidence": [], "confidence_score": 0}

    # Join all user speech into one string for analysis
    full_transcript = " ".join(user_trust_buffer).lower()

    missing_evidence = []
    evidence_found = []

    # Check each required evidence item
    for requirement in section.deducible_requirements:
        # Simple heuristic: does the requirement appear in user speech?
        # For production, this would use semantic search or embedding similarity
        has_evidence = False
        for user_utterance in user_trust_buffer:
            # Check if requirement keywords appear in utterance
            req_keywords = requirement.lower().split()[:3]  # First 3 keywords
            if any(kw in user_utterance.lower() for kw in req_keywords):
                has_evidence = True
                evidence_found.append(requirement)
                break

        if not has_evidence:
            missing_evidence.append(requirement)

    # Calculate confidence based on evidence found
    total_requirements = len(section.deducible_requirements)
    found_count = len(evidence_found)
    confidence_score = found_count / total_requirements if total_requirements > 0 else 0

    # Can deduce only if we have strong evidence (at least 60%)
    can_deduce = confidence_score >= 0.6 and len(missing_evidence) <= 1

    return {
        "can_deduce": can_deduce,
        "missing_evidence": missing_evidence,
        "confidence_score": confidence_score
    }


def triage_knowledge_level(user_trust_buffer: List[str]) -> KnowledgeLevel:
    """
    Determine if the user is 'experto' (has clear business understanding) or 'estudiante'
    (early-stage, vague, still exploring). Used to calibrate conversation depth.

    Experto indicators:
    - Speaks in concrete metrics (revenue, customers, conversion rates)
    - Uses industry terminology correctly
    - Has clear positioning
    - References specific business problems

    Estudiante indicators:
    - Vague about business stage
    - Unsure about target customer
    - Exploring multiple directions
    - Few concrete metrics
    """
    full_transcript = " ".join(user_trust_buffer).lower()

    experto_signals = [
        "revenue", "ingresos", "clientes", "conversión",
        "margen", "caco", "cac", "lifetime", "ltv", "churn",
        "usd", "eur", "precio", "tasa", "porcentaje", "%"
    ]

    estudiante_signals = [
        "no sé", "no se", "quizás", "quizas", "a lo mejor",
        "pensando", "estoy considerando", "todavía no", "todavia no",
        "aún no tengo", "aun no tengo", "todavía estoy", "todavia estoy",
        "explorando", "quizá", "quizas", "tal vez", "talvez", "no estoy seguro"
    ]

    # Count signals
    experto_count = sum(1 for signal in experto_signals if signal in full_transcript)
    estudiante_count = sum(1 for signal in estudiante_signals if signal in full_transcript)

    # Simple heuristic
    if estudiante_count >= experto_count:
        return LEVEL_ESTUDIANTE
    return LEVEL_EXPERTO


def all_required_fields_gathered(section_id: str, extracted_content: Dict) -> bool:
    """
    Validate that all required fields for a section are present and non-empty.

    This enforces the core invariant: no Section without citation_text.
    """
    section = get_section_by_id(section_id)
    if not section:
        return False

    # Citation text is ALWAYS required across all sections
    if "citation_text" not in extracted_content or not extracted_content["citation_text"]:
        return False

    # Citation source must be valid
    citation_source = extracted_content.get("citation_source")
    if citation_source not in ["usuario", "analisis_publico"]:
        return False

    # Section-specific validation
    if section_id == "brand_journey":
        required = [
            "stage_1_unaware", "stage_2_problem_aware", "stage_3_solution_aware",
            "stage_4_product_aware", "stage_5_most_aware", "current_stage"
        ]
        return all(field in extracted_content and extracted_content[field] for field in required)

    elif section_id == "etapa":
        return "stage" in extracted_content and extracted_content["stage"]

    elif section_id == "charco":
        return "pain_point" in extracted_content and extracted_content["pain_point"]

    elif section_id == "credibilidad":
        return "evidence" in extracted_content and extracted_content["evidence"]

    elif section_id == "contrarian":
        # Needs both common belief and contrarian position
        has_common = "common_belief" in extracted_content and extracted_content["common_belief"]
        has_counter = "contrarian_position" in extracted_content and extracted_content["contrarian_position"]
        return has_common and has_counter

    elif section_id == "asociaciones":
        return "associations" in extracted_content and extracted_content["associations"]

    elif section_id == "identidad":
        return "values" in extracted_content and extracted_content["values"]

    elif section_id == "oferta":
        return "offer_components" in extracted_content and extracted_content["offer_components"]

    elif section_id == "lead_magnet":
        required = ["format", "what_they_get", "value_delivered"]
        return all(field in extracted_content and extracted_content[field] for field in required)

    return True


def get_section_order() -> List[str]:
    """Return the canonical order of section IDs for display"""
    return [s.id for s in SECTIONS]
