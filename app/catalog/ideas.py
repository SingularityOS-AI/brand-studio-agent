"""
Content Ideas Generator - "Pieza 4: Bloque B, el catálogo de 30 ideas"

Generates a structured catalog of 30 content ideas from BrandBrain + NicheReport.

Core invariants:
1. LLM ON A LEASH: Only sees BrandBrain sections and NicheReport signals
2. ZERO-INVENTION: Demand signals MUST be citable from NicheReport, never fabricated
3. CACHE HASH: Hash actual section content only, exclude created_at/updated_at
4. ANGLE VALIDATION: Only 4 allowed angles ("Útil", "Inmersivo", "Reflexivo", "Vulnerable")
5. GATE HONESTY: catalog_gate_passed = True ONLY when exactly 30 valid ideas exist

Approach determination:
- If diagnostico.postura == "experto": "Experto" approach
- If diagnostico.postura == "estudiante" or "hipotesis": "Curador" approach

Categories:
- Derived from founder's charco, icp, identidad, oferta (founder-specific, not generic)
- 3 categories total
- 10 ideas per category (30 total)

Cost: 15 credits (TODO: CEO review)
"""

import os
import json
import hashlib
import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.catalog.demand import (
    validate_niche_demand,
    NicheReport,
    Signal
)
from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.store import get_brand_brain
from app.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS (per design.md §10)
# =============================================================================

class Idea(BaseModel):
    """A single content idea with citable demand signal.

    Fields:
    - id: Unique identifier (category-index format)
    - title: Compelling title for the content
    - angle: One of 4 fixed angles (Literal validation)
    - brief: What the content covers
    - target_audience: Who it's for (derived from ICP)
    - demand_signal: Optional citable signal from NicheReport
    - demand_url: Evidence URL if signal exists, else None
    """

    id: str = Field(..., description="Unique identifier (e.g., 'category1-01')")
    title: str = Field(..., description="Compelling title for the content")
    angle: str = Field(..., description="Content angle: one of 4 fixed")
    brief: str = Field(..., description="What the content covers")
    target_audience: str = Field(..., description="Who it's for")
    demand_signal: Optional[str] = Field(
        None,
        description="Citable demand signal from NicheReport or None if unavailable"
    )
    demand_url: Optional[str] = Field(
        None,
        description="Evidence URL for demand signal if available"
    )


class Category(BaseModel):
    """A content category with 10 ideas.

    Fields:
    - id: Unique identifier (category1, category2, category3)
    - name: Founder-specific category name
    - rationale: Why this category matters for this founder
    - ideas: List of 10 Idea objects
    """

    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Founder-specific category name")
    rationale: str = Field(..., description="Why this category matters")
    ideas: List[Idea] = Field(..., description="10 ideas for this category")


class Catalog(BaseModel):
    """The complete 30-idea catalog.

    Fields:
    - categories: List of 3 Category objects (30 ideas total)
    - approach: "Experto" or "Curador" based on diagnostico
    - niche: The niche string used for demand validation
    - total_ideas: Should be exactly 30
    - gate_passed: True only if exactly 30 valid ideas exist
    """

    categories: List[Category] = Field(..., description="3 categories with 30 ideas total")
    approach: str = Field(..., description="'Experto' or 'Curador'")
    niche: str = Field(..., description="Niche used for demand validation")
    total_ideas: int = Field(..., description="Total ideas (should be 30)")
    gate_passed: bool = Field(..., description="True only if exactly 30 valid ideas")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Fixed angles - ALL angles must match these exactly
VALID_ANGLES = ["Útil", "Inmersivo", "Reflexivo", "Vulnerable"]

# Credits cost for generation (TODO: CEO review)
CREDITS_COST = 15


# =============================================================================
# CACHE FUNCTIONS
# =============================================================================

def _compute_catalog_hash(brain: BrandBrain) -> str:
    """
    Compute hash of the brain for catalog cache invalidation.

    CRITICAL: Hash ONLY actual section content, exclude created_at/updated_at.
    This prevents cache self-invalidation on every DB update.

    Args:
        brain: BrandBrain object

    Returns:
        SHA256 hex digest of hashable content
    """
    hashable = {
        "sections": [
            {
                "id": s.id,
                "label": s.label,
                "status": s.status,
                "content": s.content,
                "citation_text": s.citation_text,
                "citation_source": s.citation_source,
                # EXCLUDE: created_at, updated_at (dynamic timestamps)
            }
            for s in brain.sections
        ],
        "formato": brain.formato,
    }
    brain_json = json.dumps(hashable, sort_keys=True)
    return hashlib.sha256(brain_json.encode()).hexdigest()


