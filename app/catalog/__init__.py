"""Brand Studio Agent — Catalog Module.

Provides demand validation for niches using public data sources:
- YouTube Data API v3: organic demand, trust barrier, packaging patterns
- pytrends: search trend analysis

All signals are citable with verifiable sources.
"""

from app.catalog.demand import Signal, NicheReport, validate_niche_demand

__all__ = ["Signal", "NicheReport", "validate_niche_demand"]
