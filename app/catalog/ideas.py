"""
Catálogo de Ideas (Pieza 26) - Motor de Ideas del Catálogo

Reemplaza el esquema de "3 categorías del fundador" con 5 CATEGORÍAS MAESTRAS FIJAS.
Genera 30 ideas crudas para un mes, validadas contra demanda real de mercado
(Google Trends, comentarios de YouTube, búsqueda web con grounding).

Cada idea incluye:
- master_category: una de las 5 categorías maestras fijas
- subcategory: formato específico dentro de la categoría
- title: título de la idea (sin guion)
- demand_signal: señal citable de demanda real (de NicheResearch)
- status: "pending" | "approved" | "rejected"

Elimina el campo emotional_angle (Útil/Inmersivo/Reflexivo/Vulnerable)
- el tono pertenece al guion, no a la idea cruda.
"""
from __future__ import annotations

import os
import time
import json
import hashlib
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, List, Dict, Any
from collections import Counter
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator

from app.tools.brand_brain.models import BrandBrain
from app.tools.brand_brain.store import get_brand_brain
from app.catalog.demand import (
    research_niche,
    NicheResearch
)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class IncompleteBrainError(Exception):
    """Excepción levantada cuando el BrandBrain no está completo (no todas las secciones requeridas en estado confirmado)."""
    pass


class NicheReportNotFoundError(Exception):
    """Excepción levantada cuando no existe un NicheResearch para la sesión actual."""
    pass


# =============================================================================
# CONSTANTES
# =============================================================================

# 5 Categorías Maestras Fijas (de SPEC §3)
# Source: Reporte NotebookLM — Taxonomía de Ideación B2B (2026-09-12)
MASTER_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "autoridad_tecnica",
        "name": "Autoridad Técnica e Instrucción",
        "percentage": 40,
        "subcategories": [
            "Top N/Listículo técnico",
            "Anatomía de un proceso",
            "Dato contraintuitivo con fuente"
        ]
    },
    {
        "id": "validacion_resultados",
        "name": "Validación de Resultados e Impacto",
        "percentage": 30,
        "subcategories": [
            "Antes/Después con métricas",
            "Desglose de caso de éxito",
            "Costo de la inacción"
        ]
    },
    {
        "id": "posicionamiento_narrativa",
        "name": "Posicionamiento y Tesis de Mercado",
        "percentage": 20,
        "subcategories": [
            "Mito vs Realidad",
            "Tesis Contrarian",
            "Structured Yapping"
        ]
    },
    {
        "id": "narrativa_fundadora",
        "name": "Narrativa Fundadora y Origen",
        "percentage": 0,  # Cuenta dentro del 20% de posicionamiento_narrativa
        "subcategories": [
            "Historia personal con lección",
            "Vulnerabilidad operativa",
            "Detrás de cámaras"
        ]
    },
    {
        "id": "discusion_industria",
        "name": "Discusión y Co-creación de Industria",
        "percentage": 10,
        "subcategories": [
            "Pregunta de debate",
            "Reacción a regulación/tendencia"
        ]
    }
]

# Total ideas a generar
TOTAL_IDEAS = 30

# Distribución ideales (40%, 30%, 20%, 10% + narrativa_fundadora incluida en posicionamiento)
IDEA_DISTRIBUTION = {
    "autoridad_tecnica": 12,   # 40% de 30
    "validacion_resultados": 9, # 30% de 30
    "posicionamiento_narrativa": 6, # 20% de 30 (incluye narrativa_fundadora)
    "discusion_industria": 3    # 10% de 30
}

# Cache TTL para evitar regenerar el catálogo cada vez
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 horas

# COSTO EN CRÉDITOS (entro en la pieza, de momento sin touched)
CREDITS_COST = 15


# =============================================================================
# MODELOS DE DATOS
# =============================================================================

import uuid