def _check_catalog_cache(brain: BrandBrain, session_token: str) -> Optional[dict]:
    """
    Check if a cached catalog exists for this brain.

    Args:
        brain: BrandBrain object
        session_token: Session token to query cache

    Returns:
        Cached catalog dict if valid cache hit, None otherwise
    """
    if os.getenv("TEST_MODE") == "true":
        return None

    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return None

        # Query the brand_brains table
        result = client.table("brand_brains").select(
            "catalog_json",
            "catalog_hash"
        ).eq("session_token", session_token).execute()

        if not result.data:
            return None

        row = result.data[0]

        # Check if catalog_hash matches (cache invalidation)
        current_hash = _compute_catalog_hash(brain)
        cached_hash = row.get("catalog_hash")

        if not cached_hash or cached_hash != current_hash:
            # Brain changed, cache is invalid
            logger.debug("[catalog] Cache hash mismatch - invalidating")
            return None

        # Return cached catalog
        catalog_dict = row.get("catalog_json")
        if catalog_dict:
            logger.debug("[catalog] Cache hit - returning cached catalog")
            return catalog_dict

        return None

    except Exception as e:
        logger.warning(f"[catalog] Failed to check cache: {e}")
        return None


def _save_catalog_cache(
    brain: BrandBrain,
    catalog: Catalog,
    session_token: str,
    gate_passed: bool
) -> bool:
    """
    Save the generated catalog to cache.

    Args:
        brain: BrandBrain object
        catalog: Generated Catalog object
        session_token: Session token to update cache
        gate_passed: Whether the gate passed (30 valid ideas)

    Returns:
        True if saved successfully, False otherwise
    """
    if os.getenv("TEST_MODE") == "true":
        return True

    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return False

        # Compute brain hash for cache invalidation
        brain_hash = _compute_catalog_hash(brain)

        # Update the brand_brains table
        response = client.table("brand_brains").update({
            "catalog_json": catalog.model_dump(),
            "catalog_hash": brain_hash,
            "catalog_gate_passed": gate_passed,
            "catalog_generated_at": "now()"
        }).eq("session_token", session_token).execute()

        return len(response.data) > 0

    except Exception as e:
        logger.warning(f"[catalog] Failed to save cache: {e}")
        return False


# =============================================================================
# VERTEX AI CLIENT
# =============================================================================

def _get_vertex_ai_client():
    """
    Get the Vertex AI client for Gemini models.

    Returns:
        Vertex AI GenerativeModel or None if not configured/test mode

    Raises:
        RuntimeError: If Vertex AI is not configured in production mode
    """
    # In test mode, return None to allow mocking
    if os.getenv("TEST_MODE") == "true":
        return None

    if not settings.vertex_ai_project_id:
        raise RuntimeError(
            "VERTEX_AI_PROJECT_ID is not configured. "
            "Set it in .env file or environment variable before starting the server."
        )

    try:
        from vertexai.generative_models import GenerativeModel
        import vertexai

        # Initialize Vertex AI
        vertexai.init(
            project=settings.vertex_ai_project_id,
            location=settings.vertex_ai_location
        )

        # Use model from settings (NEVER hardcode model ID)
        return GenerativeModel(settings.vertex_ai_model)

    except ImportError:
        raise RuntimeError(
            "google-cloud-aiplatform is not installed. "
            "Install it with: pip install google-cloud-aiplatform"
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize Vertex AI client: {e}. "
            "Ensure VERTEX_AI_PROJECT_ID and VERTEX_AI_LOCATION are correct."
        )


# =============================================================================
# LLM CALLS
# =============================================================================

def _call_llm_with_prompt(prompt: str, max_tokens: int = 1000) -> str:
    """
    Call Vertex AI LLM with a prompt.

    Args:
        prompt: The prompt to send
        max_tokens: Maximum output tokens

    Returns:
        LLM response text

    Raises:
        RuntimeError: If LLM call fails
    """
    model = _get_vertex_ai_client()

    # In test mode, return mock response
    if model is None:
        return '{"test": "mock_response"}'

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.0,  # Deterministic output
                "max_output_tokens": max_tokens,
                "candidate_count": 1
            }
        )

        if not response.text:
            raise RuntimeError("LLM returned empty response")

        # Clean up response
        return response.text.strip()

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise RuntimeError(f"LLM generation failed: {e}")


