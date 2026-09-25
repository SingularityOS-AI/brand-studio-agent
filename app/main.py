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
import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from fastapi import Body, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app.config import settings
from app.guard import guard
from app.auth.supabase_auth import supabase_auth

# Stripe routers (Cobro Real)
from app.billing import router as billing_router
from app.webhooks import router as webhooks_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background worker only if not running inside test environment."""
    if settings.environment != "test" and os.getenv("ENVIRONMENT") != "test":
        from app.audiovisual.worker import start_worker
        start_worker()
    yield
    if settings.environment != "test" and os.getenv("ENVIRONMENT") != "test":
        from app.audiovisual.worker import stop_worker
        await stop_worker()

app = FastAPI(
    title="Brand Studio Agent — Voice API",
    description="AssemblyAI Voice Agent API with Rate Limiting & Session Budget",
    version="1.0.0",
    lifespan=lifespan,
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

    # 5. Mint token from AssemblyAI
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

from pydantic import BaseModel, ValidationError


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


# =============================================================================
# SCRIPTING ENDPOINTS (Piece 32 — Block C: Scripting)
# =============================================================================

from app.scripting.scripts import (
    generate_script,
    audit_script,
    regenerate_scene,
    update_scene_text,
    lock_script,
    confirm_script,
    ScriptStorageError,
    SceneRegenerationInProgressError,
    CREDITS_COST_GENERATE,
    CREDITS_COST_REGENERATE_SCENE,
)
from typing import Literal, Optional


class ScriptGenerateRequest(BaseModel):
    interview_transcript: str
    source_mode: Literal["brand_brain", "raw_footage"] = "brand_brain"
    idea_kind: Optional[str] = None


# BUG 1 (Capitán, verificado en vivo): `body: BaseModel = None` en los
# endpoints de scene/regenerate y scene PATCH declaraba el tipo base sin
# campos -- FastAPI parseaba el JSON a un modelo vacío y `body.model_dump()`
# siempre daba `{}`, así que `instruction`/`spoken_text` llegaban vacíos y
# el endpoint respondía 400 aunque el cliente sí los mandara. Modelos reales
# al estilo de ScriptGenerateRequest arriba.
class SceneRegenerateRequest(BaseModel):
    instruction: Optional[str] = None


class SceneUpdateRequest(BaseModel):
    spoken_text: str


@app.get("/api/script/{idea_id}", response_class=JSONResponse)
async def get_script_endpoint(request: Request, idea_id: str):
    """
    Retrieve script by idea ID.

    This endpoint:
    1. Validates JWT authentication
    2. Checks for cached script from previous generation
    3. Returns script with audit findings
    4. Returns 404 if script not yet generated

    No cost to retrieve cached content.
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

    from app.scripting.scripts import _check_script

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    if not script:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Script not yet generated for idea {idea_id}",
                "hint": "Call POST /api/script/generate to create script (10 credits)"
            }
        )

    return JSONResponse(content={"script": script.model_dump(mode="json")})