class CatalogIdea(BaseModel):
    """
    Idea cruda de contenido para el catálogo.

    No tiene guion ni tono emocional — solo el concepto + señal de demanda.
    """
    id: str = Field(
        default_factory=lambda: f"idea_{uuid.uuid4().hex[:8]}",
        description="ID único de la idea"
    )
    master_category: str = Field(
        ...,
        description="ID de categoría maestra (una de las 5 fijas)"
    )
    subcategory: str = Field(
        ...,
        description="Formato específico dentro de la categoría"
    )
    title: str = Field(
        ...,
        description="Título de la idea (sin guion)",
        min_length=5,
        max_length=200
    )
    demand_signal: str = Field(
        ...,
        description="Señal citable de demanda real (de NicheResearch)",
        min_length=10
    )
    status: Literal["pending", "approved", "rejected"] = Field(
        default="pending",
        description="Estado de aprobación del fundador"
    )

    @field_validator("master_category")
    @classmethod
    def validate_master_category(cls, v: str) -> str:
        valid_ids = [cat["id"] for cat in MASTER_CATEGORIES]
        if v not in valid_ids:
            raise ValueError(
                f"Categoría inválida: {v}. Debe ser una de {valid_ids}"
            )
        return v


class Catalog(BaseModel):
    """
    Catálogo de 30 ideas generado para un nicho específico.
    """
    session_id: str = Field(..., description="ID de sesión único")
    niche: str = Field(..., description="Nicho analizado")
    ideas: List[CatalogIdea] = Field(
        default_factory=list,
        description="Lista de ideas generadas"
    )
    gate_passed: bool = Field(
        default=False,
        description="True solo si hay 30 ideas válidas con señales reales"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp de creación (UTC)"
    )
    catalog_locked: bool = Field(
        default=False,
        description="Indica si el catálogo está lockeado (Piece 27)"
    )

    @field_validator("ideas")
    @classmethod
    def validate_ideas_count(cls, v: List[CatalogIdea]) -> List[CatalogIdea]:
        if len(v) > TOTAL_IDEAS:
            raise ValueError(
                f"Máximo {TOTAL_IDEAS} ideas permitidas, got {len(v)}"
            )
        return v

    @property
    def idea_count(self) -> int:
        """Número de ideas en el catálogo."""
        return len(self.ideas)

    @property
    def approved_count(self) -> int:
        """Número de ideas aprobadas."""
        return sum(1 for idea in self.ideas if idea.status == "approved")

    @property
    def category_counts(self) -> Dict[str, int]:
        """Conteo de ideas por categoría maestra."""
        return Counter(idea.master_category for idea in self.ideas)


# =============================================================================
# UTILIDADES PARA EL STACK LLM (Vertex AI)
# =============================================================================

def _get_vertex_ai_client():
    """
    Retorna el cliente Vertex AI configurado.

    Reutiliza el helper de brand_soul/generator.py en vez de duplicar la
    inicialización (bug B4): ese helper usa settings.vertex_ai_project_id /
    settings.vertex_ai_model, que sí están poblados en este proyecto, y ya
    trae el fix de ".get_model()" pagado en la Pieza 25.
    """
    from app.tools.brand_soul.generator import _get_vertex_ai_client as _shared_client
    return _shared_client()


async def _call_llm_with_prompt(prompt: str, temperature: float = 0.7) -> str:
    """
    Llama a Vertex AI Gemini con un prompt y retorna la respuesta como texto.

    Args:
        prompt: Prompt para el LLM
        temperature: Temperatura de generación (0.0 a 1.0)

    Returns:
        Respuesta del LLM como string

    Raises:
        Exception: Si hay error en la llamada al LLM
    """
    model = _get_vertex_ai_client()

    try:
        # generate_content_async (no la variante síncrona) — llamar la síncrona
        # dentro de una función async bloquea el event loop completo, lo que
        # impide que asyncio.wait_for() dispare el timeout del endpoint (bug B5).
        result = await model.generate_content_async(
            prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json"
            }
        )
        return result.text
    except Exception as e:
        raise Exception(f"Error en llamada LLM: {e}") from e