def _determine_approach(brain: BrandBrain) -> str:
    """
    Determine approach based on diagnostico.postura.

    Args:
        brain: BrandBrain object

    Returns:
        "Experto" if postura == "experto", else "Curador"
    """
    diag_section = brain.get_section("diagnostico")
    if diag_section and diag_section.status == "confirmado":
        postura = diag_section.content.get("postura", "").lower()
        if postura == "experto":
            return "Experto"
    return "Curador"


def _extract_niche(brain: BrandBrain) -> str:
    """
    Extract niche from brand_brain sections.

    Priority: icp.nicho > charco.problema keywords > "general"

    Args:
        brain: BrandBrain object

    Returns:
        Niche string for demand validation
    """
    # Try ICP section first
    icp_section = brain.get_section("icp")
    if icp_section and icp_section.status == "confirmado":
        nicho = icp_section.content.get("nicho", "")
        if nicho:
            return nicho

    # Try charco for keywords
    charco_section = brain.get_section("charco")
    if charco_section and charco_section.status == "confirmado":
        problema = charco_section.content.get("problema", "")
        # Extract keywords (simple heuristic)
        words = problema.split()[:5]  # First 5 words
        result = " ".join(words)
        if result:  # Only return if we got actual keywords
            return result

    return "general"


def _derive_categories(brain: BrandBrain) -> List[Dict[str, str]]:
    """
    Use LLM to derive 3 founder-specific content categories.

    Categories must be derived from:
    - charco (pain point)
    - icp (ideal client profile)
    - identidad (brand identity)
    - oferta (offer/value proposition)

    Categories must be founder-specific, not generic.

    Args:
        brain: BrandBrain object

    Returns:
        List of 3 dicts with 'id', 'name', 'rationale'
    """
    # Extract relevant sections
    charco_section = brain.get_section("charco")
    icp_section = brain.get_section("icp")
    identidad_section = brain.get_section("identidad")
    oferta_section = brain.get_section("oferta")

    is_experto = _determine_approach(brain) == "Experto"

    # Build prompt
    prompt = f"""Eres un estratega de contenido especializado en creators.

Tu tarea: Derivar 3 categorías de contenido FUNDADOR-ESPECÍFICAS basadas en el BrandBrain.

CONTEXTO DEL FUNDADOR:
"""
    if charco_section and charco_section.status == "confirmado":
        prompt += f"""
Punto de dolor (charco):
{charco_section.content.get("problema", "")}
"""

    if icp_section and icp_section.status == "confirmado":
        prompt += f"""
Perfil de cliente ideal (ICP):
Duración del problema: {icp_section.content.get("duracion_problema", "")}
Costo del problema: {icp_section.content.get("costo_problema", "")}
Soluciones intentadas: {icp_section.content.get("soluciones_intentadas", "")}
"""

    if identidad_section and identidad_section.status == "confirmado":
        prompt += f"""
Identidad de marca:
Voz: {identidad_section.content.get("voz", "")}
Colores: {identidad_section.content.get("colores", "")}
"""

    if oferta_section and oferta_section.status == "confirmado":
        prompt += f"""
Oferta:
Resultado sonado: {oferta_section.content.get("resultado_sonado", "")}
Probabilidad percibida: {oferta_section.content.get("probabilidad_percibida", "")}
"""

    prompt += f"""
ENFOQUE: {"Experto" if is_experto else "Curador"}

INSTRUCCIONES:
1. Deriva 3 categorías de contenido que sean ÚNICAS para este fundador.
2. Categorías genéricas como "tutoriales", "motivación", "tips" están prohibidas.
3. Cada categoría debe reflejar la intersección de: charco + icp + identidad + oferta.
4. Para cada categoría, explica "rationale" (por qué esta categoría importa específicamente para ESTE fundador).

FORMATO DE RESPUESTA (JSON válido):
{{
  "categories": [
    {{
      "id": "category1",
      "name": "Nombre específico de categoría",
      "rationale": "Por qué esta categoría es única para este fundador"
    }},
    {{
      "id": "category2",
      "name": "Nombre específico de categoría",
      "rationale": "Por qué esta categoría es única para este fundador"
    }},
    {{
      "id": "category3",
      "name": "Nombre específico de categoría",
      "rationale": "Por qué esta categoría es única para este fundador"
    }}
  ]
}}

IMPORTANTE:
- NO uses plantillas genéricas.
- Si dos fundadores diferentes ejecutan este prompt, deben obtener categorías diferentes.
- Devuelve SOLO el JSON, sin explicaciones."""

    response = _call_llm_with_prompt(prompt, max_tokens=800)

    try:
        # Parse JSON from response
        # Handle markdown code blocks if present
        if response.startswith("```"):
            lines = response.split("\n")
            if len(lines) > 2:
                response = "\n".join(lines[1:-1])
            else:
                response = "\n".join(lines[1:])

        data = json.loads(response)
        categories = data.get("categories", [])

        # Validate exactly 3 categories
        if len(categories) != 3:
            logger.warning(f"LLM returned {len(categories)} categories, expected 3. Using all provided.")

        return categories

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse category JSON: {e}")
        # Fallback: generate categories from structure
        return _fallback_categories(brain)


