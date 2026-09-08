"""
Brand Soul Module

Generates the founder's takeaway document from the completed Brand Brain.

The Brand Soul is the only artifact that leaves the system and circulates
without us. Every assertion must have a literal citation from the brand_brain.

Core invariants:
1. Cannot generate without all 9 sections confirmed
2. Every block in the document has its literal citation attached
3. Citations are taken verbatim from the brain, not reworded by LLM
4. Document is cached—same brain produces same HTML every time
5. Low temperature for deterministic redaction
"""

from app.tools.brand_soul.generator import generate_brand_soul, validate_citations_in_html
from app.tools.brand_soul.template import (
    get_etapa_context,
    ETAPAS_CONFIG,
    CoolPaperPalette
)

__all__ = [
    "generate_brand_soul",
    "validate_citations_in_html",
    "get_etapa_context",
    "ETAPAS_CONFIG",
    "CoolPaperPalette"
]
