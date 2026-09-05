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

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = os.getenv("ENVIRONMENT", "development")

    # Rate Limiting Settings (per IP, requests per minute)
    rate_limit_requests_per_minute: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "30")
    )

    # Session Budget Settings (credits per session)
    initial_session_credits: int = int(
        os.getenv("INITIAL_SESSION_CREDITS", "500")
    )

    # Payment URL for 402 Payment Required response
    payment_url: str = os.getenv("PAYMENT_URL", "https://example.com/upgrade")

    # Session Duration Hard Cutoff (server-enforced, max 3 hours)
    max_session_duration_seconds: int = int(
        os.getenv("MAX_SESSION_DURATION_SECONDS", "3600")
    )  # Default 1 hour


settings = Settings()

# Fail loud if API Key is not configured (skip in test mode)
_test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
if not _test_mode and (not settings.assemblyai_api_key or settings.assemblyai_api_key == "your_assemblyai_api_key_here"):
    raise RuntimeError(
        "ASSEMBLYAI_API_KEY is not configured. "
        "Set it in .env file or environment variable before starting the server."
    )