def _fallback_categories(brain: BrandBrain) -> List[Dict[str, str]]:
    """
    Fallback category generation when LLM fails.

    Args:
        brain: BrandBrain object

    Returns:
        List of 3 category dicts
    """
    icp_section = brain.get_section("icp")
    charco_section = brain.get_section("charco")
    oferta_section = brain.get_section("oferta")

    # Extract keywords for category names
    icp_text = icp_section.content.get("nicho", "") if icp_section else ""
    charco_text = charco_section.content.get("problema", "") if charco_section else ""
    oferta_text = oferta_section.content.get("resultado_sonado", "") if oferta_section else ""

    # Generate 3 categories based on structure
    cat1_name = f"Resolución de {icp_text[:20]}..." if icp_text else "Resolución de problemas del ICP"
    cat2_name = f"Análisis de {charco_text[:20]}..." if charco_text else "Análisis del punto de dolor"
    cat3_name = f"Camino hacia {oferta_text[:20]}..." if oferta_text else "Camino hacia el resultado"

    return [
        {
            "id": "category1",
            "name": cat1_name,
            "rationale": "Basado en el nicho del ICP, esta categoría aborda los problemas específicos."
        },
        {
            "id": "category2",
            "name": cat2_name,
            "rationale": "Basado en el punto de dolor, esta categoría explora las causas profundas."
        },
        {
            "id": "category3",
            "name": cat3_name,
            "rationale": "Basado en la oferta, esta categoría muestra el camino hacia el resultado."
        }
    ]


def _match_demand_signal(idea_title: str, niche_report: NicheReport) -> Optional[Dict[str, str]]:
    """
    Fuzzy match idea title against demand signals from NicheReport.

    Args:
        idea_title: The idea title to match
        niche_report: NicheReport with demand signals

    Returns:
        Dict with 'signal' and 'url' if match found, None otherwise
    """
    # Collect all signals from NicheReport
    all_signals = []
    all_signals.extend(niche_report.demand)
    all_signals.extend(niche_report.trust_barrier)
    all_signals.extend(niche_report.packaging)

    if not all_signals:
        return None

    # Simple keyword matching
    idea_lower = idea_title.lower()

    for signal in all_signals:
        # Check if signal value contains idea keywords
        signal_lower = signal.value.lower()
        # Extract keywords from idea (first 3 meaningful words)
        idea_keywords = [w for w in idea_lower.split() if len(w) > 3][:3]

        for keyword in idea_keywords:
            if keyword in signal_lower:
                return {
                    "signal": signal.value,
                    "url": signal.evidence_url
                }

    return None


