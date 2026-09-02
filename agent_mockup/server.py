"""
========================================================================================
BRAND STUDIO AGENT — VOICE MOCKUP SERVER
========================================================================================
FastAPI Backend Server for AssemblyAI Voice Agent API:
- Mints temporary single-use WebSocket tokens (GET /api/token)
- Protects API Key (Zero client-side credential exposure)
- Serves Dark Tech WebAudio 24kHz Client with Hardware AEC
========================================================================================
"""

import os
import sys
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

# UTF-8 guard for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load secrets from a local .env. Never hardcode absolute paths here:
# this file ships in a public repo.
def load_vault_secrets():
    candidates = [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            if k and not os.getenv(k):
                                os.environ[k] = v
            except Exception:
                pass

load_vault_secrets()

class Settings(BaseSettings):
    assemblyai_api_key: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    host: str = "0.0.0.0"
    port: int = 8088
    environment: str = "development"


settings = Settings()
app = FastAPI(
    title="Brand Studio Agent — Voice Mockup",
    description="AssemblyAI Voice Agent API — WebAudio 24 kHz interactive client",
    version="1.0.0",
)

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)


@app.get("/api/health")
async def health_check():
    """Verifies server status and API Key configuration."""
    api_key_set = bool(settings.assemblyai_api_key and settings.assemblyai_api_key != "your_assemblyai_api_key_here")
    return {
        "status": "online",
        "assemblyai_configured": api_key_set,
        "environment": settings.environment,
        "sample_rate_hz": 24000,
        "protocol": "WebSocket Voice Agent API (wss://agents.assemblyai.com/v1/ws)",
    }


@app.get("/api/token")
async def mint_temporary_token(
    expires_in_seconds: int = 300,
    max_session_duration_seconds: int = 8640,
):
    """
    Mints a single-use temporary token from AssemblyAI Token Endpoint.
    Never exposes the raw API key to client-side browser code.
    """
    api_key = settings.assemblyai_api_key or os.getenv("ASSEMBLYAI_API_KEY", "")
    if not api_key or api_key == "your_assemblyai_api_key_here":
        raise HTTPException(
            status_code=500,
            detail="ASSEMBLYAI_API_KEY is not configured in the environment. Set it in .env or system variables.",
        )

    # Validate integer boundaries
    exp_sec = max(1, min(600, int(expires_in_seconds)))
    max_dur = max(60, min(10800, int(max_session_duration_seconds)))

    token_url = (
        f"https://agents.assemblyai.com/v1/token?"
        f"expires_in_seconds={exp_sec}&"
        f"max_session_duration_seconds={max_dur}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(token_url, headers=headers)
            
            if response.status_code != 200:
                print(f"[ERROR] Failed to mint token ({response.status_code}): {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"AssemblyAI Token Minting Error: {response.text}",
                )
            
            data = response.json()
            return JSONResponse(content={"token": data.get("token")})

    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to AssemblyAI: {str(exc)}")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serves the browser client."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        content="<h1>Brand Studio Agent</h1><p>static/index.html is loading...</p>",
        status_code=200,
    )


# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 70)
    print("BRAND STUDIO AGENT | Voice mockup server")
    print(f"📡 URL Local: http://localhost:{settings.port}")
    print(f"🔑 AssemblyAI Key: {'[CONFIGURADA ✅]' if settings.assemblyai_api_key else '[NO ENCONTRADA ❌]'}")
    print("=" * 70 + "\n")
    uvicorn.run("server:app", host=settings.host, port=settings.port, reload=True)