# =============================================================================
# UTILIDADES PARA NÍCHEO
# =============================================================================

def _determine_approach(diagnostico: Dict[str, Any]) -> Literal["experto", "curador"]:
    """
    Determina el enfoque basado en el diagnóstico del fundador.

    Args:
        diagnostico: Contenido de la sección 'diagnostico'

    Returns:
        "experto" si el fundador tiene experiencia directa,
        "curador" si es más investigador/curador
    """
    postura = diagnostico.get("postura", "").lower()

    if "experto" in postura:
        return "experto"
    elif "curador" in postura:
        return "curador"
    else:
        # Inferir de la descripción
        desc = diagnostico.get("descripcion", "").lower()
        experiencia_keywords = [
            "año", "experiencia", "expert", "lidera", "fundador",
            "creó", "construyó"
        ]
        curador_keywords = [
            "investig", "analiz", "studia", "revisa", "curad"
        ]

        exp_score = sum(1 for kw in experiencia_keywords if kw in desc)
        cur_score = sum(1 for kw in curador_keywords if kw in desc)

        return "experto" if exp_score >= cur_score else "curador"


def _extract_niche(icp: Dict[str, Any], charco: Dict[str, Any], diagnostico: Dict[str, Any]) -> str:
    """
    Extrae y limpia el nicho de ICP, charco y diagnostico.

    Args:
        icp: Contenido de la sección 'icp' (campos: quien_decide, tamano_empresa, etc.)
        charco: Contenido de la sección 'charco' (campo: problema)
        diagnostico: Contenido de la sección 'diagnostico' (campo: etapa)

    Returns:
        String con el nicho limpio para búsqueda
    """
    niche = ""

    # Estrategia 1: Intentar extraer de ICP usando campos disponibles
    # El Cliente Ideal (quien_decide) suele contener suficiente contexto
    if icp.get("quien_decide"):
        niche = icp["quien_decide"]
        print(f"[NICHE] Extracted from ICP.quien_decide: {niche[:50]}...")

    # Estrategia 2: Si el ICP no dio suficiente contexto, usar el charco.problema
    if not niche or len(niche.split()) < 4:
        charco_problema = charco.get("problema", "")
        if charco_problema:
            # Extraer las primeras 3-4 palabras significativas del problema
            # Ejemplo: "Profesionales médicos que luchan con liderazgo" -> "Profesionales médicos liderazgo"
            words = charco_problema.split()
            STOPWORDS = ["el", "la", "los", "las", "un", "una", "de", "en", "a", "por", "para", "con", "que", "son", "sus", "tienen", "están"]
            meaningful_words = [w for w in words[:10] if w.lower() not in STOPWORDS and len(w) > 2]
            if len(meaningful_words) >= 3:
                niche = " ".join(meaningful_words[:5])  # Tomar hasta 5 palabras
                print(f"[NICHE] Extracted from charco.problema: {niche[:50]}...")

    # Estrategia 3: Fallback a diagnostico.etapa si todo lo demás falla
    if not niche or len(niche.split()) < 3:
        etapa = diagnostico.get("etapa", "")
        if etapa:
            # La etapa suele contener el nicho
            words = etapa.split()
            STOPWORDS = ["el", "la", "los", "las", "un", "una", "de", "en", "a", "por", "para", "con", "que", "y", "o", "pero"]
            meaningful_words = [w for w in words[:15] if w.lower() not in STOPWORDS and len(w) > 2]
            if len(meaningful_words) >= 3:
                niche = " ".join(meaningful_words[:6])
                print(f"[NICHE] Extracted from diagnostico.etapa: {niche[:50]}...")

    # LIMPIEZA FINAL
    if not niche:
        print("[NICHE] ERROR: Could not extract niche from any source")
        print(f"[NICHE] ICP keys: {list(icp.keys())}")
        print(f"[NICHE] Charco keys: {list(charco.keys())}")
        print(f"[NICHE] Diagnostico keys: {list(diagnostico.keys())}")
        return ""

    # Limpiar caracteres especiales y puntuación al final
    cleaned = niche.rstrip(".,;!?:").strip()

    # Limitar a 80 caracteres para búsqueda eficiente
    cleaned = cleaned[:80]

    print(f"[NICHE] Final cleaned niche: '{cleaned}' (length: {len(cleaned)})")
    return cleaned