def _generate_ideas_for_category(
    category_id: str,
    category_name: str,
    brain: BrandBrain,
    niche_report: NicheReport,
    approach: str
) -> List[Idea]:
    """
    Generate 10 ideas for a specific category using LLM.

    Each idea must:
    - Use one of 4 fixed angles ("Útil", "Inmersivo", "Reflexivo", "Vulnerable")
    - Have a title, brief, target audience
    - Include demand signal if available from NicheReport

    Args:
        category_id: Category identifier
        category_name: Category name
        brain: BrandBrain object
        niche_report: NicheReport for signal matching
        approach: "Experto" or "Curador"

    Returns:
        List of 10 Idea objects
    """
    # Extract relevant sections for context
    icp_section = brain.get_section("icp")
    identidad_section = brain.get_section("identidad")
    oferta_section = brain.get_section("oferta")
    charco_section = brain.get_section("charco")

    icp_text = icp_section.content.get("descripcion", "") if icp_section else ""

    # Build prompt
    prompt = f"""Eres un estratega de contenido {'experto' if approach == 'Experto' else 'curador'}.

Tu tarea: Generar 10 ideas de contenido para la categoría "{category_name}".

CONTEXTO DEL FUNDADOR:
"""
    if icp_section and icp_section.status == "confirmado":
        prompt += f"""
Perfil de cliente ideal (ICP):
Descripción: {icp_section.content.get("descripcion", "")}
"""

    if charco_section and charco_section.status == "confirmado":
        prompt += f"""
Punto de dolor: {charco_section.content.get("problema", "")}
"""

    if oferta_section and oferta_section.status == "confirmado":
        prompt += f"""
Oferta: {oferta_section.content.get("resultado_sonado", "")}
"""

    prompt += f"""
ENFOQUE: {approach}

CATEGORÍA: {category_name}

ÁNGULOS PERMITIDOS (SOLO estos 4):
1. Útil: Contenido práctico, how-to, herramientas, frameworks
2. Inmersivo: Casos de estudio, storytelling, narrativa, ejemplos
3. Reflexivo: Análisis, perspectivas, filosofía, pensamiento crítico
4. Vulnerable: Experiencia personal, aprendizajes, fracasos, journeys

INSTRUCCIONES:
1. Generar 10 ideas para esta categoría
2. Cada idea debe usar un ángulo diferente (rotar por los 4 ángulos, repetir dopo)
3. Para cada idea: id (formato "{category_id}-01", "{category_id}-02", ...), title, angle, brief, target_audience
4. Ids: "{category_id}-01" a "{category_id}-10"
5. Asegurar que los ángulos sean SOLO los 4 permitidos (Útil, Inmersivo, Reflexivo, Vulnerable)
6. Los títulos deben ser atractivos y específicos (no genéricos)

FORMATO DE RESPUESTA (JSON válido):
{{
  "ideas": [
    {{
      "id": "{category_id}-01",
      "title": "Título atractivo y específico",
      "angle": "Útil",
      "brief": "Breve descripción del contenido",
      "target_audience": "Destinatario específico"
    }},
    ...
    (10 ideas total)
    {{
      "id": "{category_id}-10",
      "title": "Título atractivo y específico",
      "angle": "Vulnerable",
      "brief": "Breve descripción del contenido",
      "target_audience": "Destinatario específico"
    }}
  ]
}}

IMPORTANTE:
- NO inventar señales de demanda (demand_signal y demand_url se agregan después).
- NO usar ángulos que no sean los 4 permitidos.
- Devuelve SOLO el JSON, sin explicaciones.
- Debe haber EXACTAMENTE 10 ideas."""

    response = _call_llm_with_prompt(prompt, max_tokens=1500)

    try:
        # Parse JSON from response
        if response.startswith("```"):
            lines = response.split("\n")
            if len(lines) > 2:
                response = "\n".join(lines[1:-1])
            else:
                response = "\n".join(lines[1:])

        data = json.loads(response)
        ideas_data = data.get("ideas", [])

        # Validate exactly 10 ideas
        if len(ideas_data) != 10:
            logger.warning(f"LLM returned {len(ideas_data)} ideas, expected 10. Using all provided.")

        # Validate angles
        valid_ideas = []
        for idea_data in ideas_data:
            angle = idea_data.get("angle", "")
            if angle not in VALID_ANGLES:
                logger.warning(f"Invalid angle '{angle}' for idea {idea_data.get('id')}. Skipping.")
                continue

            # Match demand signal
            title = idea_data.get("title", "")
            signal_match = _match_demand_signal(title, niche_report)

            idea = Idea(
                id=idea_data.get("id", ""),
                title=title,
                angle=angle,
                brief=idea_data.get("brief", ""),
                target_audience=idea_data.get("target_audience", ""),
                demand_signal=signal_match["signal"] if signal_match else None,
                demand_url=signal_match["url"] if signal_match else None
            )
            valid_ideas.append(idea)

        return valid_ideas

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ideas JSON: {e}")
        return []