@app.post("/api/script/generate", response_class=JSONResponse)
async def generate_script_endpoint(request: Request, body: ScriptGenerateRequest):
    """
    Generate a script from an approved catalog idea.

    This endpoint:
    1. Validates JWT authentication
    2. Checks if catalog is locked (catalog_locked=True required)
    3. Verifies idea exists and is approved
    4. Calls Gemini to generate script with FrameZero, scenes, and audit
    5. Caches result by (session_token, idea_id)
    6. Returns script with 12 audit findings

    Protected by credits - requires 10 credits.
    Requires JWT authentication.
    REQUIRES:
    - BrandBrain to be complete
    - Catalog idea to be approved
    - Catalog to be locked (catalog_locked=True)
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

    # No rate limit - credits serve as protection

    # Extract idea_id from body
    idea_id = request.query_params.get("idea_id")
    if not idea_id:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'idea_id' query parameter"}
        )

    # Debt Pieza 50: raw_footage upload is coming soon - 400 before charging
    if getattr(body, "source_mode", None) == "raw_footage":
        return JSONResponse(
            status_code=400,
            content={"error": "Raw footage upload is coming soon"}
        )

    # BUG B1 (mismo patrón que /api/catalog/generate, 4b273e7): un guion ya
    # guardado para esta idea se devuelve TAL CUAL, sin cobrar y sin volver a
    # llamar al LLM -- antes el endpoint siempre generaba y siempre cobraba
    # aunque ya existiera guion (incluso locked), pisándolo en silencio.
    from app.scripting.scripts import _check_script

    try:
        existing = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if existing:
        remaining_balance = guard.get_remaining_credits(session_token)
        return JSONResponse(content={
            "script": existing.model_dump(mode="json"),
            "cache_status": "hit",
            "credits_remaining": remaining_balance,
        })

    # Check balance BEFORE deducting
    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    if remaining_balance < CREDITS_COST_GENERATE:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Session budget exhausted",
                "credits_remaining": remaining_balance,
                "payment_url": settings.payment_url,
            }
        )

    # Generate script
    try:
        script = await generate_script(
            session_id=session_token,
            idea_id=idea_id,
            interview_transcript=body.interview_transcript,
            source_mode=body.source_mode,
            idea_kind=body.idea_kind,
        )
    except ValueError as e:
        # Validation error - NO CREDIT DEDUCTION
        return JSONResponse(status_code=400, content={"error": str(e)})
    except ScriptStorageError as e:
        # Storage error - NO CREDIT DEDUCTION
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print(f"[ERROR] Script generation error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Script generation failed: {str(e)}"})

    # Deduct credits AFTER success
    remaining = guard.deduct_credits(session_token, amount=CREDITS_COST_GENERATE)

    return JSONResponse(content={
        "script": script.model_dump(mode="json"),
        "cache_status": "generated",
        "credits_remaining": remaining
    })


@app.post("/api/script/{idea_id}/scene/{scene_n}/regenerate", response_class=JSONResponse)
async def regenerate_scene_endpoint(
    request: Request,
    idea_id: str,
    scene_n: int,
    body: dict | None = Body(default=None),
):
    """
    Regenerate a single scene based on instruction.

    This endpoint:
    1. Validates JWT authentication
    2. Checks if script exists and is not locked
    3. Calls Gemini to regenerate the target scene only
    4. Re-runs audit on updated script
    5. Returns updated script

    Protected by credits - requires 2 credits.
    Requires JWT authentication.
    """
    # BUG 2 (Capitán): JWT se valida ANTES que el body -- sin token debe dar
    # 401, nunca 400. `body` se deja `dict | None` en la firma (no el modelo
    # Pydantic estricto) para que FastAPI no dispare su propia validación de
    # 422 antes de que lleguemos siquiera a leer el header de auth.
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # BUG 1 (Capitán): validar el body con el modelo Pydantic real
    # (SceneRegenerateRequest) en vez de `BaseModel = None` -- antes
    # `body.model_dump()` siempre daba `{}` porque BaseModel no tiene
    # campos. `instruction` es opcional.
    try:
        parsed_body = SceneRegenerateRequest(**(body or {}))
    except ValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid request body: {e}"}
        )
    # regenerate_scene() interpola `instruction` directamente en el prompt de
    # Gemini -- si viene None se cae a "" en vez de imprimir literalmente
    # "None" en el prompt.
    instruction = parsed_body.instruction or ""

    # Check balance BEFORE deducting
    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None or remaining_balance < CREDITS_COST_REGENERATE_SCENE:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Session budget exhausted",
                "credits_remaining": remaining_balance or 0
            }
        )

    # Regenerate scene
    try:
        script = await regenerate_scene(
            session_id=session_token,
            idea_id=idea_id,
            scene_n=scene_n,
            instruction=instruction,
        )
    # PIEZA 43: a duplicate in-flight regeneration of the SAME scene is
    # rejected before any Gemini call or credit charge -- surfaced as 409,
    # never charged (checked BEFORE the generic ValueError below, since
    # this is not a ValueError subclass and callers should retry later,
    # not treat it as a validation error).
    except SceneRegenerationInProgressError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    except ValueError as e:
        # Validation error (incl. an invalid Gemini response) -- NO CREDIT
        # DEDUCTION. Nothing was saved (see regenerate_scene docstring).
        return JSONResponse(status_code=400, content={"error": str(e)})
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print(f"[ERROR] Scene regeneration error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Deduct credits AFTER success
    remaining = guard.deduct_credits(session_token, amount=CREDITS_COST_REGENERATE_SCENE)

    return JSONResponse(content={
        "script": script.model_dump(mode="json"),
        "credits_remaining": remaining
    })


@app.patch("/api/script/{idea_id}/scene/{scene_n}", response_class=JSONResponse)
async def update_scene_text_endpoint(
    request: Request,
    idea_id: str,
    scene_n: int,
    body: dict | None = Body(default=None),
):
    """
    Manually update spoken text for a scene.

    This endpoint:
    1. Validates JWT authentication
    2. Checks if script exists and is not locked
    3. Updates the spoken text for the target scene
    4. Re-runs audit on updated script
    5. Returns updated script

    No cost - manual edit.
    Requires JWT authentication.
    """
    # BUG 2 (Capitán): JWT primero -- sin token debe dar 401, nunca 400.
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    # BUG 1 (Capitán): validar el body con el modelo Pydantic real
    # (SceneUpdateRequest) en vez de `BaseModel = None`. `spoken_text` es
    # obligatorio en el modelo pero Pydantic acepta "" como str válido, así
    # que se sigue rechazando explícitamente vacío/solo-espacios con 400.
    try:
        parsed_body = SceneUpdateRequest(**(body or {}))
    except ValidationError:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'spoken_text' in request body"}
        )

    spoken_text = parsed_body.spoken_text.strip()
    if not spoken_text:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'spoken_text' in request body"}
        )

    try:
        # PIEZA 43: update_scene_text is now async (shares the per-idea lock
        # with regenerate_scene so a manual edit can't be lost mid-regen).
        script = await update_scene_text(
            session_id=session_token,
            idea_id=idea_id,
            scene_n=scene_n,
            spoken_text=spoken_text,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    return JSONResponse(content={"script": script.model_dump(mode="json")})


@app.post("/api/script/{idea_id}/lock", response_class=JSONResponse)
async def lock_script_endpoint(request: Request, idea_id: str):
    """
    Lock a script (final state, no further edits allowed).

    This endpoint:
    1. Validates JWT authentication
    2. Checks if script exists and is not already locked
    3. Validates lock rules (has CTA, no critical failures)
    4. Sets script state to 'locked'
    5. Returns locked script

    No cost - lock operation.
    Requires JWT authentication.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    try:
        script = lock_script(session_id=session_token, idea_id=idea_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    return JSONResponse(content={
        "script": script.model_dump(mode="json"),
        "status": "locked"
    })


class ScriptConfirmRequest(BaseModel):
    """Request model for confirming/reviewing a script (Pieza 40)."""
    funnel_stage: Literal["tofu", "mofu", "bofu"]
    recording_format: Literal["selfie_natural", "pov", "dramatization", "teleprompter_clean", "dynamic"]


@app.patch("/api/script/{idea_id}", response_class=JSONResponse)
async def confirm_script_endpoint(
    request: Request,
    idea_id: str,
    body: dict | None = Body(default=None),
):
    """
    Confirm funnel_stage and recording_format for a script (review state).

    PIEZA 40: This endpoint implements the "reviewed" state that was defined
    but never assigned. The founder confirms:
    - funnel_stage (implements decision D5: "Brandy propone, founder confirma")
    - recording_format (implements decision E3: "sistema propone, founder confirma")

    This endpoint:
    1. Validates JWT authentication (401 without token)
    2. Validates request body (422 if invalid values)
    3. Checks if script exists and is not locked
    4. Sets funnel_stage and recording_format
    5. Moves script to "reviewed" state (if draft) or stays reviewed
    6. Returns updated script

    No cost - confirmation is free.
    Requires JWT authentication.
    """
    # BUG 2 (Capitán): JWT primero -- sin token debe dar 401, nunca 400.
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    # Validate body with Pydantic model (422 if invalid)
    try:
        parsed_body = ScriptConfirmRequest(**(body or {}))
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"error": f"Invalid request body: {e}"}
        )

    from app.scripting.scripts import confirm_script, ScriptStorageError

    try:
        script = confirm_script(
            session_id=session_token,
            idea_id=idea_id,
            funnel_stage=parsed_body.funnel_stage,
            recording_format=parsed_body.recording_format,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    return JSONResponse(content={
        "script": script.model_dump(mode="json"),
        "status": "reviewed",
        "credits_remaining": guard.get_remaining_credits(session_token),
    })


# =============================================================================
# AUDIOVISUAL ENDPOINTS (Pieza 50 — Bloque D: Audiovisual Generation)
# =============================================================================

def _scene_has_live_asset(existing_jobs: list[dict[str, Any]], scene_n: int, kind: str) -> bool:
    return any(
        j.get("scene_n") == scene_n
        and j.get("kind") == kind
        and j.get("status") in ("pending", "running", "done")
        for j in existing_jobs
    )


def _enrich_estimate_with_live_assets(
    est: dict[str, Any], existing_jobs: list[dict[str, Any]]
) -> dict[str, Any]:
    credits_pending = 0
    cost_usd_pending = 0.0
    for sc in est.get("scenes", []):
        asset_type = sc.get("asset_type", "a_roll")
        scene_n = sc.get("scene_n")
        if asset_type != "a_roll":
            has_live = _scene_has_live_asset(existing_jobs, scene_n, asset_type)
            sc["has_live_asset"] = has_live
            if not has_live:
                credits_pending += sc.get("credits", 0)
                cost_usd_pending += sc.get("cost_usd", 0.0)
        else:
            sc["has_live_asset"] = False
    est["credits_pending"] = credits_pending
    est["cost_usd_pending"] = round(cost_usd_pending, 4)
    return est


@app.get("/api/audiovisual/{idea_id}/estimate", response_class=JSONResponse)
async def estimate_audiovisual_endpoint(request: Request, idea_id: str):
    """
    Returns credit and cost estimate for audiovisual generation of a locked script.
    409 if script is not locked. Does not charge credits.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    from app.scripting.scripts import _check_script, ScriptStorageError
    from app.audiovisual.pricing import estimate
    from app.audiovisual.jobs import list_jobs

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(
            status_code=404,
            content={"error": f"Script not found for idea {idea_id}"},
        )

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked before estimating audiovisual generation"},
        )

    try:
        est = estimate(script)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    existing_jobs = list_jobs(session_token, idea_id)
    est = _enrich_estimate_with_live_assets(est, existing_jobs)

    return JSONResponse(content=est)


def _ensure_soundtrack_jobs(script: Any, session_token: str, idea_id: str) -> tuple[list[dict[str, Any]], bool]:
    """
    Ensure background music job and SFX jobs exist for a locked script (Pieza 60).
    Idempotent by session:idea:version_tag. Re-enqueues failed music/sfx jobs.
    Returns (soundtrack_jobs, music_created).
    """
    from app.audiovisual.jobs import create_job, list_jobs, mark_cancelled
    from app.audiovisual.sfx import pick_sfx

    script_version = getattr(script, "timestamp", None)
    version_tag = script_version.isoformat() if script_version else (getattr(script, "id", None) or "v1")

    existing_jobs = list_jobs(session_token, idea_id)
    music_idempotency_key = f"{session_token}:{idea_id}:{version_tag}:music"

    existing_music = next((j for j in existing_jobs if j.get("idempotency_key") == music_idempotency_key), None)
    if existing_music and existing_music.get("status") == "failed":
        mark_cancelled(existing_music["id"], error="Re-enqueued soundtrack")

    est_duration = float(script.target_seconds or (script.scenes[-1].end_s if script.scenes else 45.0))
    music_job, music_created = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=None,
        kind="music",
        credits=0,
        cost_usd=0.0,
        input={
            "music_prompt": script.music_prompt,
            "angle": script.angle,
            "phases": [sc.phase for sc in script.scenes],
            "recording_format": script.recording_format,
            "target_seconds": script.target_seconds,
            "duration_s": est_duration,
        },
        idempotency_key=music_idempotency_key,
        return_created=True,
    )

    soundtrack_jobs = [music_job]

    for sc in script.scenes:
        chosen_sfx = pick_sfx(sc)
        if chosen_sfx:
            sfx_key = f"{session_token}:{idea_id}:{version_tag}:{sc.n}:sfx"
            existing_sfx = next((j for j in existing_jobs if j.get("idempotency_key") == sfx_key), None)
            if existing_sfx and existing_sfx.get("status") == "failed":
                mark_cancelled(existing_sfx["id"], error="Re-enqueued sfx")

            sfx_job = create_job(
                session_token=session_token,
                idea_id=idea_id,
                scene_n=sc.n,
                kind="sfx",
                credits=0,
                cost_usd=0.0,
                input={
                    "scene_n": sc.n,
                    "phase": sc.phase,
                    "sound": sc.sound,
                    "sfx_file": chosen_sfx.get("file"),
                    "tag": chosen_sfx.get("tag"),
                    "storage_path": chosen_sfx.get("storage_path"),
                },
                idempotency_key=sfx_key,
            )
            soundtrack_jobs.append(sfx_job)

    return soundtrack_jobs, music_created


@app.post("/api/audiovisual/{idea_id}/soundtrack", response_class=JSONResponse)
async def create_soundtrack_jobs_endpoint(request: Request, idea_id: str):
    """
    Ensures background music and SFX jobs exist for a locked script (Pieza 60).
    Idempotent and free (0 credits).
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    from app.scripting.scripts import _check_script, ScriptStorageError

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(
            status_code=404,
            content={"error": f"Script not found for idea {idea_id}"},
        )

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked before creating soundtrack jobs"},
        )

    jobs, _ = _ensure_soundtrack_jobs(script, session_token, idea_id)
    return JSONResponse(content={"jobs": jobs})