# =============================================================================
# GENERACIÓN DE IDEAS
# =============================================================================

def _build_idea_generation_prompt(
    niche: str,
    master_category: str,
    subcategories: List[str],
    niche_research: NicheResearch,
    approach: Literal["experto", "curador"],
    count: int
) -> str:
    """
    Construye el prompt para generar ideas de una categoría específica.

    # PLACEHOLDER: afinar en ronda posterior
    """
    # Construir contexto de demanda desde NicheResearch
    demand_context_lines = []

    # Señales de YouTube
    if niche_research.youtube_pain_signals:
        demand_context_lines.append("SEÑALES DE DOLOR DE YOUTUBE:")
        for i, signal in enumerate(niche_research.youtube_pain_signals[:5], 1):
            demand_context_lines.append(f"  {i}. {signal}")

    # Trends
    if niche_research.trends_series:
        demand_context_lines.append("\nTENDENCIAS DE BÚSQUEDA:")
        for i, (date, value) in enumerate(niche_research.trends_series[:3], 1):
            demand_context_lines.append(f"  {i}. {date}: {value}")

    if niche_research.trends_related:
        demand_context_lines.append("\nBÚSQUEDAS RELACIONADAS:")
        for i, query in enumerate(niche_research.trends_related[:5], 1):
            demand_context_lines.append(f"  {i}. {query}")

    # Notas de grounding web
    if niche_research.web_grounding_notes:
        demand_context_lines.append("\nCONTEXT WEB (GROUNDING):")
        for note in niche_research.web_grounding_notes[:3]:
            demand_context_lines.append(f"  - {note}")

    demand_context = "\n".join(demand_context_lines) if demand_context_lines else "No hay señales específicas."

    # Nombre de categoría
    cat_name = next(c["name"] for c in MASTER_CATEGORIES if c["id"] == master_category)

    # Enfoque del fundador
    approach_note = (
        "El fundador es EXPERTO: usa su experiencia directa, casos reales, y datos propios."
        if approach == "experto"
        else "El fundador es CURADOR: investiga, compara, y presenta aprendizajes de terceros."
    )

    prompt = f"""Eres un estratega de contenido B2B. Tu tarea es generar ideas de contenido ALINEADAS CON DEMANDA REAL.

NICHO: {niche}
CATEGORÍA: {cat_name}
SUBCATEGORÍAS DISPONIBLES: {", ".join(subcategories)}

ENFOQUE DEL FUNDADOR: {approach_note}

CONTEXTO DE DEMANDA REAL:
{demand_context}

INSTRUCCIONES:
1. Genera ideas de contenido que RESPONDAN a las señales de demanda listadas arriba.
2. Usa UNA de las subcategorías para cada idea.
3. NO inventes señales de demanda — cita solo lo que aparece en el contexto.
4. Respeta {cat_name} (no mezcles categorías).

RESPONDE EN JSON con este formato exacto:
{{
  "ideas": [
    {{
      "subcategory": "Nombre de subcategoría (de la lista)",
      "title": "Título de la idea (5-15 palabras)",
      "demand_signal": "Cita textual de la señal de demanda que inspira esta idea (NO inventar)"
    }}
  ]
}}

Genera EXACTAMENTE {count} ideas, ni más ni menos.
"""
    return prompt


