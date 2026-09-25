"""Configuration and constants for Bloque E Editing module."""
import os

RENDER_SERVICE_URL = os.getenv("RENDER_SERVICE_URL", "")
RENDER_SERVICE_SECRET = os.getenv("RENDER_SERVICE_SECRET", "")
RENDER_CREDITS = int(os.getenv("RENDER_CREDITS", "20"))
REDRESS_CREDITS = int(os.getenv("REDRESS_CREDITS", "2"))
RAW_PER_HOUR = int(os.getenv("RAW_PER_HOUR", "12"))
GAP_MS = int(os.getenv("GAP_MS", "400"))
PAD_MS = int(os.getenv("PAD_MS", "100"))

_fillers_env = os.getenv("FILLERS")
if _fillers_env:
    FILLERS = frozenset(item.strip() for item in _fillers_env.split(",") if item.strip())
else:
    FILLERS = frozenset({"um", "uh", "eh", "em", "mm", "mmm", "ehh", "hmm"})

RENDER_COST_PER_S = float(os.getenv("RENDER_COST_PER_S", "0.000088"))
INPUT_URL_TTL = int(os.getenv("INPUT_URL_TTL", "1800"))
SHARE_TTL = int(os.getenv("SHARE_TTL", "604800"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "290"))
LLM_TIMEOUT_DRESS = int(os.getenv("LLM_TIMEOUT_DRESS", "20"))
LLM_TIMEOUT_REDRESS = int(os.getenv("LLM_TIMEOUT_REDRESS", "10"))
LLM_TIMEOUT_META = int(os.getenv("LLM_TIMEOUT_META", "15"))
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_BYTES", "47000000"))

EDIT_FIELDS = (
    "timeline",
    "raw_render",
    "dressing",
    "captions",
    "settings",
    "render",
    "metadata",
)