@app.post("/api/audiovisual/{idea_id}/prepare", response_class=JSONResponse)
async def prepare_audiovisual_endpoint(request: Request, idea_id: str):
    """
    Ensures missing asset prompts are generated for a locked script (Pieza 66).
    Free (0 credits) and idempotent.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    from app.scripting.scripts import (
        _check_script,
        _fill_missing_asset_prompts,
        _get_script_lock,
        _save_script,
        ScriptStorageError,
    )

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(
            status_code=404,
            content={"error": f"Script not found for idea {idea_id}"},
        )

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked before preparing asset prompts"},
        )

    async with _get_script_lock(session_token, idea_id):
        script = _check_script(session_token, idea_id)
        if not script:
            return JSONResponse(
                status_code=404,
                content={"error": f"Script not found for idea {idea_id}"},
            )
        changed = await _fill_missing_asset_prompts(script)
        if changed:
            _save_script(script)

    return JSONResponse(content={
        "changed": changed,
        "scenes": [s.model_dump(mode="json") for s in script.scenes],
    })


@app.post("/api/audiovisual/{idea_id}/generate", response_class=JSONResponse)
async def generate_audiovisual_endpoint(request: Request, idea_id: str):
    """
    Launches audiovisual generation for a locked script.
    - Recalculates estimate
    - 409 if not locked
    - 422 if over_ceiling or over_ai_video_limit
    - Charges base (15 credits) once per launch (idempotent by idea_id + script version)
    - Creates asset jobs: one per non-a_roll scene + soundtrack jobs
    - Returns {jobs: [...], credits_remaining}
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    from app.scripting.scripts import _check_script, ScriptStorageError
    from app.audiovisual.pricing import estimate, CREDITS_TABLE, COST_USD_TABLE
    from app.audiovisual.jobs import create_job, list_jobs, mark_cancelled

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(
            status_code=404,
            content={"error": f"Script not found for idea {idea_id}"},
        )

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked before generating audiovisual assets"},
        )

    est = estimate(script)
    if est.get("over_ai_video_limit"):
        return JSONResponse(
            status_code=422,
            content={
                "error": f"AI video limit exceeded: {est['ai_video_count']} video scenes (max 1 allowed)"
            },
        )
    if est.get("over_ceiling"):
        return JSONResponse(
            status_code=422,
            content={
                "error": f"Cost ceiling exceeded: ${est['cost_usd_total']:.2f} USD (max $1.50 USD)"
            },
        )

    from app.audiovisual.spend_guard import AI_KINDS, can_spend

    ai_cost_sum = sum(
        COST_USD_TABLE.get(sc.asset_type, 0.0)
        for sc in script.scenes
        if sc.asset_type in AI_KINDS
    )
    if ai_cost_sum > 0 and not can_spend(ai_cost_sum):
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI generation is paused right now. Switch those scenes to Stock or Motion graphic — they're free.",
                "code": "ai_paused",
            },
        )

    script_version = getattr(script, "timestamp", None)
    version_tag = script_version.isoformat() if script_version else (getattr(script, "id", None) or "v1")
    music_idempotency_key = f"{session_token}:{idea_id}:{version_tag}:music"

    existing_jobs = list_jobs(session_token, idea_id)

    base_cost = CREDITS_TABLE.get("base", 0)
    needed = 0

    for sc in script.scenes:
        if sc.asset_type != "a_roll":
            has_live_job = _scene_has_live_asset(existing_jobs, sc.n, sc.asset_type)
            if not has_live_job:
                needed += CREDITS_TABLE.get(sc.asset_type, 0)

    music_job_exists = any(
        j.get("kind") == "music"
        and j.get("idempotency_key") == music_idempotency_key
        and j.get("status") != "cancelled"
        for j in existing_jobs
    )
    if not music_job_exists:
        needed += base_cost

    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None:
        raise HTTPException(status_code=401, detail="Invalid session")

    if needed > 0 and remaining_balance < needed:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Session budget exhausted",
                "credits_needed": needed,
                "credits_remaining": remaining_balance,
                "payment_url": settings.payment_url,
            },
        )

    from app.scripting.scripts import _get_script_lock, _save_script, _clean_optional_text

    async with _get_script_lock(session_token, idea_id):
        script = _check_script(session_token, idea_id)
        if not script:
            return JSONResponse(
                status_code=404,
                content={"error": f"Script not found for idea {idea_id}"},
            )
        script_changed = False
        for sc in script.scenes:
            if await _ensure_scene_prompt(script, sc):
                script_changed = True
        if script_changed:
            _save_script(script)

    soundtrack_jobs, music_created = _ensure_soundtrack_jobs(script, session_token, idea_id)
    music_job = next((j for j in soundtrack_jobs if j.get("kind") == "music"), None)

    if music_created and base_cost > 0 and music_job:
        try:
            remaining_balance = guard.deduct_credits(session_token, amount=base_cost)
        except Exception as e:
            logger.error(f"[generate] Failed to deduct base credits for {session_token}: {e}")
            mark_cancelled(music_job["id"], error="Launch payment failed")
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_needed": base_cost,
                    "credits_remaining": guard.get_remaining_credits(session_token),
                    "payment_url": settings.payment_url,
                },
            )

    scene_jobs = []
    for sc in script.scenes:
        if sc.asset_type != "a_roll":
            live_job = next(
                (
                    j for j in existing_jobs
                    if j.get("scene_n") == sc.n
                    and j.get("kind") == sc.asset_type
                    and j.get("status") in ("pending", "running", "done")
                ),
                None,
            )
            if live_job:
                scene_jobs.append(live_job)
            else:
                scene_key = f"{session_token}:{idea_id}:{version_tag}:{sc.n}:{sc.asset_type}"
                job = create_job(
                    session_token=session_token,
                    idea_id=idea_id,
                    scene_n=sc.n,
                    kind=sc.asset_type,
                    credits=CREDITS_TABLE.get(sc.asset_type, 0),
                    cost_usd=COST_USD_TABLE.get(sc.asset_type, 0.0),
                    input={
                        "stock_query": _clean_optional_text(sc.stock_query),
                        "visual_prompt": _clean_optional_text(sc.visual_prompt),
                        "on_screen_text": sc.on_screen_text,
                        "spoken_text": sc.spoken_text,
                        "phase": sc.phase,
                        "duration_s": sc.duration_s,
                    },
                    idempotency_key=scene_key,
                )
                scene_jobs.append(job)

    all_jobs_dict = {j["id"]: j for j in (soundtrack_jobs + scene_jobs)}
    return JSONResponse(content={
        "jobs": list(all_jobs_dict.values()),
        "credits_remaining": remaining_balance,
    })