async def _generate_ideas_for_category(
    niche: str,
    master_category: str,
    subcategories: List[str],
    niche_research: NicheResearch,
    approach: Literal["experto", "curador"],
    count: int
) -> List[CatalogIdea]:
    """
    Genera ideas para una categoría maestra específica.

    Args:
        niche: Nicho del fundador
        master_category: ID de categoría maestra
        subcategories: Lista de subcategorías válidas
        niche_research: Resultado de research_niche()
        approach: "experto" o "curador"
        count: Cantidad de ideas a generar

    Returns:
        Lista de CatalogIdea generadas
    """
    prompt = _build_idea_generation_prompt(
        niche=niche,
        master_category=master_category,
        subcategories=subcategories,
        niche_research=niche_research,
        approach=approach,
        count=count
    )

    try:
        response = await _call_llm_with_prompt(prompt, temperature=0.7)

        # Parsear respuesta JSON. Con response_mime_type="application/json" el
        # LLM ya no envuelve en ```json ni trunca a media frase (bug B6) -- si
        # aun asi el parseo falla, no se inventan ideas de un fallback de texto:
        # se devuelve [] y el gate honesto se encarga de reportarlo.
        try:
            data = json.loads(response)
            ideas_data = data.get("ideas", [])
        except json.JSONDecodeError as e:
            print(f"[ideas] JSON inválido del LLM para {master_category}: {e}")
            return []

        # Convertir a CatalogIdea
        ideas = []
        for idea_data in ideas_data[:count]:  # Limitar a count
            try:
                idea = CatalogIdea(
                    master_category=master_category,
                    subcategory=idea_data.get("subcategory", subcategories[0]),
                    title=idea_data.get("title", "Si título"),
                    demand_signal=idea_data.get(
                        "demand_signal",
                        _get_fallback_signal(niche_research)
                    ),
                    status="pending"
                )
                if len(idea.demand_signal) >= 10:
                    ideas.append(idea)
            except Exception:
                continue

        return ideas

    except Exception as e:
        print(f"Error generando ideas para {master_category}: {e}")
        return []


def _get_fallback_signal(niche_research: NicheResearch) -> str:
    """
    Retorna una señal de demanda fallback si el LLM no cita ninguna.
    """
    if niche_research.youtube_pain_signals:
        return niche_research.youtube_pain_signals[0][:200]
    if niche_research.trends_related:
        return f"Tendencia de búsqueda: {niche_research.trends_related[0]}"
    if niche_research.web_grounding_notes:
        return niche_research.web_grounding_notes[0][:200]
    return "Demanda detectada en investigación de nicho"


def _check_brand_soul_generated(session_id: str) -> bool:
    """
    Verifica si Brand Soul ha sido generado y cacheado para la sesión.

    Args:
        session_id: ID de sesión único

    Returns:
        True si Brand Soul existe en cache, False en otro caso
    """
    from app.tools.brand_brain.store import get_brand_brain
    from app.tools.brand_soul.generator import _check_cache

    brain = get_brand_brain(session_id)
    if not brain:
        return False

    cached_html = _check_cache(brain, session_id)
    return cached_html is not None


