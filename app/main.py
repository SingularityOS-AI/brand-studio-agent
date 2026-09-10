"""
 ========================================================================================
BRAND STUDIO AGENT — PIEZA 1 FASTAPI SERVER
 ========================================================================================
Main FastAPI application with:
  - Rate limiting by IP (429 on excess)
  - Session budget enforcement (402 on depletion)
  - Guard layer protecting token minting endpoint
  - server-enforced max_session_duration_seconds
 ========================================================================================
"""

import os
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.guard import guard
from app.auth.supabase_auth import supabase_auth

app = FastAPI(
    title="Brand Studio Agent — Voice API",
    description="AssemblyAI Voice Agent API with Rate Limiting & Session Budget",
    version="1.0.0",
)

# Enable CORS (restrict in production)
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
    """Verifies server status and configuration."""
    return {
        "status": "online",
        "environment": settings.environment,
        "rate_limit_requests_per_minute": settings.rate_limit_requests_per_minute,
        "initial_session_credits": settings.initial_session_credits,
        "max_session_duration_seconds": settings.max_session_duration_seconds,
    }


@app.get("/api/config", response_class=JSONResponse)
async def get_config():
    """
    Returns frontend configuration including Supabase settings and initial credits.
    This endpoint is public - it only contains the publishable key, not the service key.
    """
    return JSONResponse(content={
        "supabase_url": settings.supabase_url,
        "supabase_publishable_key": settings.supabase_publishable_key,
        "initial_session_credits": settings.initial_session_credits,
    })