# =============================================================================
# MAIN GENERATION FUNCTION
# =============================================================================

class CatalogGenerationError(Exception):
    """Raised when catalog cannot be generated"""
    pass


class IncompleteBrainError(CatalogGenerationError):
    """Raised when brain doesn't have all required sections"""
    pass


class NicheReportNotFoundError(CatalogGenerationError):
    """Raised when NicheReport is not available for the niche"""
    pass


async def generate_catalog(
    session_token: str,
    regenerate: bool = False
) -> Tuple[Catalog, str]:
    """
    Generate the catalog of 30 content ideas.

    Args:
        session_token: User session token
        regenerate: Force regeneration even if cached

    Returns:
        Tuple of (Catalog object, cache_status string)

    Raises:
        IncompleteBrainError: If brain doesn't have 9 confirmed sections
        CatalogGenerationError: If generation fails
    """
    # 1. Get BrandBrain
    brain = get_brand_brain(session_token)
    if not brain:
        raise CatalogGenerationError("Brand brain not found for this session")

    # 2. Check all 9 sections are confirmed
    required_sections = [
        "diagnostico", "brand_journey", "charco", "icp",
        "contrarian", "asociaciones", "identidad", "oferta", "lead_magnet"
    ]
    missing = [
        sid for sid in required_sections
        if not brain.get_section(sid) or brain.get_section(sid).status != "confirmado"
    ]
    if missing:
        raise IncompleteBrainError(
            f"Missing or unconfirmed sections: {', '.join(missing)}"
        )

    # 3. Check cache
    if not regenerate:
        cached_dict = _check_catalog_cache(brain, session_token)
        if cached_dict:
            logger.info("[catalog] Returning cached catalog")
            return Catalog(**cached_dict), "cached"

    logger.info("[catalog] Generating new catalog")

    # 4. Determine approach
    approach = _determine_approach(brain)

    # 5. Extract niche
    niche = _extract_niche(brain)

    # 6. Validate niche demand
    logger.info(f"[catalog] Validating demand for niche: {niche}")
    niche_report = await validate_niche_demand(niche, use_cache=True)

    if niche_report is None:
        raise NicheReportNotFoundError(
            f"NicheReport no encontrado para nicho: {niche}. "
            "Genere el reporte de demanda primero."
        )

    # 7. Derive categories using LLM
    logger.info("[catalog] Deriving 3 founder-specific categories")
    categories_data = _derive_categories(brain)

    if len(categories_data) != 3:
        raise CatalogGenerationError(
            f"Expected 3 categories, got {len(categories_data)}"
        )

    # 8. Generate ideas for each category
    logger.info("[catalog] Generating 30 ideas (10 per category)")
    all_categories = []

    for cat_data in categories_data:
        cat_id = cat_data["id"]
        cat_name = cat_data["name"]
        cat_rationale = cat_data["rationale"]

        logger.info(f"[catalog] Generating ideas for category: {cat_name}")

        ideas = _generate_ideas_for_category(
            cat_id, cat_name, brain, niche_report, approach
        )

        if len(ideas) != 10:
            logger.warning(
                f"[catalog] Expected 10 ideas for {cat_name}, got {len(ideas)}. "
                "This may affect gate pass."
            )

        category = Category(
            id=cat_id,
            name=cat_name,
            rationale=cat_rationale,
            ideas=ideas
        )
        all_categories.append(category)

    # 9. Count total valid ideas
    total_ideas = sum(len(cat.ideas) for cat in all_categories)

    # 10. Gate logic
    gate_passed = (total_ideas == 30)

    if gate_passed:
        logger.info("[catalog] GATE PASSED: 30 valid ideas generated")
    else:
        logger.warning(
            f"[catalog] GATE FAILED: Got {total_ideas} ideas, expected exactly 30. "
            f"Categories: {[len(cat.ideas) for cat in all_categories]}"
        )

    # 11. Build catalog
    catalog = Catalog(
        categories=all_categories,
        approach=approach,
        niche=niche,
        total_ideas=total_ideas,
        gate_passed=gate_passed
    )

    # 12. Save to cache
    _save_catalog_cache(brain, catalog, session_token, gate_passed)

    cache_status = "generated" if regenerate or not _check_catalog_cache(brain, session_token) else "cached"

    return catalog, cache_status