async def generate_catalog(session_id: str, niche_research: Optional[NicheResearch] = None) -> Catalog:
    """
    Genera el catálogo de 30 ideas para la sesión.

    Flujo:
    1. Obtiene BrandBrain lockeado
    2. Verifica que Brand Soul exista (prerequisito para catálogo)
    3. Extrae nicho y enfoque
    4. Llama a research_niche() para obtener señales de demanda (salvo que ya
       venga pre-calculado en `niche_research` -- ver bug B1: evita disparar
       research_niche() dos veces en el mismo request de /investigate)
    5. Genera ideas distribuidas en 5 categorías maestras
    6. Valida gate (30 ideas válidas con señales reales)

    Args:
        session_id: ID de sesión único
        niche_research: NicheResearch ya calculado por el llamador (opcional).
            Si se pasa, no se vuelve a llamar research_niche() internamente.

    Returns:
        Catalog con las ideas generadas

    Raises:
        IncompleteBrainError: Si BrandBrain no está completado (secciones sin confirmar)
        ValueError: Si falta información clave en BrandBrain o Brand Soul no existe
        NicheReportNotFoundError: Si no se pudo obtener un NicheResearch para el nicho
        Exception: Si hay error en la generación o research_niche()
    """
    # 1. Obtener BrandBrain lockeado
    brain = get_brand_brain(session_id)

    if not brain or not brain.sections:
        raise ValueError("No se encontró BrandBrain para esta sesión")

    # Verificar que esté lockeado
    for section in brain.sections:
        if section.status != "confirmado" and section.status != "completado":
            raise IncompleteBrainError(
                f"BrandBrain no está completado: sección '{section.label}' "
                f"tiene estado '{section.status}'"
            )

    # 2. Verificar que Brand Soul exista (REQUISITO OBLIGATORIO)
    if not _check_brand_soul_generated(session_id):
        raise ValueError(
            "Brand Soul es un prerequisito para generar el catálogo. "
            "Primero genera tu Brand Soul para continuar."
        )

    # 2. Extraer información clave
    diagnostico = brain.get_section("diagnostico").content if brain.get_section("diagnostico") else {}
    icp = brain.get_section("icp").content if brain.get_section("icp") else {}
    charco = brain.get_section("charco").content if brain.get_section("charco") else {}

    if not diagnostico or not icp or not charco:
        raise ValueError(
            "Faltan secciones requeridas en BrandBrain: "
            "diagnostico, icp, charco"
        )

    # Determinar enfoque
    approach = _determine_approach(diagnostico)

    # Extraer nicho
    niche = _extract_niche(icp, charco, diagnostico)

    if not niche or len(niche) < 3:
        raise ValueError("No se pudo extraer un nicho válido de BrandBrain")

    # 3. Llamar a research_niche() para obtener señales de demanda
    # (salvo que el llamador ya la haya calculado -- bug B1)
    if niche_research is None:
        try:
            niche_research = await research_niche(niche)
            if niche_research is None:
                raise NicheReportNotFoundError(
                    f"No se pudo obtener un NicheResearch para el nicho: {niche}"
                )
        except NicheReportNotFoundError:
            raise  # Re-levantar tal cual, ya es nuestra excepción
        except Exception as e:
            raise Exception(f"Error en research_niche(): {e}") from e

    # 4. Generar ideas distribuidas en 5 categorías
    all_ideas = []

    # Generar por cada categoría principal
    for cat_id, count in IDEA_DISTRIBUTION.items():
        cat_info = next((c for c in MASTER_CATEGORIES if c["id"] == cat_id), None)
        if not cat_info:
            continue

        # Generar ideas para esta categoría
        category_ideas = await _generate_ideas_for_category(
            niche=niche,
            master_category=cat_id,
            subcategories=cat_info["subcategories"],
            niche_research=niche_research,
            approach=approach,
            count=count
        )

        all_ideas.extend(category_ideas)

    # Rellenar si faltan ideas (distribuir en categorías principales).
    # Acotado a MAX_FILL_ROUNDS (bug B2): si el LLM devuelve [] o pocas ideas,
    # esto ya NO reintenta sin fin hasta el timeout de 120s del endpoint --
    # se detiene y deja que el gate honesto reporte gate_passed=False.
    MAX_FILL_ROUNDS = 2
    fill_round = 0
    while len(all_ideas) < TOTAL_IDEAS and fill_round < MAX_FILL_ROUNDS:
        fill_round += 1
        missing = TOTAL_IDEAS - len(all_ideas)
        made_progress = False
        for cat_id in IDEA_DISTRIBUTION:
            if missing <= 0:
                break
            cat_info = next((c for c in MASTER_CATEGORIES if c["id"] == cat_id), None)
            if cat_info:
                extra = await _generate_ideas_for_category(
                    niche=niche,
                    master_category=cat_id,
                    subcategories=cat_info["subcategories"],
                    niche_research=niche_research,
                    approach=approach,
                    count=1
                )
                if extra:
                    made_progress = True
                all_ideas.extend(extra)
                missing -= len(extra) if extra else 0
        if not made_progress:
            # El LLM no está devolviendo ideas nuevas -- no insistir más rondas.
            break

    # Limitar a 30 ideas
    all_ideas = all_ideas[:TOTAL_IDEAS]

    # 5. Validar gate
    gate_passed = (
        len(all_ideas) == TOTAL_IDEAS and
        all(len(idea.demand_signal) >= 10 for idea in all_ideas)
    )

    # Crear catálogo
    catalog = Catalog(
        session_id=session_id,
        niche=niche,
        ideas=all_ideas,
        gate_passed=gate_passed,
        created_at=datetime.now(timezone.utc),
        catalog_locked=False  # Piece 27
    )

    return catalog