@app.post("/api/audiovisual/{idea_id}/scenes/{scene_n}/regenerate", response_class=JSONResponse)
async def regenerate_audiovisual_scene_endpoint(request: Request, idea_id: str, scene_n: int):
    """
    Regenerates the asset job for a specific non-a_roll scene (Pieza 55).
    - Requires locked script (409 if not locked)
    - Rejects a_roll scenes (400)
    - Validates credit balance against kind credit cost (402 if insufficient)
    - Cancels prior done/failed jobs for this scene
    - Creates new job of same kind with unique idempotency_key
    - For stock: passes exclude_ids of all previously used source_ids in this scene
    - For motion_graphic: increments template_offset to rotate to next template
    - For ai_video: respects max 1 active ai_video per script
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    from app.scripting.scripts import _check_script, ScriptStorageError
    from app.audiovisual.pricing import CREDITS_TABLE, COST_USD_TABLE
    from app.audiovisual.jobs import create_job, list_jobs, mark_cancelled
    import time
    import uuid

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(
            status_code=404,
            content={"error": f"Script not found for idea {idea_id}"},
        )

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked before regenerating assets"},
        )

    target_scene = None
    for sc in (script.scenes or []):
        if getattr(sc, "n", None) == scene_n:
            target_scene = sc
            break

    if not target_scene:
        return JSONResponse(
            status_code=404,
            content={"error": f"Scene {scene_n} not found in script"},
        )

    asset_type = getattr(target_scene, "asset_type", "a_roll")
    if asset_type == "a_roll":
        return JSONResponse(
            status_code=400,
            content={"error": "Cannot regenerate an a_roll scene. Use the recording studio to record a new take."},
        )

    credits_required = CREDITS_TABLE.get(asset_type, 0)
    cost_usd = COST_USD_TABLE.get(asset_type, 0.0)

    from app.audiovisual.spend_guard import AI_KINDS, can_spend

    if asset_type in AI_KINDS and not can_spend(cost_usd):
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI generation is paused right now. Switch those scenes to Stock or Motion graphic — they're free.",
                "code": "ai_paused",
            },
        )

    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None:
        raise HTTPException(status_code=401, detail="Invalid session")

    if remaining_balance < credits_required:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Insufficient credits to regenerate asset",
                "credits_needed": credits_required,
                "credits_remaining": remaining_balance,
                "payment_url": settings.payment_url,
            },
        )

    existing_jobs = list_jobs(session_token, idea_id)

    # Check ai_video limit across active jobs if asset_type == "ai_video"
    if asset_type == "ai_video":
        active_ai_videos = [
            j for j in existing_jobs
            if j.get("kind") == "ai_video"
            and j.get("status") in ("pending", "running", "done")
            and j.get("scene_n") != scene_n
        ]
        if len(active_ai_videos) >= 1:
            return JSONResponse(
                status_code=422,
                content={"error": "AI video limit reached (maximum 1 active AI video allowed per script)"},
            )

    scene_jobs = [
        j for j in existing_jobs
        if j.get("scene_n") == scene_n and j.get("kind") == asset_type
    ]

    # A job already in flight for this scene means a second request (double
    # click, retry) would run and charge the same asset twice.
    if any(j.get("status") in ("pending", "running") for j in scene_jobs):
        return JSONResponse(
            status_code=409,
            content={"error": "This scene is already being generated. Wait for it to finish."},
        )

    # For stock: pass exclude_ids of already used source_ids
    exclude_ids = []
    if asset_type == "stock":
        for j in scene_jobs:
            out = j.get("output") or {}
            sid = out.get("source_id")
            if sid and str(sid) not in exclude_ids:
                exclude_ids.append(str(sid))
            inp = j.get("input") or {}
            for prev_ex in inp.get("exclude_ids") or []:
                if str(prev_ex) not in exclude_ids:
                    exclude_ids.append(str(prev_ex))

    # For motion_graphic: pass template_offset (+1 each time)
    template_offset = 0
    if asset_type == "motion_graphic":
        highest_offset = -1
        for j in scene_jobs:
            inp = j.get("input") or {}
            offset_val = inp.get("template_offset")
            if offset_val is not None:
                try:
                    highest_offset = max(highest_offset, int(offset_val))
                except (ValueError, TypeError):
                    pass
            elif j.get("status") in ("done", "failed"):
                highest_offset = max(highest_offset, 0)
        template_offset = (highest_offset + 1) if highest_offset >= 0 else 1

    # Mark prior done/failed jobs for this scene as cancelled (do not delete)
    for j in scene_jobs:
        if j.get("status") in ("done", "failed"):
            mark_cancelled(j["id"], error="Regenerated by user")

    from app.scripting.scripts import _get_script_lock, _save_script, _clean_optional_text

    async with _get_script_lock(session_token, idea_id):
        script = _check_script(session_token, idea_id)
        if script:
            target_scene = next((sc for sc in (script.scenes or []) if getattr(sc, "n", None) == scene_n), target_scene)
            if target_scene and await _ensure_scene_prompt(script, target_scene):
                _save_script(script)

    input_data = {
        "stock_query": _clean_optional_text(getattr(target_scene, "stock_query", None)),
        "visual_prompt": _clean_optional_text(getattr(target_scene, "visual_prompt", None)),
        "on_screen_text": getattr(target_scene, "on_screen_text", None),
        "spoken_text": getattr(target_scene, "spoken_text", None),
        "phase": getattr(target_scene, "phase", None),
        "duration_s": getattr(target_scene, "duration_s", 5.0),
    }
    if asset_type == "stock":
        input_data["exclude_ids"] = exclude_ids
    elif asset_type == "motion_graphic":
        input_data["template_offset"] = template_offset

    nonce = uuid.uuid4().hex[:8]
    ts = int(time.time())
    idempotency_key = f"{session_token}:{idea_id}:scene_{scene_n}:{asset_type}:regen:{ts}_{nonce}"

    job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=scene_n,
        kind=asset_type,
        credits=credits_required,
        cost_usd=cost_usd,
        input=input_data,
        idempotency_key=idempotency_key,
    )

    return JSONResponse(content={
        "job": job,
        "status": "pending",
        "credits_remaining": remaining_balance,
    })


class AssetTypePatchRequest(BaseModel):
    asset_type: str


async def _generate_asset_prompt(target_type: str, scene: Any, script_angle: str) -> str:
    spoken_text = getattr(scene, "spoken_text", "") or ""
    on_screen_text = getattr(scene, "on_screen_text", "") or ""
    stock_query = getattr(scene, "stock_query", "") or ""
    b_roll = getattr(scene, "b_roll", "") or ""

    try:
        import asyncio
        from app.audiovisual.genai_client import get_genai_client
        from app.config import settings
        from google.genai import types

        client = get_genai_client()
        model_name = getattr(settings, "vertex_ai_model", "gemini-2.5-flash")

        if target_type in ("ai_image", "ai_video"):
            system_instruction = (
                "Write a single visual prompt description in English, max 40 words, for an image or 6 s clip, "
                "vertical 9:16, no text/letters/logos, no identifiable real faces of people."
            )
            contents = (
                f"Angle: {script_angle}\n"
                f"Spoken text: {spoken_text}\n"
                f"On-screen text: {on_screen_text}\n"
                f"Stock query: {stock_query}\n"
                f"B-roll: {b_roll}\n"
            )
        elif target_type == "stock":
            system_instruction = (
                "Reply with ONLY 2 to 5 English search words separated by spaces for Pexels stock video. "
                "No list, no numbering, no quotes, no explanation."
            )
            contents = f"On-screen text: {on_screen_text}\nB-roll: {b_roll}\nSpoken text: {spoken_text}"
        else:
            return ""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.4,
        )
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            ),
            timeout=8.0,
        )
        raw_text = (getattr(resp, "text", "") or "").strip()
        if target_type == "stock":
            from app.scripting.scripts import _sanitize_stock_query
            sanitized = _sanitize_stock_query(raw_text)
            if sanitized:
                return sanitized
        elif target_type in ("ai_image", "ai_video"):
            lines = raw_text.splitlines()
            if lines and lines[0].strip().endswith(":"):
                lines = lines[1:]
            clean_str = "\n".join(lines).strip()
            paragraphs = [p.strip() for p in clean_str.split("\n\n") if p.strip()]
            first_para = paragraphs[0] if paragraphs else ""
            cleaned_text = first_para.strip('"').strip("'").strip()
            if cleaned_text:
                return cleaned_text[:400]
    except Exception as e:
        logger.warning(f"[patch_scene_asset_type] LLM prompt generation failed: {e}")

    # Fallback determinista (Pieza 66: single source of truth in scripts.py)
    from app.scripting.scripts import _fallback_stock_query, _fallback_visual_prompt
    if target_type in ("ai_image", "ai_video"):
        return _fallback_visual_prompt(scene)
    elif target_type == "stock":
        return _fallback_stock_query(scene)
    return ""


async def _ensure_scene_prompt(script: Any, scene: Any) -> bool:
    """
    Ensure visual_prompt or stock_query are generated and clean if missing or 'null' (Pieza 60).
    Returns True if scene was modified.
    """
    from app.scripting.scripts import _clean_optional_text

    asset_type = getattr(scene, "asset_type", "a_roll")
    changed = False

    if asset_type in ("ai_image", "ai_video"):
        cleaned_prompt = _clean_optional_text(getattr(scene, "visual_prompt", None))
        if cleaned_prompt is None:
            generated_prompt = await _generate_asset_prompt(asset_type, scene, script.angle)
            scene.visual_prompt = _clean_optional_text(generated_prompt) or generated_prompt
            changed = True
    elif asset_type == "stock":
        cleaned_query = _clean_optional_text(getattr(scene, "stock_query", None))
        if cleaned_query is None:
            generated_query = await _generate_asset_prompt("stock", scene, script.angle)
            scene.stock_query = _clean_optional_text(generated_query) or generated_query
            changed = True

    return changed


@app.patch("/api/audiovisual/{idea_id}/scenes/{scene_n}/asset_type", response_class=JSONResponse)
async def patch_scene_asset_type_endpoint(
    request: Request,
    idea_id: str,
    scene_n: int,
    body: AssetTypePatchRequest,
):
    """
    Patch asset_type of a scene in a locked script (Pieza 57).
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    valid_types = {"a_roll", "stock", "ai_image", "ai_video", "motion_graphic"}
    new_asset_type = body.asset_type
    if new_asset_type not in valid_types:
        return JSONResponse(
            status_code=422,
            content={"error": f"Invalid asset_type '{new_asset_type}'"},
        )

    from app.scripting.scripts import _check_script, _get_script_lock, _save_script, ScriptStorageError
    from app.audiovisual.pricing import estimate, COST_USD_TABLE
    from app.audiovisual.spend_guard import AI_KINDS, can_spend
    from app.audiovisual.jobs import list_jobs

    async with _get_script_lock(session_token, idea_id):
        try:
            script = _check_script(session_token, idea_id)
        except ScriptStorageError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})

        if not script:
            return JSONResponse(
                status_code=404,
                content={"error": f"Script not found for idea {idea_id}"},
            )

        if script.state != "locked":
            return JSONResponse(
                status_code=409,
                content={"error": "Script must be locked before modifying scene asset types"},
            )

        target_scene = None
        for sc in (script.scenes or []):
            if getattr(sc, "n", None) == scene_n:
                target_scene = sc
                break

        if not target_scene:
            return JSONResponse(
                status_code=404,
                content={"error": f"Scene {scene_n} not found in script"},
            )

        current_asset_type = getattr(target_scene, "asset_type", "a_roll")
        if new_asset_type == current_asset_type:
            est = estimate(script)
            existing_jobs = list_jobs(session_token, idea_id)
            est = _enrich_estimate_with_live_assets(est, existing_jobs)
            return JSONResponse(content={
                "scene": target_scene.model_dump(mode="json"),
                "estimate": est,
            })

        # 422 if ai_video and another scene is already ai_video
        if new_asset_type == "ai_video":
            other_ai_video = next(
                (sc for sc in script.scenes if getattr(sc, "n", None) != scene_n and getattr(sc, "asset_type", None) == "ai_video"),
                None,
            )
            if other_ai_video:
                return JSONResponse(
                    status_code=422,
                    content={"error": f"Only 1 AI video per script. Change scene {other_ai_video.n} first."},
                )

        # 503 if AI type and spend limit exceeded
        if new_asset_type in AI_KINDS:
            cost = COST_USD_TABLE.get(new_asset_type, 0.0)
            if not can_spend(cost):
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "AI generation is paused right now. Switch those scenes to Stock or Motion graphic — they're free.",
                        "code": "ai_paused",
                    },
                )

        # 409 if job in flight for scene_n
        existing_jobs = list_jobs(session_token, idea_id)
        scene_jobs = [j for j in existing_jobs if j.get("scene_n") == scene_n]
        if any(j.get("status") in ("pending", "running") for j in scene_jobs):
            return JSONResponse(
                status_code=409,
                content={"error": "This scene is being generated. Wait for it to finish."},
            )

        # Save original asset_type to suggested_asset_type on first change
        if getattr(target_scene, "suggested_asset_type", None) is None:
            target_scene.suggested_asset_type = current_asset_type

        target_scene.asset_type = new_asset_type

        # Generate prompt/query if missing or invalid ("null", etc.)
        await _ensure_scene_prompt(script, target_scene)

        _save_script(script)

        est = estimate(script)
        est = _enrich_estimate_with_live_assets(est, existing_jobs)

        return JSONResponse(content={
            "scene": target_scene.model_dump(mode="json"),
            "estimate": est,
        })


