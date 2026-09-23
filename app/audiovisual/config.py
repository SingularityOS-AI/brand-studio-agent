"""
Configuration and model identifiers for Audiovisual Generation (Bloque D).
"""
import os

# Model identifiers from environment with defaults from plan-bloque-D.md
AV_IMAGE_MODEL: str = os.getenv("AV_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
AV_VIDEO_MODEL: str = os.getenv("AV_VIDEO_MODEL", "veo-3.1-lite-generate-001")
AV_MUSIC_MODEL: str = os.getenv("AV_MUSIC_MODEL", "lyria-3-clip-preview")

# Guardrails and budget ceilings (Plan Bloque D - A5)
AV_COST_CEILING_USD: float = float(os.getenv("AV_COST_CEILING_USD", "1.50"))
AV_MAX_AI_VIDEO: int = int(os.getenv("AV_MAX_AI_VIDEO", "1"))

# Private storage bucket for binary assets
AV_STORAGE_BUCKET: str = os.getenv("AV_STORAGE_BUCKET", "brand-assets")