# =============================================================================
# CACHING
# =============================================================================

def _compute_catalog_hash(session_id: str) -> str:
    """
    Calcula un hash basado en el BrandBrain de la sesión.

    EXCLUYE timestamps (no estamos en el bug de hash-with-timestamps).

    Args:
        session_id: ID de sesión

    Returns:
        String hash SHA256
    """
    brain = get_brand_brain(session_id)

    if not brain:
        raise ValueError("No se encontró BrandBrain para esta sesión")

    # Serializar solo los datos relevantes (sin timestamps)
    data_to_hash = {
        "session_id": session_id,
        "sections": [
            {
                "id": s.id,
                "label": s.label,
                "status": s.status,
                "content": s.content,
                # NO incluir created_at/updated_at
            }
            for s in brain.sections
        ]
    }

    # Calcular hash
    json_str = json.dumps(data_to_hash, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def _check_catalog_cache(session_id: str) -> Optional[Catalog]:
    """
    Verifica si existe un catálogo cacheado válido para esta sesión.

    Args:
        session_id: ID de sesión

    Returns:
        Catalog si existe y es válido, None en caso contrario
    """
    cache_dir = "cache/catalog"
    cache_file = os.path.join(cache_dir, f"{session_id}.json")

    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Verificar TTL
        created_str = data.get("created_at")
        if created_str:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - created
            if age > timedelta(seconds=CACHE_TTL_SECONDS):
                return None  # Cache expirado

        # Verificar hash
        current_hash = _compute_catalog_hash(session_id)
        cached_hash = data.get("brand_hash")

        if cached_hash != current_hash:
            return None  # BrandBrain cambió

        # Reconstruir Catalog
        ideas_json = data.get("ideas", [])
        ideas = [
            CatalogIdea(**idea_data)
            for idea_data in ideas_json
        ]

        catalog = Catalog(
            session_id=data.get("session_id", session_id),
            niche=data.get("niche", ""),
            ideas=ideas,
            gate_passed=data.get("gate_passed", False),
            created_at=datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.now(timezone.utc),
            catalog_locked=data.get("catalog_locked", False)
        )

        return catalog

    except Exception as e:
        print(f"Error leyendo cache: {e}")
        return None


def _save_catalog_cache(catalog: Catalog) -> None:
    """
    Guarda un catálogo en cache para futuras consultas.

    Args:
        catalog: Catalog a cachear
    """
    cache_dir = "cache/catalog"
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{catalog.session_id}.json")

    try:
        # Calcular hash del BrandBrain
        brand_hash = _compute_catalog_hash(catalog.session_id)

        data = {
            "session_id": catalog.session_id,
            "niche": catalog.niche,
            "ideas": [idea.model_dump() for idea in catalog.ideas],
            "gate_passed": catalog.gate_passed,
            "created_at": catalog.created_at.isoformat(),
            "catalog_locked": catalog.catalog_locked,
            "brand_hash": brand_hash
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        print(f"Error guardando cache: {e}")


async def get_or_generate_catalog(session_id: str) -> Catalog:
    """
    Obtiene el catálogo cacheado o genera uno nuevo.

    Args:
        session_id: ID de sesión

    Returns:
        Catalog con las ideas (cacheado o generado)
    """
    # Intentar cargar de cache
    cached = _check_catalog_cache(session_id)
    if cached:
        return cached

    # Generar nuevo catálogo
    catalog = await generate_catalog(session_id)

    # Guardar en cache
    _save_catalog_cache(catalog)

    return catalog


async def update_idea_status(
    session_id: str,
    idea_id: str,
    new_status: Literal["pending", "approved", "rejected"]
) -> Catalog:
    """
    Actualiza el estado de aprobación/descarte de una idea individual.
    """
    # Bug B10: usar SOLO el cache, nunca get_or_generate_catalog -- si no hay
    # catálogo generado todavía, esto disparaba una generación completa GRATIS
    # (sin cobrar los 15/25 créditos de /generate o /investigate).
    catalog = _check_catalog_cache(session_id)
    if not catalog:
        raise ValueError("No hay catálogo generado para esta sesión. Genera o investiga primero.")
    if catalog.catalog_locked:
        raise ValueError("El catálogo está bloqueado. No se pueden modificar ideas.")

    found = False
    for idea in catalog.ideas:
        if idea.id == idea_id:
            idea.status = new_status
            found = True
            break

    if not found:
        raise ValueError(f"Idea con ID '{idea_id}' no encontrada en el catálogo.")

    _save_catalog_cache(catalog)
    return catalog


async def regenerate_single_idea(session_id: str, idea_id: str) -> CatalogIdea:
    """
    Regenera únicamente una idea individual reemplazándola en la misma categoría.
    """
    # Bug B10: mismo fix que update_idea_status -- solo cache, nunca generación gratis.
    catalog = _check_catalog_cache(session_id)
    if not catalog:
        raise ValueError("No hay catálogo generado para esta sesión. Genera o investiga primero.")
    if catalog.catalog_locked:
        raise ValueError("El catálogo está bloqueado. No se pueden regenerar ideas.")

    target_idea = next((i for i in catalog.ideas if i.id == idea_id), None)
    if not target_idea:
        raise ValueError(f"Idea con ID '{idea_id}' no encontrada en el catálogo.")

    # Re-obtener brain y research
    brain = get_brand_brain(session_id)
    diagnostico = brain.get_section("diagnostico").content if brain else {}
    icp = brain.get_section("icp").content if brain else {}
    charco = brain.get_section("charco").content if brain else {}
    approach = _determine_approach(diagnostico)
    niche = _extract_niche(icp, charco, diagnostico)

    niche_research = await research_niche(niche)

    cat_info = next((c for c in MASTER_CATEGORIES if c["id"] == target_idea.master_category), None)
    subcategories = cat_info["subcategories"] if cat_info else ["General"]

    new_ideas = await _generate_ideas_for_category(
        niche=niche,
        master_category=target_idea.master_category,
        subcategories=subcategories,
        niche_research=niche_research,
        approach=approach,
        count=1
    )

    if not new_ideas:
        raise Exception("No se pudo generar un reemplazo para la idea.")

    new_idea = new_ideas[0]
    # Reemplazar en la lista preservando posición
    for i, idea in enumerate(catalog.ideas):
        if idea.id == idea_id:
            catalog.ideas[i] = new_idea
            break

    _save_catalog_cache(catalog)
    return new_idea


def lock_catalog_session(session_id: str) -> Catalog:
    """
    Bloquea el catálogo si todas las ideas han sido revisadas (approved o rejected).
    """
    catalog = _check_catalog_cache(session_id)
    if not catalog:
        raise ValueError("No existe un catálogo generado para esta sesión.")

    pending_count = sum(1 for idea in catalog.ideas if idea.status == "pending")
    if pending_count > 0:
        raise ValueError(
            f"No se puede bloquear el catálogo. Hay {pending_count} ideas aún en estado 'pending'."
        )

    catalog.catalog_locked = True
    _save_catalog_cache(catalog)
    return catalog