@app.get("/api/audiovisual/{idea_id}/jobs", response_class=JSONResponse)
async def get_audiovisual_jobs_endpoint(request: Request, idea_id: str):
    """
    List asset jobs for an idea, including signed_url if job status is 'done',
    and output_display for music and sfx jobs (Pieza 57).
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    from app.audiovisual.jobs import list_jobs
    from app.audiovisual.storage import signed_url
    from app.audiovisual.music import load_music_library
    from app.audiovisual.sfx import load_sfx_library

    jobs = list_jobs(session_token, idea_id)
    music_lib = load_music_library()
    sfx_lib = load_sfx_library()

    for j in jobs:
        if j.get("status") == "done":
            storage_path = j.get("output", {}).get("storage_path") or j.get("input", {}).get("storage_path")
            if storage_path:
                try:
                    j["signed_url"] = signed_url(storage_path)
                except Exception as e:
                    logger.warning(f"Could not generate signed_url for job {j.get('id')}: {e}")

        kind = j.get("kind")
        status_val = j.get("status")
        out = j.get("output") or {}
        inp = j.get("input") or {}

        if kind == "music" and status_val == "done":
            track_file = out.get("track_file")
            if track_file:
                matched_track = next((t for t in music_lib if t.get("file") == track_file), None)
                j["output_display"] = {
                    "title": matched_track.get("title", track_file) if matched_track else track_file,
                    "author": matched_track.get("author", "") if matched_track else "",
                    "mood": out.get("mood", ""),
                    "energy": out.get("energy", ""),
                    "reason": out.get("reason", ""),
                }
        elif kind == "sfx":
            sfx_file = out.get("file") or inp.get("sfx_file")
            tag = out.get("tag") or inp.get("tag")
            matched_sfx = next((s for s in sfx_lib if s.get("file") == sfx_file), None)
            if not matched_sfx and tag:
                matched_sfx = next((s for s in sfx_lib if tag in [t.lower() for t in s.get("tags", [])]), None)
            title = matched_sfx.get("title") if matched_sfx else (sfx_file or tag or "")
            display_tag = tag or (matched_sfx.get("tags", ["sfx"])[0] if matched_sfx and matched_sfx.get("tags") else "sfx")
            j["output_display"] = {
                "tag": display_tag,
                "title": title,
            }

    return JSONResponse(content={"jobs": jobs})


@app.post("/api/audiovisual/{idea_id}/takes/{scene_n}/upload-url", response_class=JSONResponse)
async def get_take_upload_url_endpoint(request: Request, idea_id: str, scene_n: int):
    """
    Returns signed upload URL for an A-roll scene take.
    - Validates that the script exists and is locked (409 if unlocked, 404 if not found).
    - Validates that the scene exists and is an a_roll scene (404 if not found, 400 if not a_roll).
    - Returns {storage_path, signed_upload_url, token}.
    - Charges 0 credits.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    from app.scripting.scripts import _check_script, ScriptStorageError
    from app.audiovisual.storage import create_signed_upload_url

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(status_code=404, content={"error": f"Script not found for idea {idea_id}"})

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked to record takes"},
        )

    scene = next((s for s in script.scenes if s.n == scene_n), None)
    if not scene:
        return JSONResponse(
            status_code=404,
            content={"error": f"Scene {scene_n} not found in script"},
        )

    ext = "webm"
    if request.query_params.get("ext"):
        ext = request.query_params.get("ext")
    elif request.query_params.get("mime"):
        ext = request.query_params.get("mime")

    try:
        upload_data = create_signed_upload_url(
            session_token=session_token,
            idea_id=idea_id,
            scene_n=scene_n,
            ext=ext,
        )
    except Exception as e:
        logger.error(f"[upload-url] Failed to create signed upload URL: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(content=upload_data)


@app.post("/api/audiovisual/{idea_id}/takes/{scene_n}/commit", response_class=JSONResponse)
async def commit_take_endpoint(request: Request, idea_id: str, scene_n: int):
    """
    Commits an uploaded take for a scene (a_roll or B-roll per Pieza 56):
    - Verifies that storage_path belongs to this founder/idea/scene (403 if invalid).
    - Validates script is locked and scene exists in script.
    - Sets role="on_camera" for a_roll scenes, role="voiceover" for B-roll scenes.
    - Cancels any previous take/transcript jobs for this scene.
    - Creates job 'a_roll_take' with status 'done' (0 credits).
    - Enqueues job 'transcript' with status 'pending' (0 credits).
    - Returns {take_job: ..., transcript_job: ...}.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        body = await request.json()
    except Exception:
        body = {}

    storage_path = body.get("storage_path")
    if not storage_path or not isinstance(storage_path, str):
        return JSONResponse(status_code=400, content={"error": "storage_path is required"})

    mime = body.get("mime", "video/webm")
    duration_s = body.get("duration_s")

    # Security check: verify storage_path prefix belongs to this session_token, idea_id, scene_n
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()[:16]
    expected_prefix = f"{token_hash}/{idea_id}/{scene_n}/"
    if not storage_path.startswith(expected_prefix):
        return JSONResponse(
            status_code=403,
            content={"error": "storage_path does not belong to this user, idea, or scene"},
        )

    from app.scripting.scripts import _check_script, ScriptStorageError
    from app.audiovisual.jobs import create_job, list_jobs, mark_cancelled, mark_done
    from app.audiovisual.storage import signed_url

    try:
        script = _check_script(session_token, idea_id)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if not script:
        return JSONResponse(status_code=404, content={"error": f"Script not found for idea {idea_id}"})

    if script.state != "locked":
        return JSONResponse(
            status_code=409,
            content={"error": "Script must be locked to commit takes"},
        )

    scene = next((s for s in script.scenes if s.n == scene_n), None)
    if not scene:
        return JSONResponse(
            status_code=404,
            content={"error": f"Scene {scene_n} not found in script"},
        )

    role = "on_camera" if (scene.asset_type or "a_roll") == "a_roll" else "voiceover"

    # Cancel previous take & transcript jobs for this scene
    existing_jobs = list_jobs(session_token, idea_id)
    for j in existing_jobs:
        if j.get("scene_n") == scene_n and j.get("kind") in ("a_roll_take", "transcript"):
            if j.get("status") not in ("cancelled", "failed"):
                mark_cancelled(j["id"], error="Replaced by new take")

    # Create a_roll_take in 'done' (0 credits)
    take_job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=scene_n,
        kind="a_roll_take",
        credits=0,
        cost_usd=0.0,
        input={
            "storage_path": storage_path,
            "mime": mime,
            "duration_s": duration_s,
            "role": role,
        },
    )

    take_job = mark_done(
        job_id_or_job=take_job["id"],
        output={
            "storage_path": storage_path,
            "mime": mime,
            "duration_s": duration_s,
            "role": role,
        },
        cost_usd=0.0,
        charged=False,
    )
    try:
        take_job["signed_url"] = signed_url(storage_path)
    except Exception as e:
        logger.warning(f"Could not generate signed_url for take: {e}")

    # Enqueue transcript job (0 credits)
    transcript_job = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=scene_n,
        kind="transcript",
        credits=0,
        cost_usd=0.0,
        input={
            "storage_path": storage_path,
            "take_job_id": take_job["id"],
            "mime": mime,
            "duration_s": duration_s,
        },
    )

    return JSONResponse(content={
        "take_job": take_job,
        "transcript_job": transcript_job,
        "take_job_id": take_job["id"],
        "transcript_job_id": transcript_job["id"],
    })


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
    from app.catalog.ideas import CatalogStorageError

    # 5. Check for cached catalog
    try:
        catalog = ideas._check_catalog_cache(session_token)
    except CatalogStorageError as e:
        # PIEZA 31 (bug B3): fallo real de lectura -- nunca 404 (que dispara
        # regeneración/cobro en el frontend), siempre 503 explícito.
        return JSONResponse(status_code=503, content={"error": str(e)})
    if not catalog:
        return JSONResponse(
            status_code=404,
            content={
                "error": "Catalog not yet generated",
                "hint": "Call POST /api/catalog/generate to create catalog (15 credits)"
            }
        )

    # 6. Attach script states in a single batch query (PIEZA 45)
    from app.scripting.scripts import get_script_states_by_session
    try:
        script_states = get_script_states_by_session(session_token)
    except ScriptStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    for idea in catalog.ideas:
        idea.script_state = script_states.get(idea.id, None)

    catalog_dict = catalog.model_dump(mode="json")
    for idea_dict in catalog_dict.get("ideas", []):
        idea_dict["script_state"] = script_states.get(idea_dict.get("id"), None)

    # 7. Return cached catalog
    return JSONResponse(content={
        "catalog": catalog_dict,
        "cache_status": "hit"
    })


@app.post("/api/catalog/generate", response_class=JSONResponse)
async def generate_catalog_endpoint(request: Request):
    """
    Generate a content catalog with 30 content ideas from brand brain.

    This endpoint:
    1. Validates JWT authentication
    2. Deducts credits (15 credits for catalog generation)
    3. Generates 30 content ideas in 5 master categories
    4. Validates each idea against NicheResearch demand signals
    5. Caches result by hash to prevent duplicate work
    6. Sets gate_passed=True only when valid ideas exist

    Protected by credits (no rate limit).
    Requires JWT authentication.
    REQUIRES:
    - BrandBrain to be complete (9 sections confirmado/completado)
    - Brand Soul to be generated (prerequisite for catalog)
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

    # No rate limit for authorized catalog generation - credits serve as the protection mechanism

    # 4. Generate catalog (main business logic in ideas.py) - VALIDATE BEFORE DEDUCTING CREDITS
    try:
        from app.catalog import ideas
        from app.catalog.ideas import CREDITS_COST, CatalogStorageError

        # PIEZA 31 (bug B1): un catálogo ya guardado (de cualquier tamaño) se
        # devuelve TAL CUAL, sin cobrar y sin volver a llamar al LLM -- antes
        # cache_status se calculaba solo para etiquetar la respuesta pero los
        # créditos se cobraban igual más abajo, sin importar si era "hit".
        try:
            cached = ideas._check_catalog_cache(session_token)
        except CatalogStorageError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})

        if cached:
            remaining_balance = guard.get_remaining_credits(session_token)
            return JSONResponse(content={
                "catalog": cached.model_dump(mode="json"),
                "cache_status": "hit",
                "credits_remaining": remaining_balance,
                "gate_passed": cached.gate_passed
            })

        # PIEZA 31 (bug B2): verificar saldo ANTES de generar -- antes se
        # llamaba al LLM sin chequear créditos y, si el saldo era menor a
        # CREDITS_COST, deduct_credits() lanzaba 402 DESPUÉS de haber
        # gastado el trabajo del LLM y guardado el catálogo; el siguiente
        # GET /api/catalog lo entregaba gratis porque ya estaba persistido.
        remaining_balance = guard.get_remaining_credits(session_token)
        if remaining_balance is None:
            raise HTTPException(status_code=401, detail="Invalid session")
        if remaining_balance < CREDITS_COST:
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Session budget exhausted",
                    "credits_remaining": remaining_balance,
                    "payment_url": settings.payment_url,
                }
            )

        # Add timeout wrapper - max 2 minutes for full catalog generation
        catalog = await asyncio.wait_for(
            ideas.get_or_generate_catalog(session_token),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        # Timeout - NO CREDIT DEDUCTION (generation didn't complete)
        print(f"[ERROR] Catalog generation timeout after 120 seconds for session {session_token}")
        return JSONResponse(
            status_code=504,
            content={"error": "Catalog generation timed out. External APIs may be slow. Please try again."}
        )
    except ValueError as e:
        # Validation errors (missing brain/demand, etc.) - NO CREDIT DEDUCTION
        return JSONResponse(
            status_code=400,
            content={"error": str(e)}
        )
    except CatalogStorageError as e:
        # PIEZA 31 (bug B3): fallo real de persistencia -- nunca se cobra.
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print(f"[ERROR] Catalog generation error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Catalog generation failed: {str(e)}"}
        )

    # 3. Deduct credits ONLY AFTER successful catalog generation
    remaining = guard.deduct_credits(session_token, amount=CREDITS_COST)

    # 5. Return success
    return JSONResponse(content={
        "catalog": catalog.model_dump(mode="json"),
        "cache_status": "generated",
        "credits_remaining": remaining,
        "gate_passed": catalog.gate_passed
    })


