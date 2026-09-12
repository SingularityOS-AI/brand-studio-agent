"""Brand Studio Agent — Catalog Module.

Provides demand validation for niches using public data sources:
- YouTube Data API v3: organic demand, trust barrier, packaging patterns
- pytrends: search trend analysis
- LLM (Gemini): pain signal classification, web grounding

All signals are citable with verifiable sources.
"""

from app.catalog.demand import (
    Signal,
    NicheReport,
    NicheResearch,
    validate_niche_demand,
    research_niche,
)

__all__ = [
    "Signal",
    "NicheReport",
    "NicheResearch",
    "validate_niche_demand",
    "research_niche",
]
