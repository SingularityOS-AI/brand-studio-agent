"""
Template for Brand Soul Document

Defines:
1. Cool Paper palette (production design system)
2. ETAPAS configuration from Segués framework
3. HTML template structure for the document

Critical: The template provides the FIXED structure. The LLM only fills
in the content within each block.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Literal
from enum import Enum


# =============================================================================
# COOL PAPER PALETTE — Production Design System
# =============================================================================

class CoolPaperPalette:
    """
    Cool Paper color palette as defined in CONTEXTO_MAESTRO.md §12.

    This is NOT Ink Blue (#0055FF). Cool Paper is softer, more approachable.
    """

    # Backgrounds
    BACKGROUND = "#E7EAF0"          # Light gray-blue foundation
    SURFACE = "#FFFFFF"             # White for cards and content blocks

    # Text
    TEXT_PRIMARY = "#14181F"        # Near-black body text
    TEXT_SECONDARY = "#5C6675"      # Muted gray for supporting text

    # Accents & Borders
    ACCENT = "#2B4CD8"              # Cobalto (NOT Ink Blue)
    LINE = "#D5DAE4"                # Subtle border lines

    # Semantic (optional, keep minimal)
    SUCCESS = "#10B981"
    WARNING = "#F59E0B"
    ERROR = "#EF4444"

    # Typography
    FONT_HEADLINE = "'Space Grotesk', system-ui, sans-serif"
    FONT_BODY = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"


# =============================================================================
# ETAPAS SEGUÉS FRAMEWORK
# =============================================================================
# Based on the 6 levels framework. Each stage has:
# - Name (Spanish)
# - One skill to unlock (the ONLY thing that matters)
# - One thing that's PROHIBITED (what NOT to do)

ETAPAS_CONFIG: Dict[str, Dict] = {
    "invisible": {
        "name": "Invisibilidad",
        "skill_to_unlock": "tu perspectiva — tu cicatriz",
        "prohibited": "optimizar horarios; ninguna hora mágica salva un mensaje que suena como el de todos",
        "description": "Nadie te conoce. Tu perspectiva única es lo único que puede romper el silencio."
    },
    "exploracion": {
        "name": "Exploración",
        "skill_to_unlock": "hablar el idioma de tu charco de dolor",
        "prohibited": "hablar de tu solución; hasta que entiendan el problema, no odian lo que odias",
        "description": "Estás probando qué problema resuena. No hay stillness — hay aprendizaje."
    },
    "precision": {
        "name": "Precisión",
        "skill_to_unlock": "tu postura contraria — lo que el charco acepta pero tú rechazas",
        "prohibited": "generalizar; el nicho es un charco, no el océano",
        "description": "Ya sabes quiénes son. Ahora necesitas posicionarte contra lo que todos aceptan."
    },
    "momentum": {
        "name": "Moméntum",
        "skill_to_unlock": "tu oferta irrechazable — la ecuación de valor que cierra la venta",
        "prohibited": "hacer ofertas blandas; sin riesgo inverso, es una oferta, no irrechazable",
        "description": "La gente te conoce y confía. El momento para convertir esa confianza en ventas."
    },
    "sistema": {
        "name": "Sistema",
        "skill_to_unlock": "tu lead magnet — el primer paso gratis que abre la puerta",
        "prohibited": "pensar en escala; un lead magnet que no convierte no escala no importa",
        "description": "Ya cierras ventas. Ahora necesitas un sistema que traiga leads mientras duermes."
    },
    "dominio": {
        "name": "Dominio",
        "skill_to_unlock": "tu brand journey — el viaje completo de no-problema a cliente",
        "prohibited": "automatizar sin entender; cada etapa del viaje tiene una psicología",
        "description": "El sistema funciona. Ahora dominas cada etapa del viaje del cliente."
    }
}


def get_etapa_context(stage_id: str) -> Dict[str, str]:
    """
    Get the complete context for a specific etapa.

    Args:
        stage_id: The stage ID (e.g., "invisible", "exploracion")

    Returns:
        Dict with keys: name, skill_to_unlock, prohibited, description

    Raises:
        ValueError: If stage_id is not found
    """
    if stage_id not in ETAPAS_CONFIG:
        raise ValueError(f"Unknown stage_id: {stage_id}. Valid stages: {list(ETAPAS_CONFIG.keys())}")
    return ETAPAS_CONFIG[stage_id]


def detect_etapa_from_brand_brain(brand_brain) -> Optional[str]:
    """
    Detect the current business stage from the brand_brain data.

    This is a heuristic based on the "etapa" section content.
    If the section is missing or unclear, returns None.

    Args:
        brand_brain: BrandBrain object

    Returns:
        Stage ID string (e.g., "invisible", "exploracion") or None
    """
    diagnostico_section = brand_brain.get_section("diagnostico")
    if not diagnostico_section:
        return None

    stage_content = diagnostico_section.content.get("etapa", "").lower()

    # Map content to stage IDs
    stage_mapping = {
        "seed": "invisible",
        "startup": "exploracion",
        "growth": "precision",
        "expansion": "momentum",
        "maturity": "sistema"
    }

    for key, stage_id in stage_mapping.items():
        if key in stage_content:
            return stage_id

    return None


# =============================================================================
# HTML TEMPLATE STRUCTURE
# =============================================================================

def build_soul_html(
    summary: str,
    closing: str,
    redacted_sections: Dict[str, str],
    citations: Dict[str, str]
) -> str:
    """
    Build the complete Brand Soul HTML document.

    This function assembles all sections into the final HTML using
    the Cool Paper design system.

    All citations are taken literally from the brand_brain sections
    and inserted verbatim — NOT reworded by the LLM or this function.

    Returns:
        Complete HTML document as a string
    """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brand Soul</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: {CoolPaperPalette.FONT_BODY};
            background-color: {CoolPaperPalette.BACKGROUND};
            color: {CoolPaperPalette.TEXT_PRIMARY};
            line-height: 1.6;
            padding: 40px;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: {CoolPaperPalette.SURFACE};
            padding: 60px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}

        h1 {{
            font-family: {CoolPaperPalette.FONT_HEADLINE};
            font-size: 32px;
            font-weight: 700;
            color: {CoolPaperPalette.TEXT_PRIMARY};
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }}

        h2 {{
            font-family: {CoolPaperPalette.FONT_HEADLINE};
            font-size: 20px;
            font-weight: 600;
            color: {CoolPaperPalette.TEXT_PRIMARY};
            margin-top: 40px;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid {CoolPaperPalette.LINE};
        }}

        h3 {{
            font-family: {CoolPaperPalette.FONT_HEADLINE};
            font-size: 16px;
            font-weight: 600;
            color: {CoolPaperPalette.TEXT_SECONDARY};
            margin-top: 24px;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        p {{
            margin-bottom: 16px;
            font-size: 15px;
        }}

        .etapa-box {{
            background: linear-gradient(135deg, {CoolPaperPalette.ACCENT}15 0%, {CoolPaperPalette.ACCENT}05 100%);
            border-left: 4px solid {CoolPaperPalette.ACCENT};
            padding: 24px;
            margin-bottom: 40px;
            border-radius: 4px;
        }}

        .etapa-title {{
            font-family: {CoolPaperPalette.FONT_HEADLINE};
            font-size: 18px;
            font-weight: 700;
            color: {CoolPaperPalette.ACCENT};
            margin-bottom: 8px;
        }}

        .etapa-skill {{
            font-weight: 600;
            margin-bottom: 8px;
        }}

        .etapa-prohibited {{
            color: {CoolPaperPalette.TEXT_SECONDARY};
            font-style: italic;
            margin-bottom: 12px;
        }}

        .citation {{
            font-family: {CoolPaperPalette.FONT_MONO};
            font-size: 13px;
            color: {CoolPaperPalette.TEXT_SECONDARY};
            background: {CoolPaperPalette.BACKGROUND};
            padding: 12px;
            margin-top: 12px;
            border-radius: 4px;
            border-left: 3px solid {CoolPaperPalette.LINE};
        }}

        .two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-top: 16px;
        }}

        .column {{
            padding: 20px;
            border-radius: 6px;
        }}

        .column-accepted {{
            background: {CoolPaperPalette.BACKGROUND};
            border: 1px solid {CoolPaperPalette.LINE};
        }}

        .column-contrarian {{
            background: linear-gradient(135deg, {CoolPaperPalette.ACCENT}10 0%, {CoolPaperPalette.ACCENT}05 100%);
            border: 1px solid {CoolPaperPalette.ACCENT}30;
        }}

        .column-title {{
            font-family: {CoolPaperPalette.FONT_HEADLINE};
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .column-accepted .column-title {{
            color: {CoolPaperPalette.TEXT_SECONDARY};
        }}

        .column-contrarian .column-title {{
            color: {CoolPaperPalette.ACCENT};
        }}

        .associations-list {{
            list-style: none;
            padding: 0;
        }}

        .associations-list li {{
            padding: 8px 0;
            border-bottom: 1px solid {CoolPaperPalette.LINE};
        }}

        .associations-list li:last-child {{
            border-bottom: none;
        }}

        .associations-desired {{
            color: {CoolPaperPalette.TEXT_PRIMARY};
        }}

        .associations-prohibited {{
            color: {CoolPaperPalette.TEXT_SECONDARY};
            font-style: italic;
        }}

        .equation {{
            background: linear-gradient(90deg, {CoolPaperPalette.ACCENT}10 0%, transparent 100%);
            padding: 24px;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 500;
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}

            .container {{
                box-shadow: none;
                padding: 40px;
                max-width: 100%;
            }}

            .etapa-box {{
                page-break-inside: avoid;
            }}
        }}

        @media (max-width: 600px) {{
            body {{
                padding: 20px;
            }}

            .container {{
                padding: 30px;
            }}

            .two-column {{
                grid-template-columns: 1fr;
                gap: 16px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Brand Soul</h1>

        <h2>Executive summary</h2>
        <p>{summary}</p>

        <h2>Diagnosis</h2>
        <p>{redacted_sections.get('diagnostico', '')}</p>
        <div class="citation">"{citations.get('diagnostico', '')}"</div>

        <h2>Brand Journey</h2>
        <p>{redacted_sections.get('brand_journey', '')}</p>
        <div class="citation">"{citations.get('brand_journey', '')}"</div>

        <h2>Your Pond</h2>
        <p>{redacted_sections.get('charco', '')}</p>
        <div class="citation">"{citations.get('charco', '')}"</div>

        <h2>Ideal Client</h2>
        <p>{redacted_sections.get('icp', '')}</p>
        <div class="citation">"{citations.get('icp', '')}"</div>

        <h2>Contrarian Take</h2>
        <p>{redacted_sections.get('contrarian', '')}</p>
        <div class="citation">"{citations.get('contrarian', '')}"</div>

        <h2>Associations</h2>
        <p>{redacted_sections.get('asociaciones', '')}</p>
        <div class="citation">"{citations.get('asociaciones', '')}"</div>

        <h2>Identity</h2>
        <p>{redacted_sections.get('identidad', '')}</p>
        <div class="citation">"{citations.get('identidad', '')}"</div>

        <h2>Offer</h2>
        <p>{redacted_sections.get('oferta', '')}</p>
        <div class="citation">"{citations.get('oferta', '')}"</div>

        <h2>Lead Magnet</h2>
        <p>{redacted_sections.get('lead_magnet', '')}</p>
        <div class="citation">"{citations.get('lead_magnet', '')}"</div>

        <h2>How Brandy will use this</h2>
        <p>{closing}</p>
    </div>
</body>
</html>
"""

    return html
