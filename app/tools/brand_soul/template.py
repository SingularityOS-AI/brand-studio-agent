"""
Template for Brand Soul Document

Defines:
1. Cool Paper palette (production design system)
2. ETAPAS configuration from Segués framework
3. HTML template structure for the long-form prose document

Critical: The template provides the FIXED structure (executive summary,
nine titled chapters, closing note). The chapter prose itself is written by
`app/tools/brand_soul/generator.py` (LLM on a leash, with a deterministic
fallback) — this module only lays it out. The document is consolidated
long-form prose: no JSON-like blocks, no "label: value" lines, no raw field
dumps.
"""

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

ETAPAS_CONFIG: dict[str, dict] = {
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


def get_etapa_context(stage_id: str) -> dict[str, str]:
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


def detect_etapa_from_brand_brain(brand_brain) -> str | None:
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
# HTML TEMPLATE STRUCTURE — long-form prose document
# =============================================================================


def _render_paragraphs(paragraphs: list[str]) -> str:
    return "\n".join(f"            <p>{paragraph}</p>" for paragraph in paragraphs)


def _render_chapter(index: int, chapter: dict) -> str:
    return f"""
        <h2>{index}. {chapter["heading"]}</h2>
{_render_paragraphs(chapter["paragraphs"])}
        <div class="citation">"{chapter["citation"]}"</div>
"""


def build_soul_html(
    executive_summary: str,
    chapters: list[dict],
    closing_note: str,
) -> str:
    """
    Build the complete Brand Soul HTML document as consolidated long-form
    prose: an executive summary, one titled chapter per confirmed section,
    and a closing note.

    Args:
        executive_summary: 120-200 words of prose introducing the document.
        chapters: one dict per section, in display order, each with
            {"heading": str, "paragraphs": list[str], "citation": str}.
            All citations are taken literally from the brand_brain sections
            and inserted verbatim — NOT reworded by the LLM or this function.
        closing_note: short prose explaining how Brandy will use this document.

    Returns:
        Complete HTML document as a string.
    """
    chapters_html = "\n".join(
        _render_chapter(index, chapter) for index, chapter in enumerate(chapters, start=1)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
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

        p {{
            margin-bottom: 16px;
            font-size: 15px;
        }}

        .summary-box {{
            background: linear-gradient(135deg, {CoolPaperPalette.ACCENT}15 0%, {CoolPaperPalette.ACCENT}05 100%);
            border-left: 4px solid {CoolPaperPalette.ACCENT};
            padding: 24px;
            margin-bottom: 24px;
            border-radius: 4px;
        }}

        .summary-box h2 {{
            margin-top: 0;
            border-bottom: none;
            color: {CoolPaperPalette.ACCENT};
        }}

        .summary-box p:last-child {{
            margin-bottom: 0;
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

        .closing-box {{
            background: {CoolPaperPalette.BACKGROUND};
            border: 1px solid {CoolPaperPalette.LINE};
            padding: 24px;
            margin-top: 40px;
            border-radius: 4px;
        }}

        .closing-box h2 {{
            margin-top: 0;
            border-bottom: none;
        }}

        .closing-box p:last-child {{
            margin-bottom: 0;
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

            .summary-box, .closing-box {{
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
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Brand Soul</h1>

        <div class="summary-box">
            <h2>Executive Summary</h2>
{_render_paragraphs([executive_summary])}
        </div>
{chapters_html}
        <div class="closing-box">
            <h2>How Brandy Will Use This</h2>
{_render_paragraphs([closing_note])}
        </div>
    </div>
</body>
</html>
"""

    return html
