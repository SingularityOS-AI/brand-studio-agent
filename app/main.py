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


def _with_session_cookie(response: JSONResponse, session_token: str) -> JSONResponse:
    """Sets the opaque session cookie on any outgoing response. Idempotent —
    safe to call even when the browser already has this exact value."""
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=False,  # Set True in production (HTTPS)
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@app.get("/api/token")
async def mint_temporary_token(request: Request):
    """
    Guarded endpoint: mints a single-use temporary token from AssemblyAI.
    Rate limits by IP, then checks session budget before minting.
    Opaque session token stored in httpOnly cookie.
    """
    # 1. Rate limit check by IP
    client_ip = request.client.host
    guard.check_rate_limit(
        client_ip,
        max_requests_per_minute=settings.rate_limit_requests_per_minute
    )

    # 2. Get or create session from cookie
    session_token = request.cookies.get("session_token")
    if not session_token or not guard.get_session(session_token):
        session_token = guard.create_session(initial_credits=settings.initial_session_credits)

    # 3. Check and deduct budget
    try:
        remaining = guard.deduct_credits(session_token, amount=1)
    except HTTPException as e:
        # Depleted budget (402)
        if e.status_code == 402:
            return _with_session_cookie(
                JSONResponse(
                    status_code=402,
                    content={
                        "error": "Session budget exhausted",
                        "credits_remaining": 0,
                        "payment_url": settings.payment_url,
                    },
                ),
                session_token,
            )
        raise

    # 4. Mint token from AssemblyAI (skip in test mode)
    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
    if test_mode:
        # Return mock token for tests
        return _with_session_cookie(
            JSONResponse(
                content={
                    "token": "test_mock_token_assemblyai",
                    "credits_remaining": remaining
                }
            ),
            session_token,
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
            return _with_session_cookie(
                JSONResponse(content={"token": data.get("token"), "credits_remaining": remaining}),
                session_token,
            )

    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to AssemblyAI: {str(exc)}")


@app.get("/api/session", response_class=JSONResponse)
async def get_session_status(request: Request):
    """Returns current session credits."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")

    credits = guard.get_remaining_credits(session_token)
    if credits is None:
        raise HTTPException(status_code=401, detail="Invalid session token")

    return JSONResponse(content={"credits_remaining": credits})


# =============================================================================
# BRAND BRAIN ENDPOINTS (Pieza 2: Bloque A — el Cerebro de Marca)
# =============================================================================

from pydantic import BaseModel


class BrainRetrieveResponse(BaseModel):
    brand_brain: dict
    sections_count: int


@app.get("/api/brain", response_class=JSONResponse)
async def get_brand_brain_handler(request: Request):
    """
    Retrieve brand brain for current session.

    Returns the complete brand brain with all nine sections,
    including their status (propuesto/confirmado) and citations.
    """
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")

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


@app.post("/api/brain/extract", response_class=JSONResponse)
async def extract_brand_brain_handler(request: Request, body: ExtractBrandBrainRequest):
    """
    Extract brand brain sections from conversation transcript.

    This endpoint is called when the AssemblyAI agent invokes the extract_brand_brain tool.
    Validates, persists, and returns the extracted sections.

    Protected by spend_guard to prevent credit exhaustion.
    """
    # 1. Validate session
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")

    session = guard.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # 2. Deduct credits (extraction costs 5 credits)
    try:
        remaining = guard.deduct_credits(session_token, amount=5)
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

    # 4. Return success
    return JSONResponse(content={
        "brand_brain": brain.to_dict(),
        "sections_count": len(brain.sections),
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
    """
    # 1. Validate session from cookie before accepting
    # Browsers send cookies automatically in WebSocket handshake (same-origin)
    session_token = websocket.cookies.get("session_token")
    if not session_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="No session token")
        return

    session = guard.get_session(session_token)
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session token")
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

    # 4. Start transcription engine - only charge credits if this succeeds
    engine = AssemblyAISpeechEngine()
    try:
        engine.start_realtime_transcription(
            on_final_callback=on_final,
            on_partial_callback=on_partial,
            sample_rate=16000,
            language_code=settings.stt_language,
        )
    except RuntimeError as e:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(e))
        return

    # 5. Deduct credits for voice session (only after successful engine start)
    try:
        remaining = guard.deduct_credits(session_token, amount=10)  # Voice session costs 10 credits
    except HTTPException as e:
        if e.status_code == 402:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session budget exhausted")
            return
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Server error")
        return

    # 6. Main loop: receive audio chunks and send transcription results
    listen_task = asyncio.create_task(listen_to_websocket(websocket, engine))
    send_task = asyncio.create_task(send_to_websocket(websocket, result_queue))

    try:
        await asyncio.gather(listen_task, send_task)
    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        print(f"[WebSocket Error] {e}")
    finally:
        # 7. Always clean up
        engine.stop()
        listen_task.cancel()
        send_task.cancel()


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