@app.get("/api/token")
async def mint_temporary_token(request: Request):
    """
    Guarded endpoint: mints a single-use temporary token from AssemblyAI.
    Requires JWT authentication from Google OAuth.
    Rate limits by IP, then checks session budget before minting.
    """
    # 1. Extract and verify JWT from Authorization header
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header. Please login with Google first."
        )

    try:
        user_id = supabase_auth.get_user_id(authorization)
    except HTTPException:
        raise

    # 2. Rate limit check by IP
    client_ip = request.client.host
    guard.check_rate_limit(
        client_ip,
        max_requests_per_minute=settings.rate_limit_requests_per_minute
    )

    # 3. Get or create session for authenticated user
    session_token = guard.get_or_create_user_session(user_id)

    # 4. Check and deduct budget
    try:
        remaining = guard.deduct_credits(session_token, amount=1)
    except HTTPException as e:
        # Depleted budget (402)
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": 0,
                    "payment_url": settings.payment_url,
                },
            )
        raise

    # 5. Mint token from AssemblyAI (skip in test mode)
    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
    if test_mode:
        # Return mock token for tests
        return JSONResponse(
            content={
                "token": "test_mock_token_assemblyai",
                "credits_remaining": remaining
            }
        )

    api_key = settings.assemblyai_api_key
    token_url = (
        f"https://agents.assemblyai.com/v1/token?"
        f"expires_in_seconds=300&"
        f"max_session_duration_seconds={settings.max_session_duration_seconds}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response_aa = await client.get(token_url, headers=headers)

            if response_aa.status_code != 200:
                print(f"[ERROR] Failed to mint token ({response_aa.status_code}): {response_aa.text}")
                raise HTTPException(
                    status_code=response_aa.status_code,
                    detail=f"AssemblyAI Token Minting Error: {response_aa.text}",
                )

            data = response_aa.json()
            # Return token and credits (no session cookie - auth is via JWT)
            return JSONResponse(content={"token": data.get("token"), "credits_remaining": remaining})

    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to AssemblyAI: {str(exc)}")
    except Exception as e:
        print(f"[ERROR] Token minting error: {e}")
        raise HTTPException(status_code=500, detail=f"Token minting failed: {str(e)}")


@app.get("/api/session", response_class=JSONResponse)
async def get_session_status(request: Request):
    """Returns current session credits. Requires JWT authentication."""
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    credits = guard.get_remaining_credits(session_token)
    if credits is None:
        raise HTTPException(status_code=401, detail="Invalid session")

    return JSONResponse(content={"credits_remaining": credits})


@app.post("/api/voice/reserve", response_class=JSONResponse)
async def reserve_voice_credits(request: Request):
    """
    Reserves a block of voice credits for 1 minute of conversation.

    DEBIT BY RESERVATION NOT PROXY:
    The audio flows directly from browser to AssemblyAI (that path already works
    and rewriting it 3 weeks before launch is high risk). The backend charges
    IN ADVANCE, in short renewable blocks.

    BLOCKS OF 1 MINUTE (7.5 CREDITS):
    - Short by design: gives near-exact granularity WITHOUT needing to refund unused time
    - If the browser crashes or user closes tab, billing simply stops renewing
    - No cleanup needed; no detection required

    Returns 402 Payment Required if insufficient balance.

    Requires JWT authentication.
    Rate limited to voice_reserve_rate_limit_per_minute (default: 10/min).
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 2. Rate limit check by IP (this endpoint called every minute during voice sessions)
    client_ip = request.client.host
    guard.check_rate_limit(
        client_ip,
        max_requests_per_minute=settings.voice_reserve_rate_limit_per_minute
    )

    # 3. Deduct credits for 1 minute of voice
    # Round 7.5 to 8 credits because deduct_credits only accepts integers
    # We overcharge slightly rather than undercharge; the difference is negligible ($0.008/min)
    credits_to_deduct = 8  # Rounded up from 7.5
    try:
        remaining = guard.deduct_credits(session_token, amount=credits_to_deduct)
    except HTTPException as e:
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted. Please purchase more credits to continue.",
                    "credits_remaining": session["credits"],
                    "payment_url": settings.payment_url,
                }
            )
        raise

    # 4. Return granted seconds and remaining credits
    return JSONResponse(content={
        "seconds_granted": 60,  # 1 minute
        "credits_remaining": remaining
    })


# =============================================================================
# BRAND BRAIN ENDPOINTS (Pieza 2: Bloque A — el Cerebro de Marca)
# =============================================================================

from pydantic import BaseModel


class BrainRetrieveResponse(BaseModel):
    brand_brain: dict
    sections_count: int


# =============================================================================
# BRAND SOUL ENDPOINTS (Pieza 2: Bloque B — el Alma de Marca)
# =============================================================================

class SoulGenerateResponse(BaseModel):
    html: str
    cache_status: str  # "cached" or "generated"
    credits_remaining: int


@app.get("/api/soul", response_class=JSONResponse)
async def get_brand_soul(request: Request):
    """
    Retrieve cached Brand Soul document for current session.

    Returns the HTML document if it has been previously generated.
    Returns 404 if no document exists yet.
    Requires JWT authentication.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    from app.tools.brand_soul.generator import _check_cache
    from app.tools.brand_brain.store import get_brand_brain

    brain = get_brand_brain(session_token)
    if not brain:
        return JSONResponse(
            status_code=404,
            content={"error": "Brand brain not found for this session"}
        )

    # Check if cached HTML exists.
    # _check_cache exige (brain, session_token): llamarla con un solo argumento
    # lanzaba TypeError y este endpoint devolvia 500 siempre. El bug estuvo
    # dormido mientras nadie llamaba a GET /api/soul desde el frontend.
    cached_html = _check_cache(brain, session_token)
    if not cached_html:
        return JSONResponse(
            status_code=404,
            content={"error": "Brand Soul not generated yet. Call POST /api/soul/generate first."}
        )

    return JSONResponse(content={"html": cached_html})


class SoulGenerateRequest(BaseModel):
    regenerate: bool = False  # Force regeneration even if cached


@app.post("/api/soul/generate", response_class=JSONResponse)
async def generate_brand_soul_handler(request: Request, body: SoulGenerateRequest):
    """
    Generate the Brand Soul document.

    This endpoint:
    1. Validates JWT authentication
    2. Rate limits by IP (stricter limit - 5 requests/min)
    3. Validates that all 9 brand brain sections are confirmed
    4. Checks if cached HTML exists (unless regenerate=True)
    5. Generates new HTML using LLM redaction with citations
    6. Validates all citations exist literally in brain
    7. Caches the result
    8. Returns the HTML document

    Protected by rate limiting and spend_guard - requires 20 credits.
    Requires JWT authentication.
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 2. Rate limit check by IP (stricter than general rate limit - this endpoint calls Vertex AI)
    client_ip = request.client.host
    guard.check_rate_limit(
        client_ip,
        max_requests_per_minute=settings.soul_generate_rate_limit_per_minute
    )

    # 3. Deduct credits (generation costs 20 credits)
    try:
        remaining = guard.deduct_credits(session_token, amount=20)
    except HTTPException as e:
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": session["credits"],
                    "payment_url": settings.payment_url,
                }
            )
        raise

    # 4. Generate document
    from app.tools.brand_soul.generator import (
        generate_brand_soul,
        IncompleteBrainError,
        CitationValidationError,
        SoulGenerationError
    )

    try:
        html, cache_status = generate_brand_soul(session_token)
    except IncompleteBrainError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Brand brain incomplete: {str(e)}"}
        )
    except CitationValidationError as e:
        # Critical: LLM invented citations - don't show the document
        return JSONResponse(
            status_code=500,
            content={"error": f"Citation validation failed: {str(e)}. Document not shown."}
        )
    except SoulGenerationError as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Generation failed: {str(e)}"}
        )
    except Exception as e:
        print(f"[ERROR] Soul generation error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal generation error: {str(e)}"}
        )

    # 4. Return success
    return JSONResponse(content={
        "html": html,
        "cache_status": cache_status,
        "credits_remaining": remaining
    })


@app.get("/api/brain", response_class=JSONResponse)
async def get_brand_brain_handler(request: Request):
    """
    Retrieve brand brain for current session.

    Returns the complete brand brain with all nine sections,
    including their status (propuesto/confirmado) and citations.
    Requires JWT authentication.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    from app.tools.brand_brain.store import get_brand_brain

    brain = get_brand_brain(session_token)
    if not brain:
        return JSONResponse(
            status_code=404,
            content={"error": "Brand brain not found for this session"}
        )

    # Convert to dict for JSON response
    return JSONResponse(content={
        "brand_brain": brain.to_dict(),
        "sections_count": len(brain.sections)
    })


class ExtractBrandBrainRequest(BaseModel):
    transcript: str
    turn_count: int | None = None  # Optional - no turn limit per CEO decision
    tool_result: dict


# =============================================================================
# DEMAND VALIDATION ENDPOINTS (Pieza 3 — Validación de Demanda Automatizada)
# =============================================================================

from app.catalog.demand import validate_niche_demand, NicheReport, clear_demand_cache


@app.get("/api/demand", response_class=JSONResponse)
async def get_demand_validation(request: Request):
    """
    Validate demand for a niche using public data sources.

    This endpoint:
    1. Validates JWT authentication
    2. Rate limits by IP
    3. Deducts credits (10 credits for demand validation)
    4. Analyzes niche using YouTube Data API and pytrends
    5. Sets abort_recommended=True if trend_direction == "baja"
    6. Returns structured NicheReport with citable signals

    Protected by rate limiting and spend_guard - requires 10 credits.
    Requires JWT authentication.
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    # 2. Extract niche from query parameter
    niche = request.query_params.get("niche")
    if not niche:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'niche' query parameter"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 3. Rate limit check
    client_ip = request.client.host
    guard.check_rate_limit(
        client_ip,
        max_requests_per_minute=settings.rate_limit_requests_per_minute
    )

    # 4. Deduct credits (demand validation costs 10 credits)
    try:
        remaining = guard.deduct_credits(session_token, amount=10)
    except HTTPException as e:
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": session["credits"],
                    "payment_url": settings.payment_url,
                }
            )
        raise

    # 5. Validate demand
    try:
        report = await validate_niche_demand(niche=niche, use_cache=True)
    except Exception as e:
        logger.error(f"[demand] Validation error for '{niche}': {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Demand validation failed: {str(e)}"}
        )

    # 6. Return report
    return JSONResponse(content={
        "report": report.model_dump(),
        "credits_remaining": remaining
    })


# =============================================================================
# CATALOG ENDPOINTS (Pieza 4 — Bloque B: Catálogo de 30 Ideas de Contenido)
# =============================================================================

from app.catalog.ideas import generate_catalog


@app.get("/api/catalog", response_class=JSONResponse)
async def get_catalog(request: Request):
    """
    Retrieve the cached content catalog (30 content ideas).

    This endpoint:
    1. Validates JWT authentication
    2. Checks for cached catalog from previous generation
    3. Returns cached catalog with categories and demand signals
    4. Returns 404 if catalog not yet generated

    No cost to retrieve cached content.
    Requires JWT authentication.
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    # 2. Import here to avoid circular dependency
    from app.tools.brand_brain.store import get_brand_brain

    # 3. Check if brain exists
    brain = get_brand_brain(session_token)
    if not brain:
        return JSONResponse(
            status_code=404,
            content={"error": "Brand brain not found. Generate brand brain first."}
        )

    # 4. Import catalog module (this also defines _check_catalog_cache)
    from app.catalog import ideas

    # 5. Check for cached catalog
    catalog = ideas._check_catalog_cache(brain)
    if not catalog:
        return JSONResponse(
            status_code=404,
            content={
                "error": "Catalog not yet generated",
                "hint": "Call POST /api/catalog/generate to create catalog (15 credits)"
            }
        )

    # 6. Return cached catalog
    return JSONResponse(content={
        "catalog": catalog.model_dump(),
        "cache_status": "hit"
    })


@app.post("/api/catalog/generate", response_class=JSONResponse)
async def generate_catalog_endpoint(request: Request):
    """
    Generate a content catalog with 30 content ideas from brand brain.

    This endpoint:
    1. Validates JWT authentication
    2. Rate limits by IP
    3. Deducts credits (TODO: 15 credits for catalog generation)
    4. Generates 3 founder-specific content categories
    5. Generates 10 ideas per category with 4 possible angles
    6. Validates each idea against NicheReport demand signals
    7. Caches result by hash to prevent duplicate work
    8. Sets catalog_gate_passed=True only when exactly 30 valid ideas exist

    Protected by rate limiting and spend_guard.
    Requires JWT authentication.
    Requires BrandBrain to be complete (9 sections propuesto/confirmado).
    Requires NicheReport to exist (from /api/demand validation).
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 2. Check rate limit
    if not guard.check_rate_limit(request.client.host):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )

    # 3. Deduct credits (TODO: CEO said 15 credits, verify cost)
    from app.catalog.ideas import CREDITS_COST
    try:
        remaining = guard.deduct_credits(session_token, amount=CREDITS_COST)
    except HTTPException as e:
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": session["credits"],
                    "payment_url": settings.payment_url,
                }
            )
        raise

    # 4. Generate catalog (main business logic in ideas.py)
    try:
        catalog, cache_status = generate_catalog(session_token)
    except ValueError as e:
        # Validation errors (missing brain/demand, etc.)
        return JSONResponse(
            status_code=400,
            content={"error": str(e)}
        )
    except Exception as e:
        print(f"[ERROR] Catalog generation error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Catalog generation failed: {str(e)}"}
        )

    # 5. Return success
    return JSONResponse(content={
        "catalog": catalog.model_dump(),
        "cache_status": cache_status,
        "credits_remaining": remaining,
        "gate_passed": catalog.gate_passed
    })


@app.post("/api/brain/extract", response_class=JSONResponse)
async def extract_brand_brain_handler(request: Request, body: ExtractBrandBrainRequest):
    """
    Extract brand brain sections from conversation transcript.

    This endpoint is called when the AssemblyAI agent invokes the extract_brand_brain tool.
    Validates, persists, and returns the extracted sections.

    Protected by spend_guard to prevent credit exhaustion.
    Requires JWT authentication.
    """
    # 1. Validate JWT
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 2. Deduct credits (extraction costs 1 credit)
    try:
        remaining = guard.deduct_credits(session_token, amount=1)
    except HTTPException as e:
        if e.status_code == 402:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": session["credits"],
                    "payment_url": settings.payment_url,
                }
            )
        raise

    # 3. Extract and persist
    from app.tools.brand_brain.extractor import extract_and_persist
    from app.tools.brand_brain.extractor import ExtractionError

    try:
        # turn_count is now optional - sections validated by content/citation
        brain = extract_and_persist(
            session_token=session_token,
            transcript=body.transcript,
            turn_count=getattr(body, 'turn_count', None),
            tool_result=body.tool_result
        )
    except ExtractionError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Extraction failed: {str(e)}"}
        )
    except Exception as e:
        print(f"[ERROR] Extraction error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal extraction error: {str(e)}"}
        )

    # 4. Return success with missing_sections for agent guidance
    missing_sections = getattr(brain, '_metadata', {}).get('missing_sections', [])
    # FALLO 3 (PIEZA_17): descartes explicitos, no mudos. Diagnostico para
    # consola del frontend, nunca UI del fundador.
    skipped_sections = getattr(brain, '_metadata', {}).get('skipped_sections', [])
    return JSONResponse(content={
        "brand_brain": brain.to_dict(),
        "sections_count": len(brain.sections),
        "missing_sections": missing_sections,
        "skipped_sections": skipped_sections,
        "credits_remaining": remaining
    })


@app.get("/api/agent-token", response_class=JSONResponse)
async def get_agent_token(request: Request):
    """
    Token EFIMERO para que el navegador abra el WebSocket del Voice Agent.

    NUNCA devuelve la API key maestra. Este endpoint devolvia
    `settings.assemblyai_api_key` en crudo a cualquiera que lo pidiera: sin
    autenticacion, sin guard y sin limite. Cualquier visitante podia copiarla
    de las devtools y gastar sin tope contra la cuenta del dueno, anulando
    por completo el techo de gasto que la Pieza 1 existe para imponer. Es el
    mismo patron de toll fraud que ya costo dinero dos veces en este
    portafolio (Voxniac y neura-sales).

    Delega en /api/token, que ya pasa por rate limit + presupuesto y acuna un
    token de vida corta. Se conserva la ruta para no romper clientes viejos.
    """
    return await mint_temporary_token(request)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serves the browser client."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        content="<h1>Brand Studio Agent</h1><p>static/index.html not found</p>",
        status_code=500,
    )


@app.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket):
    """
    Puente: audio PCM16 16kHz mono del navegador -> wrapper -> AssemblyAI.
    Devuelve al navegador mensajes JSON {"type": "partial"|"final", "text": str}.

    Requires JWT token in query parameter: ?token=<jwt_token>
    Deducts credits per second (7.5 credits/min) instead of fixed amount.
    """
    # 1. Validate JWT token from query parameter before accepting
    query_params = dict(websocket.query_params)
    token = query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing JWT token")
        return

    try:
        user_id = supabase_auth.get_user_id(token)
        session_token = guard.get_or_create_user_session(user_id)
        session = guard.get_session(session_token)
        if not session:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
            return
    except HTTPException as e:
        await websocket.close(code=e.status_code, reason=e.detail)
        return

    # 2. Accept connection first - browser needs this before sending audio
    await websocket.accept()

    # 3. Setup AssemblyAI wrapper with async queue
    from app.voice.wrapper import AssemblyAISpeechEngine

    result_queue = asyncio.Queue()

    # Capture the event loop ASAP for cross-thread callback safety
    loop = asyncio.get_running_loop()

    def on_final(text: str, words):
        """Callback for final transcription results from AssemblyAI thread."""
        # Use call_soon_threadsafe to safely put from SDK's thread to our event loop
        loop.call_soon_threadsafe(result_queue.put_nowait, {"type": "final", "text": text})

    def on_partial(text: str):
        """Callback for partial transcription results from AssemblyAI thread."""
        # Use call_soon_threadsafe to safely put from SDK's thread to our event loop
        loop.call_soon_threadsafe(result_queue.put_nowait, {"type": "partial", "text": text})

    # 4. Start voice session tracking
    guard.start_voice_session(session_token)

    # 5. Start transcription engine
    engine = AssemblyAISpeechEngine()
    try:
        engine.start_realtime_transcription(
            on_final_callback=on_final,
            on_partial_callback=on_partial,
            sample_rate=16000,
            language_code=settings.stt_language,
        )
    except RuntimeError as e:
        guard.end_voice_session(session_token)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(e))
        return

    # 6. Deduct initial credits for voice session startup (1 credit = minimum)
    try:
        remaining = guard.deduct_credits(session_token, amount=1)
    except HTTPException as e:
        if e.status_code == 402:
            guard.end_voice_session(session_token)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session budget exhausted")
            return
        guard.end_voice_session(session_token)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")
        return

    # 7. Main loop: receive audio chunks, send transcription results, and deduct credits periodically
    listen_task = asyncio.create_task(listen_to_websocket(websocket, engine))
    send_task = asyncio.create_task(send_to_websocket(websocket, result_queue))
    credit_task = asyncio.create_task(deduct_voice_credits_loop(websocket, session_token))

    try:
        await asyncio.gather(listen_task, send_task, credit_task, return_exceptions=True)
    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        print(f"[WebSocket Error] {e}")
    finally:
        # 8. Always clean up and finalize credit deduction
        engine.stop()
        listen_task.cancel()
        send_task.cancel()
        credit_task.cancel()
        guard.end_voice_session(session_token)


async def listen_to_websocket(websocket: WebSocket, engine):
    """Receive audio chunks from browser and stream to AssemblyAI."""
    try:
        async for message in websocket.iter_bytes():
            # Audio comes as binary PCM16 16kHz mono
            engine.stream_audio_chunk(message)
    except WebSocketDisconnect:
        raise
    except Exception as e:
        print(f"[Listen Error] {e}")
        raise


async def send_to_websocket(websocket: WebSocket, result_queue: asyncio.Queue):
    """Send transcription results to browser."""
    try:
        while True:
            result = await result_queue.get()
            await websocket.send_json(result)
    except WebSocketDisconnect:
        raise
    except Exception as e:
        print(f"[Send Error] {e}")
        raise


async def deduct_voice_credits_loop(websocket: WebSocket, session_token: str):
    """
    Periodically deduct voice credits every 10 seconds while session is active.
    """
    try:
        while True:
            # Wait 10 seconds between deductions
            await asyncio.sleep(10)
            try:
                remaining = guard.deduct_voice_credits(session_token, interval_seconds=10)
                # Optionally send credit update to client
                await websocket.send_json({"type": "credits_update", "credits_remaining": remaining})
            except HTTPException as e:
                if e.status_code == 402:
                    # Budget exhausted - close connection
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session budget exhausted")
                break
            except Exception as e:
                print(f"[Credit Deduction Error] {e}")
                break
    except asyncio.CancelledError:
        # Task was cancelled - normal cleanup path
        pass
    except Exception as e:
        print(f"[Credit Loop Error] {e}")
        raise


# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 70)
    print("BRAND STUDIO AGENT | Piece 1 - Guarded Voice API")
    print(f"URL Local: http://localhost:{settings.port}")
    print(f"AssemblyAI Key: {'[CONFIGURED OK]' if settings.assemblyai_api_key else '[NOT FOUND]'}")
    print(f"Rate Limit: {settings.rate_limit_requests_per_minute} requests/min per IP")
    print(f"Session Budget: {settings.initial_session_credits} credits")
    print(f"Max Duration: {settings.max_session_duration_seconds}s")
    print("=" * 70 + "\n")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
