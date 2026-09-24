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

# Lyria fallback flag for music generation (Pieza 52 - default false)
AV_ALLOW_LYRIA: bool = os.getenv("AV_ALLOW_LYRIA", "false").lower() in ("true", "1", "yes")

# GenAI location for Vertex AI Client (Pieza 53)
AV_GENAI_LOCATION: str = os.getenv("AV_GENAI_LOCATION", "us-central1")
# Verified with real calls on 2026-09-23: the Gemini 3.x image models 404 in
# us-central1 and only resolve in "global"; Veo 3.1 Lite resolves in us-central1.
AV_IMAGE_LOCATION: str = os.getenv("AV_IMAGE_LOCATION", "global")
AV_VIDEO_LOCATION: str = os.getenv("AV_VIDEO_LOCATION", AV_GENAI_LOCATION)

# Video polling interval and timeout for Veo (Pieza 53)
AV_VIDEO_POLL_INTERVAL: float = float(os.getenv("AV_VIDEO_POLL_INTERVAL", "10.0"))
AV_VIDEO_TIMEOUT_SECONDS: float = float(os.getenv("AV_VIDEO_TIMEOUT_SECONDS", "480.0"))
