"""
Environment and Rate/Budget Limits for Brand Studio Agent.
Fail loud if ASSEMBLYAI_API_KEY is missing.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ruta absoluta al .env de la raiz del repo. Absoluta a proposito: si fuera
# relativa dependeria del directorio desde el que se lanza el servidor, y
# arrancar desde otra carpeta dejaria la key sin cargar en silencio.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# pydantic-settings carga el .env en SU objeto, pero NO lo mete en os.environ.
# guard.py lee SUPABASE_URL/SUPABASE_KEY con os.getenv, y main.py lee TEST_MODE
# igual: sin esto los veian vacios y el guard caia a memoria EN SILENCIO aunque
# Supabase estuviera bien configurado en el .env. Un fallback silencioso de la
# persistencia es como se pierden los creditos de todos sin que nadie se entere.
# override=False: una variable real del entorno (Render) siempre gana al .env.
try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_FILE, override=False)
except ImportError:  # python-dotenv viene con pydantic-settings; si falta, seguimos
    pass


class Settings(BaseSettings):
    # Sin esto, pydantic-settings NO lee el archivo .env: solo mira variables
    # de entorno reales del sistema. Era la causa de "Missing Authorization
    # header" aun teniendo la key escrita en .env.
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AssemblyAI API Key - REQUIRED
    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")

    # Supabase Configuration - REQUIRED for Google OAuth
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = os.getenv("ENVIRONMENT", "development")

    # Rate Limiting Settings (per IP, requests per minute)
    rate_limit_requests_per_minute: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "30")
    )

    # Rate Limiting for Brand Soul Generate (stricter, as it calls Vertex AI)
    soul_generate_rate_limit_per_minute: int = int(
        os.getenv("SOUL_GENERATE_RATE_LIMIT_PER_MINUTE", "5")
    )

    # Rate Limiting for Voice Reserve (called every minute during voice sessions)
    voice_reserve_rate_limit_per_minute: int = int(
        os.getenv("VOICE_RESERVE_RATE_LIMIT_PER_MINUTE", "10")
    )

    # Session Budget Settings (credits per session)
    initial_session_credits: int = int(
        os.getenv("INITIAL_SESSION_CREDITS", "250")
    )

    # Payment URL for 402 Payment Required response
    payment_url: str = os.getenv("PAYMENT_URL", "https://example.com/upgrade")

    # Session Duration Hard Cutoff (server-enforced, max 3 hours)
    max_session_duration_seconds: int = int(
        os.getenv("MAX_SESSION_DURATION_SECONDS", "3600")
    )  # Default 1 hour

    # Platform Spend Cap (USD) - stops granting free credits after this amount
    platform_spend_cap_usd: float = float(
        os.getenv("PLATFORM_SPEND_CAP_USD", "120")
    )  # Default $120 USD

    # Credit Value: 1 credit = $0.01 USD
    credit_value_usd: float = 0.01

    # Voice Credit Cost: 7.5 credits per minute (AssemblyAI charges $4.50/hr)
    voice_credits_per_minute: float = 7.5

    # Speech-to-Text Language Configuration
    stt_language: str = os.getenv("STT_LANGUAGE", "es")  # Default to Spanish

    # Vertex AI Configuration (for Gemini 2.5 Flash-Lite - Brand Soul generation)
    vertex_ai_project_id: str = os.getenv("VERTEX_AI_PROJECT_ID", "")
    vertex_ai_location: str = os.getenv("VERTEX_AI_LOCATION", "us-central1")
    vertex_ai_model: str = "gemini-2.5-flash-lite-preview-06-17"


settings = Settings()

# Fail loud if API Key is not configured (skip in test mode)
_test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
if not _test_mode and (not settings.assemblyai_api_key or settings.assemblyai_api_key == "your_assemblyai_api_key_here"):
    raise RuntimeError(
        "ASSEMBLYAI_API_KEY is not configured. "
        "Set it in .env file or environment variable before starting the server."
    )