@app.post("/api/catalog/idea", response_class=JSONResponse)
async def add_founder_idea_endpoint(request: Request):
    """
    Pieza 29 (punto B) — Agrega una idea manual del fundador al catálogo. Gratis.

    Body JSON:
        title (str, 5-200 chars)
        master_category (str, uno de los 5 IDs de MASTER_CATEGORIES)
        source (str, min 10 chars -- de dónde sale la idea)
        subcategory (str, opcional -- default la primera de la categoría)

    Se parsea el body a mano (no con un modelo Pydantic tipado) para que
    cualquier input inválido devuelva 400 con un mensaje claro, no el 422
    genérico de FastAPI -- input no confiable, trust boundary real.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Body debe ser JSON válido"})

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "Body debe ser un objeto JSON"})

    title = body.get("title")
    master_category = body.get("master_category")
    source = body.get("source")
    subcategory = body.get("subcategory")

    if not isinstance(title, str) or not (5 <= len(title.strip()) <= 200):
        return JSONResponse(status_code=400, content={"error": "title debe ser texto de 5 a 200 caracteres"})
    if not isinstance(master_category, str) or not master_category:
        return JSONResponse(status_code=400, content={"error": "master_category es requerido"})
    if not isinstance(source, str) or len(source.strip()) < 10:
        return JSONResponse(status_code=400, content={"error": "source debe ser texto de al menos 10 caracteres"})
    if subcategory is not None and not isinstance(subcategory, str):
        return JSONResponse(status_code=400, content={"error": "subcategory debe ser texto"})

    from app.catalog.ideas import MASTER_CATEGORIES

    # PIEZA 31 (bug B4): validar subcategory contra las subcategorías
    # permitidas de la categoría elegida ANTES de persistir. `subcategory`
    # es texto libre que termina en innerHTML del frontend (ver
    # buildIdeaCardHTML) -- limitarlo a la lista fija es defensa en
    # profundidad además del escapeHtml del lado del cliente (B4 frontend).
    cat_info_for_validation = next((c for c in MASTER_CATEGORIES if c["id"] == master_category), None)
    if (
        subcategory is not None
        and subcategory.strip()
        and cat_info_for_validation is not None
        and subcategory.strip() not in cat_info_for_validation["subcategories"]
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    f"subcategory inválida para la categoría '{master_category}'. "
                    f"Debe ser una de {cat_info_for_validation['subcategories']}"
                )
            }
        )

    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError
        catalog = ideas.add_founder_idea(
            session_id=session_token,
            title=title.strip(),
            master_category=master_category,
            source=source.strip(),
            subcategory=subcategory
        )
        return JSONResponse(
            status_code=201,
            content={"catalog": catalog.model_dump(mode="json"), "status": "success"}
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


@app.post("/api/catalog/investigate", response_class=JSONResponse)
async def investigate_catalog_endpoint(request: Request):
    """
    Pieza 27 — Dispara la investigación de demanda (25 créditos).
    
    1. Ejecuta research_niche() (Google Trends + YouTube API + Gemini Web Grounding)
    2. Genera 30 ideas distribuidas en 5 categorías maestras fijas.
    3. Retorna catalog + niche_research para la UI visual.
    """
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

    # No rate limit for authorized investigate endpoint - credits serve as the protection mechanism

    INVESTIGATE_COST = 25

    # PIEZA 31 (bug B1): un catálogo ya guardado (de cualquier tamaño) se
    # devuelve TAL CUAL, sin cobrar los 25 créditos y sin repetir
    # research_niche() (~40-90s) -- antes esta ruta siempre re-investigaba y
    # re-cobraba aunque ya existiera un catálogo generado/investigado.
    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError

        existing_catalog = ideas._check_catalog_cache(session_token)
    except CatalogStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    if existing_catalog:
        remaining_balance = guard.get_remaining_credits(session_token)
        return JSONResponse(content={
            "catalog": existing_catalog.model_dump(mode="json"),
            "niche_research": (
                existing_catalog.niche_research.model_dump()
                if existing_catalog.niche_research else None
            ),
            "credits_remaining": remaining_balance,
            "gate_passed": existing_catalog.gate_passed,
            "cache_status": "hit"
        })

    # Bug B1 (Pieza 30): cobrar los 25 créditos ANTES de intentar generar significaba que
    # todo fallo (TypeError garantizado por el bug de _extract_niche, timeout,
    # error del LLM) se llevaba los créditos del usuario sin entregar nada.
    # Se verifica saldo con el helper de solo-lectura (get_remaining_credits)
    # y se cobra recién después de un éxito real, mismo patrón que /generate.
    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    if remaining_balance < INVESTIGATE_COST:
        return JSONResponse(
            status_code=402,
            content={
                "error": "Session budget exhausted",
                "credits_remaining": remaining_balance,
                "payment_url": settings.payment_url,
            }
        )

    try:
        from app.catalog import ideas, demand
        from app.catalog.ideas import CatalogStorageError
        from app.tools.brand_brain.store import get_brand_brain

        brain = get_brand_brain(session_token)
        if not brain:
            raise ValueError("No se encontró BrandBrain para esta sesión")

        diagnostico = brain.get_section("diagnostico").content if brain.get_section("diagnostico") else {}
        icp = brain.get_section("icp").content if brain.get_section("icp") else {}
        charco = brain.get_section("charco").content if brain.get_section("charco") else {}
        # Bug B1: _extract_niche exige 3 argumentos (icp, charco, diagnostico) --
        # llamarla con 2 disparaba un TypeError garantizado en cada request.
        niche = ideas._extract_niche(icp, charco, diagnostico)
        if not niche or len(niche) < 3:
            raise ValueError("No se pudo extraer un nicho válido de BrandBrain")

        # Bug B1: UNA sola llamada a research_niche() -- antes se llamaba aquí
        # y OTRA VEZ dentro de generate_catalog() para el mismo nicho. Se pasa
        # el resultado ya calculado a get_or_generate_catalog para que lo
        # reutilice si necesita generar (si hay cache válida, se ignora).
        niche_research = await asyncio.wait_for(
            demand.research_niche(niche),
            timeout=90.0
        )
        catalog = await asyncio.wait_for(
            ideas.get_or_generate_catalog(session_token, niche_research=niche_research),
            timeout=120.0
        )
    except asyncio.TimeoutError:
        # Bug B1: timeout -> NO se cobran créditos.
        print(f"[ERROR] Catalog investigation timeout for session {session_token}")
        return JSONResponse(
            status_code=504,
            content={"error": "Catalog investigation timed out. External APIs may be slow. Please try again."}
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        # PIEZA 31 (bug B3): fallo real de persistencia -- nunca se cobra.
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print(f"[ERROR] Investigate catalog error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Bug B1: cobrar SOLO tras éxito real.
    try:
        remaining = guard.deduct_credits(session_token, amount=INVESTIGATE_COST)
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

    return JSONResponse(content={
        "catalog": catalog.model_dump(mode="json"),
        "niche_research": niche_research.model_dump(),
        "credits_remaining": remaining,
        "gate_passed": catalog.gate_passed
    })


@app.post("/api/catalog/idea/{idea_id}/accept", response_class=JSONResponse)
async def accept_idea_endpoint(request: Request, idea_id: str):
    """Marca una idea como aceptada (status='approved')."""
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError
        catalog = await ideas.update_idea_status(session_token, idea_id, "approved")
        return JSONResponse(content={"catalog": catalog.model_dump(mode="json"), "status": "success"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


@app.post("/api/catalog/idea/{idea_id}/discard", response_class=JSONResponse)
async def discard_idea_endpoint(request: Request, idea_id: str):
    """Marca una idea como descartada (status='rejected')."""
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError
        catalog = await ideas.update_idea_status(session_token, idea_id, "rejected")
        return JSONResponse(content={"catalog": catalog.model_dump(mode="json"), "status": "success"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


@app.post("/api/catalog/idea/{idea_id}/regenerate", response_class=JSONResponse)
async def regenerate_idea_endpoint(request: Request, idea_id: str):
    """Regenera una sola idea reemplazándola por 3 créditos."""
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Bug B9: cobrar ANTES de intentar regenerar significaba que cualquier
    # error (no ValueError, ej. el "No se pudo generar un reemplazo" que es
    # Exception genérica) se llevaba los 3 créditos sin entregar nada, y
    # además no había handler para 500 -- FastAPI dejaba pasar la excepción
    # cruda. Se verifica saldo primero, se cobra tras éxito, y se capturan
    # ValueError (400) y Exception (500) por separado.
    REGEN_COST = 3
    remaining_balance = guard.get_remaining_credits(session_token)
    if remaining_balance is None or remaining_balance < REGEN_COST:
        return JSONResponse(
            status_code=402,
            content={"error": "Session budget exhausted", "credits_remaining": remaining_balance or 0}
        )

    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError
        new_idea = await ideas.regenerate_single_idea(session_token, idea_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        # PIEZA 31 (bug B3): la idea no quedó persistida -- nunca se cobra.
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        print(f"[ERROR] Regenerate idea error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    remaining = guard.deduct_credits(session_token, amount=REGEN_COST)
    try:
        catalog = ideas._check_catalog_cache(session_token)
    except CatalogStorageError as e:
        # La regeneración ya se cobró y persistió con éxito -- este re-lectura
        # es solo para adjuntar el catálogo completo a la respuesta; si falla,
        # se informa sin catálogo en vez de reventar con un 500 crudo.
        print(f"[ERROR] Regenerate idea: no se pudo releer el catálogo tras guardar: {e}")
        catalog = None
    return JSONResponse(content={
        "idea": new_idea.model_dump(mode="json"),
        "catalog": catalog.model_dump(mode="json") if catalog else None,
        "credits_remaining": remaining
    })


@app.post("/api/catalog/lock", response_class=JSONResponse)
async def lock_catalog_endpoint(request: Request):
    """Bloquea el catálogo si las 30 ideas han sido revisadas."""
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    try:
        from app.catalog import ideas
        from app.catalog.ideas import CatalogStorageError
        catalog = ideas.lock_catalog_session(session_token)
        return JSONResponse(content={
            "catalog_locked": catalog.catalog_locked,
            "catalog": catalog.model_dump(mode="json"),
            "status": "success"
        })
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except CatalogStorageError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


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


# =============================================================================
# MOTION GRAPHIC ENDPOINTS (Pieza 54 — HyperFrames Motion Graphics Preview)
# =============================================================================

@app.get("/api/audiovisual/{idea_id}/motion/{scene_n}")
async def get_motion_graphic_preview(
    request: Request,
    idea_id: str,
    scene_n: int,
):
    """
    Returns HTML preview of motion graphic composition for a scene.

    This endpoint:
    1. Validates JWT authentication
    2. Verifies the motion_graphic job exists and is done
    3. Returns the HTML content with CSP header allowing cdn.jsdelivr.net
    4. Returns 404 if motion graphic not found or not ready
    5. Never returns HTML for another founder's content

    Requires JWT authentication.
    """
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    user_id = supabase_auth.get_user_id(authorization)
    session_token = guard.get_or_create_user_session(user_id)

    from app.audiovisual.motion_graphics import get_motion_html

    html_content, storage_path = get_motion_html(session_token, idea_id, scene_n)

    if html_content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Motion graphic not found for idea {idea_id} scene {scene_n}",
        )

    # Return HTML with CSP header allowing CDN scripts
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;",
        "X-Content-Type-Options": "nosniff",
    }

    return HTMLResponse(content=html_content, headers=headers)


# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register Stripe routers (Cobro Real)
app.include_router(billing_router)
app.include_router(webhooks_router)


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
