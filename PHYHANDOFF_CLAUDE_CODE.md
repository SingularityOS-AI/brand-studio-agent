# HANDOFF — Claude Code Session (Monday Planning)
## Session Goal: Analizar DE CERO la conversión MVP Wrapper → Voice Agent con tools + memoria

---

## 📍 Current State Snapshot

### What WORKS (v2.2 MVP Wrapper)
- ✅ **Voice Agent API WebSocket** working (AssemblyAI real-time)
- ✅ **AudioWorklet** PCM16 mono 24kHz → correct audio_playback
- ✅ **Transcription** with auto-scroll to bottom
- ✅ **Bug-free** — NO errors in console (`Missing 'audio' field` FIXED)
- ✅ **FastAPI endpoint** `/api/agent-token` returns AssemblyAI key

| File | v2.2 Status | Coverage |
|------|-------------|----------|
| `app/main.py` | ✅ WORKING | FastAPI + agent-token endpoint |
| `app/static/app.js` | ✅ WORKING | Voice API + AudioWorklet + scroll |
| `app/static/index.html` | ✅ WORKING | 3-zone layout (VOZ \| DOCUMENT \| PROD) |
| `app/voice/wrapper.py` | ⚠️ OBSOLETE | Streaming STT-only, NOT used |

### What EXISTS BUT DISCONNECTED
- ⚠️ **Prototype** at `../.claude/design/prototype/` — Full 6-turn interview + 9 sections
  - ✅ `brandy-script.js` — Interview logic GOLD
  - ✅ `index.html` — 92KB mock UI showing complete survey
  - ✅ `api.js` — Mocked endpoints (need to REAL implement)
  - ❌ **NOT connected** to production code

### What DOESN'T EXIST (GAP = 100%)
- ❌ **Session persistence** — Agent amnesia on reload
- ❌ **Supabase connection** — Zero database operations
- ❌ **Tool invocation** — Agent claims tools but NEVER calls them
- ❌ **Bloque A** (9 secciones) — Brand extraction NOT implemented
- ❌ **Bloque B** (30 ideas) — Catalog generation NOT implemented
- ❌ **Bloque C** (Juez + Script) — Viralidad Noir judging NOT implemented
- ❌ **Bloque D** (Render) — HyperFaces integration NOT implemented
- ❌ **LLM Gateway** — No structured JSON output from LLMs
- ❌ **Spend Guard** — Rate limit + budget cap (Pieza 1) NOT implemented

---

## 📚 DOCUMENTS OF TRUTH — Reading Order OBLIGATORY

### 🔴 PRINCIPAL CONTRACT

**1. [`.claude/specs/spec.md`](../.claude/specs/spec.md)** — REV 3.6 FIRMADA
- **Lines 62-78**: Bloque A structure (9 secciones con frameworks)
  - Ralston (Brand Journey: 5 etapas del viaje del cliente)
  - Segués (Etapa del negocio:诊断 del current stage)
  - Noske (Pain point: charco donde cae el cliente)
  - Gray (Oferta + Lead Magnet: Hook → Promise → Delivery)
  - Hormozi (Postura + Asociaciones + Identidad + Lead Magnet final)
- **Lines 86-93**: Bloque B gate duro — "si el catálogo no se sostiene, no se escribe el primer guion"
- **Lines 270-286**: Opción B (DECIDIDA) — Render + Supabase + in-process queue + HyperFrames
- **Non-negotiable mandates**:
  - "El sistema no es un wrapper. Hace."
  - "Ninguna afirmación sin cita literal"
  - "Users enter cold and exit with their own brand"

> ⚠️ BEFORE YOU TOUCH ANY CODE, READ THIS ENTIRE FILE

**2. [`.claude/specs/plan.md`](../.claude/specs/plan.md)** — SELLADO
- **§6**: 10 piezas en orden de ejecución
  - **Pieza 1**: spend_guard (gate duro anti-toll fraud) — MOST CRITICAL BLOCKER
  - **Pieza 2**: Bloque A的一部分 (interrogatorio + 9 secciones)
  - **Pieza 3**: Bloque B parte 1 (catálogo 30 ideas + gate)
  - **Piezas 4-10**: Se escriben al llegar (informed by what happens before)
- **Pattern**: Solda barra → Capitán QA → CEO valida
- **Ambigüedad** (lines 219-220): "Nadie ha medido cuánto cuesta en créditos una vuelta A→D real" — BLOCKS until Pieza 8

### 🔶 TECHNICAL DESIGN

**3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — System Architecture
- **Lines 67-72**: Task assignment table
  - Voice Agent API → Conversation + turn-taking + barge-in
  - Streaming STT → Transcription with word-level timestamps
  - LLM Gateway → Verdict with forced JSON
  - Gemini → Vision-only (footage visual gaps)
- **Lines 78-94**: Async pattern — Tool enqueues → `reply.create` in background
- **Lines 98-118**: Judge contract with forced JSON schema, citations invariant

**4. [`../CONTEXTO_MAESTRO.md`](../CONTEXTO_MAESTRO.md)** — Master Context
- **§12**: Design system
  - Palette: Cool Paper cobalto `#2B4CD8` (NOT Ink Blue)
  - Fonts: Space Grotesk (headlines) + Inter (body) + JetBrains Mono (code)
  - Layout: 3-zone fixed (VOZ 420px \| DOCUMENTO flexible \| PRODUCCIÓN 380px)
- **Estado actual** (line ~100): "CODIGO REAL EN `brand-studio-agent/`: Mockup de AssemblyAI, sin UI. Ninguna pieza despachada todavía"

### 🔶 PROTOTYPE GOLD (Reference ONLY)

**5. [`.claude/design/prototype/brandy-script.js`](../.claude/design/prototype/brandy-script.js)** — Interview Flow GOLD
- Contains complete 6-turn interview logic
- Turn structure: Context → Discovery → Journey → Stage → Pain → Offer → Identity
- **THIS IS the reference for tool implementation**

**6. [`.claude/design/prototype/index.html`](../.claude/design/prototype/index.html)** — UI Mock (92KB)
- Shows 9 sections structure
- Use as data contract reference ONLY (do NOT copy code)

**7. [`.claude/design/prototype/api.js`](../.claude/design/prototype/api.js)`** — Mock Endpoints
- Use as endpoint contract reference
- Migrate these to FastAPI real endpoints

### 🔶 ASSEMBLYAI TECHNICAL REFERENCE

**8. [`../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md`](../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md)** — Full Reference
- **Lines 6-7**: Voice Agent API provides "conversation, tool calling, barge-in"
- **Lines 102-111**: Minimal agent JSON (shows it's config wrapper, NOT full framework)
- **Lines 348-375**: Tool calling pattern
  - Agent sends: `tool.call` (function name, args)
  - Backend responds: `tool.result` (return value)
  - Agent continues conversation with knowledge from tool
- **Lines 375-408**: Async flow with `reply.create`
  - Can send at any time, NOT only during hold
  - Allows background jobs without blocking conversation
- **CRITICAL REGLE**: Never send `input.audio` before `session.ready` event

### 🔴 CRITICAL RESEARCH FINDINGS — COMPLETE AGENT ARCHITECTURE

**9. [`../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md`](../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md)** — 🔥 GOLD STANDARD RESEARCH

This document contains the **DEFINITIVE architecture for the complete cognitive agent system**. It was discovered after spec.md, plan.md, and ARCHITECTURE.md were written, and it SUPERSEDES the simpler single-datbase approach in those documents.

**Why This Matters**:
- ✅ **Three-Layer Memory Architecture** — Redis (short-term) ← pgvector (semantic) ← PostgreSQL relacional (procedural rules)
- ✅ **Google ADK Integration** — Multi-agent system with Agent2Agent (A2A) protocol for cross-language orchestration
- ✅ **Temporal + LangGraph** — Asynchronous execution engine with durable state (NOT just async/callback hacks)
- ✅ **HyperFrames video engine** — Code-based video production (NOT generative diffusion models)
- ✅ **Production-tested patterns** — Anti-toll fraud, circuit breakers, Saga compensation pattern

**Key Innovations Not in Original Spec**:

| Feature | Original Spec | DEEP_RESEARCH (NEW) | Should We Adopt? |
|---------|---------------|-------------------|------------------|
| **Database Architecture** | Single PostgreSQL | **Three-layer: Redis + pgvector + PostgreSQL relacional** | ✅ **YES** — Critical for agent memory |
| **Agent Orchestration** | AssemblyAI Voice API only | **Google ADK + AssemblyAI Voice API** | ✅ **YES** — ADK for strategic planning, AssemblyAI for voice interviews |
| **Async Execution** | `reply.create` pattern only | **Temporal + LangGraph AsyncPostgresSaver** | ✅ **YES** — Production-grade durability |
| **Vector Search** | NOT mentioned | **PostgreSQL pgvector with HNSW index** | ✅ **YES** — Required for semantic similarity search |
| **HyperFrames Integration** | Mentioned in spec | **Detailed implementation + Docker issues** | ✅ **YES** — Avoid --docker flag timeout issue |

**Critical Code Patterns From DEEP_RESEARCH**:

**1. Three-Layer Memory System** (lines 68-140):
```python
# Layer 1: Redis (short-term turns, <2ms)
# Layer 2: pgvector (semantic similarity, 10-50ms)
# Layer 3: PostgreSQL relacional (brand rules, <5ms)

def fetch_unified_brand_context(creator_id: str, query_embedding: list, pg_conn) -> dict:
    context = {
        "short_term_turns": [],    # Redis
        "semantic_memories": [],   # PostgreSQL pgvector HNSW index
        "procedural_rules": {}     # PostgreSQL relational + ACID
    }
    # Retrieve from all 3 layers in parallel
    return context
```

**2. pgvector Schema** (lines 70-88):
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS brand_episodic_memories (
    id BIGSERIAL PRIMARY KEY,
    creator_id VARCHAR(100) NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    memory_content TEXT NOT NULL,
    memory_embedding VECTOR(1536) NOT NULL,  -- OpenAI embeddings
    source_origin VARCHAR(50) NOT NULL,    -- voice_interview, youtube_comment, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast similarity search
CREATE INDEX IF NOT EXISTS episodic_memories_hnsw_idx
ON brand_episodic_memories
USING hnsw (memory_embedding vector_cosine_ops);
```

**3. Temporal + LangGraph Workflow** (lines 196-267):
```python
@workflow.defn
class BrandStudioProductionWorkflow:
    def __init__(self):
        self._human_approved_script: bool | None = None

    @workflow.signal
    def receive_creator_approval(self, approval: bool) -> None:
        self._human_approved_script = approval

    @workflow.run
    async def run(self, input_data: dict) -> dict:
        compensations_stack = []

        try:
            # 1. TTS audio generation
            audio_data = await workflow.execute_activity(
                synthesize_narrator_voice,
                input_data["script_text"],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=COGNITIVE_RETRY_POLICY
            )

            # 2. Durable wait for human approval (no CPU consumed)
            await workflow.wait_condition(
                lambda: self._human_approved_script is not None,
                timeout=timedelta(hours=24)
            )

            # 3. HyperFrames HTML composition
            html_composition = await workflow.execute_activity(
                build_hyperframes_html,
                {**input_data, "audio_url": audio_data["public_url"]},
                start_to_close_timeout=timedelta(minutes=2)
            )

            # 4. Video render
            rendered_video = await workflow.execute_activity(
                render_multimedia_video,
                html_composition["s3_key"],
                start_to_close_timeout=timedelta(minutes=15)
            )

            # 5. Publish (point of no return)
            social_publish = await workflow.execute_activity(
                publish_video_social_channels,
                rendered_video["public_url"]
            )

            return {"status": "COMPLETED", "video_url": rendered_video["public_url"]}

        except Exception as error:
            # Saga pattern: compensate in reverse order
            for action, asset_key in reversed(compensations_stack):
                await workflow.execute_activity(
                    cleanup_temp_s3_resources,
                    {"action": action, "key": asset_key}
                )
            await workflow.execute_activity(
                rollback_api_billing_quota,
                input_data["creator_id"]
            )
            raise error
```

**4. Google ADK Agent** (lines 19-26):
```python
from google.adk import Agent

def extract_market_trends(topic: str) -> dict:
    return {
        "status": "success",
        "topic": topic,
        "keywords": ["Kubernetes", "DevOps", "Platform Engineering"],
        "trend_score": 9.8
    }

root_agent = Agent(
    model='gemini-flash-latest',
    name='personal_brand_planner',
    description="Planifies the strategy for the personal brand",
    instruction="Analyze the user and generate weekly topics using search tools",
    tools=[extract_market_trends]
)
```

**5. AssemblyAI Voice API Integration** (lines 21-48):
```python
import json
import websockets

VOICE_AGENT_WS = "wss://agents.assemblyai.com/v1/ws"
SYSTEM_PROMPT = "You are an expert consultant in personal branding. Interview the user."

async def initiate_voice_discovery(api_key: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    async with websockets.connect(VOICE_AGENT_WS, extra_headers=headers) as ws:
        # First message MUST be session.update to configure
        session_config = {
            "type": "session.update",
            "session": {
                "system_prompt": SYSTEM_PROMPT,
                "greeting": "¡Hola! Ready to help design your brand. What's your specialty?",
                "tools": [],
                "output": {"voice": "ivy"}
            }
        }
        await ws.send(json.dumps(session_config))

        # MUST wait for session.ready before transmitting audio
        async for message in ws:
            event = json.loads(message)
            if event["type"] == "session.ready":
                print("Voice channel established, ready for audio streaming.")
                break
```

**6. HyperFrames Video Engine** (lines 270-286):
```python
import subprocess

def run_hyperframes_compilation(composition_folder: str, output_mp4_path: str):
    cmd = [
        "npx", "hyperframes", "render",
        composition_folder,
        "--output", output_mp4_path,
        "--fps", "30",
        "--quality", "high"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"status": "SUCCESS", "log": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"status": "FAILED", "error": e.stderr}
```

**7. Docker Timeout Issue** (lines 308-309):
> "La ejecución con la bandera --docker puede detenerse al 25% del progreso y fallar por Navigation timeout de 60000 ms. Esto ocurre por un bloqueo en la transferencia de píxeles (ReadPixels GPU stall)."

**FIX**: Use headless rendering without `--docker` flag, or use Vercel Sandbox / Modal for cloud deployment.

**Architecture Comparison: Original Spec vs DEEP_RESEARCH**:

```
┌────────────────────────────────────────────────────────────────────┐
│ ORIGINAL SPEC (simpler)         │ DEEP_RESEARCH (production-grade) │
├─────────────────────────────────┼─────────────────────────────────┤
│ Single PostgreSQL              │ 3-layer: Redis + pgvector + PG    │
│ AssemblyAI Voice API only      │ Google ADK + AssemblyAI Voice API │
│ `reply.create` async pattern   │ Temporal + LangGraph (durable)    │
│ Basic HTTP handlers            │ Workflow engine with Saga pattern│
│ Hand-coded persistence         │ AsyncPostgresSaver (checkpoints) │
│ Manual error handling           │ Automatic retries + compensation  │
└─────────────────────────────────┴─────────────────────────────────┘
```

**Action Required**:
- ⚠️ **READ THIS DOCUMENT FIRST** (lines 1-339) — it contains the PRODUCTION architecture
- ⚠️ **COMPARE with original spec** — identify where DEEP_RESEARCH improves or contradicts spec
- ⚠️ **DECIDIR: Do we adopt Google ADK integration?** (spec doesn't mention it)
- ⚠️ **DECIDIR: Do we implement pgvector for semantic search?** (spec only mentions PostgreSQL)
- ⚠️ **DECIDIR: Do we use Temporal workflow engine?** (spec only mentions "in-process queue")

> 🎯 This is the **MOST IMPORTANT RESEARCH** because it provides a COMPLETE, battle-tested architecture that goes FAR beyond what the original spec envisioned.
- **Lines 6-7**: Voice Agent API provides "conversation, tool calling, barge-in"
- **Lines 102-111**: Minimal agent JSON (shows it's config wrapper, NOT full framework)
- **Lines 348-375**: Tool calling pattern
  - Agent sends: `tool.call` (function name, args)
  - Backend responds: `tool.result` (return value)
  - Agent continues conversation with knowledge from tool
- **Lines 375-408**: Async flow with `reply.create`
  - Can send at any time, NOT only during hold
  - Allows background jobs without blocking conversation
- **CRITICAL REGLE**: Never send `input.audio` before `session.ready` event

### 🔶 RESEARCH OUTSPUTS (Created by Gemini Deep Research)

**9. [`.research_context.md`](.research_context.md)** — Research Summary
- User crisis profile findings
- Tool extraction schema definitions
- Supabase schema suggestions
- LLM capability mapping
- Credit cost estimation
- Tool invocation blueprints

> 🎯 READ THIS AFTER READING 1-8. This tells you what research discovered.

### 🔶 SELF-ANALYSIS

**10. [`ANALISIS_CRUZADO.html`](ANALISIS_CRUZADO.html)** — Spec vs Progress Analysis
- Visual diagram of workflow A→B→C→D vs actual implementation
- Decision summary (4 pending decisions with context)
- Block-by-block gap analysis
- Comparison table: Spec Requires vs Implementation Actual
- Recommendation: Use AssemblyAI as voice layer, NOT Flight SDK

---

## 🎯 SERIES CRITERIA — When_SESSION_SUCCESSFUL

Claude Code session complete when:

1. ✅ All 10 documents above read (1-8 mandatory, 9-10 reference)
2. ✅ Tool invocation architecture defined (how backend tools respond to agent's `tool.call`)
3. ✅ Session persistence pattern documented (how load/save brand_brain to Supabase)
4. ✅ First implementable component identified (likely: `app/tools/brand_extractor.py`)
5. ✅ Risk table populated (toll fraud, amnesia, tool failure, HyperFaces integration cost)
6. ✅ Cost estimation frame defined (when will Pieza 8 measure real credits?)

---

## 🗺️ IMPLEMENTATION ROADMAP (Spec-Driven)

### Phase 1: Foundation (Non-negotiable prerequisites)

**Pieza 1: Spend Guard** — RATE LIMIT + BUDGET CAP (ANTI-TOLL FRAUD)
```
app/spend/guard.py
├── rate_limit_by_ip()      # Limit requests per IP
├── budget_check()          # Check user credits before spend
├── spending_lock()         # Hard cutoff when credits exhausted
└── request/middleware.py   # Apply guard to all spending endpoints
```

**Database + Session Persistence** — FIXES AGENT AMNESIA
```
app/db/
├── supabase_client.py      # Async client
├── schemas/
│   ├── users.py           # user credits, metadata
│   ├── sessions.py        # session_id, transcript, created_at
│   ├── brand_brains.py    # 9 sections JSONB
│   ├── catalogs.py        # 30 ideas, status
│   └── scripts.py         # script, verdict, viral_score
└── migrations/
    └── 001_initial_schema.sql

app/session/
├── middleware.py          # Extract session cookie
├── manager.py             # Load/save sessions
└── cookie.py              # UUID session_id, 30 days expiry
```

### Phase 2: Bloque A Tool Implementation (Start HERE after Phase 1)

**Tool: Brand Extraction** — The KING of tools
```
app/tools/
├── base_tool.py           # Base handler: execute() + tool_callback()
├── brand_brain/
│   ├── extractor.py       # LLM extraction from 6-turn interview
│   ├── validator.py       # Ralston/Hormozi framework checks
│   ├── formats.py         # Ralston, Segués, Noske, Gray, Hormozi formats
│   └── schemas.py         # Pydantic models (BrandBrain, Journey, Stage, etc.)
└── tool_registry.py       # Register tools for Voice Agent API
```

**Voice Agent Tool Contract** — How tools connect to agent
```python
# Schema sent to AssemblyAI during session initialization
tools_schema = {
    "name": "extract_brand_brain",
    "description": "Extract 9 brand sections from the 6-turn conversation transcript",
    "parameters": {
        "transcript": "string (full conversation)",
        "turn_count": "integer (should be 6)"
    }
}

# Tool handler in backend
async def extract_brand_brain(transcript: str, turn_count: int) -> dict:
    # 1. Validate turn_count == 6
    # 2. Extract with LLM (gpt-4o-mini, temperature=0.3)
    # 3. Validate against Ralston/Hormozi frameworks
    # 4. Save to Supabase brand_brains table
    # 5. Return brand_brain JSON for agent acknowledgment
```

### Phase 3: Bloque B Tool Implementation

**Tool: Catalog Generation** — 30 Ideas Generator
```
app/catalog/
├── generator.py       # LLM generates 30 ideas from brand_brain
├── validator.py       # Demand validation (ICP research)
├── researcher.py      # YouTube Data API integration
└── formats.py         # Catalog entry format
```

### Phase 4: Bloque C Tool Implementation

**Tool: Viralidad Noir Judge** + **Tool: Script Writer**
```
app/script/
├── judge.py           # Viralidad Noir scorer (purity + score + axes)
├── writer.py          # Script generator from approved catalog item
├── critic.py          # Citation enforcement (test-only)
└── schemas.py         # Verdict JSON contract
```

### Phase 5: Bloque D Tool Implementation

**Tool: Render Pipeline** + **Tool: Teleprompter**
```
app/render/
├── queue.py           # In-process job queue (from Neural Editor)
├── hyperframes.py     # HyperFaces integration (video-use)
├── artifacts.py       # MP4 + thumbnail + shorts generation
└── teleprompter.py    # Teleprompter logic
```

---

## 🔧 IMPLEMENTATION PATTERN — Tool Calling with AssemblyAI

### 1. Initialize Voice Agent with Tools

```python
# In FastAPI backend
from assemblyai import Client

client = Client(api_key=settings.assemblyai_api_key)

# Create agent with tools
agent = client.voice.agents.create(
    model="claude-3-5-haiku",
    tools=[
        {
            "name": "extract_brand_brain",
            "description": "Extract 9 brand sections from interview",
            "parameters": {
                "transcript": "string",
                "turn_count": "integer"
            }
        },
        {
            "name": "approve_catalog",
            "description": "Approve 30-idea catalog for production",
            "parameters": {
                "catalog_id": "string"
            }
        },
        # ... more tools
    ]
)
```

### 2. Agent Sends `tool.call` (Frontend handles this automatically)

```javascript
// In app/static/app.js (WebSocket message handler)
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // Agent has data.audio (audio response) or data.tool_call
    if (data.type === "tool.call") {
        // AssemblyAI automatically sends this to backend if configured
        console.log("Agent wants to call tool:", data.tool_call);
        // Backend receives this via WebSocket connection
    }
};
```

### 3. Backend Handles `tool.call` (NEW CODE NEEDED HERE)

```python
# In app/tools/tool_registry.py
from assemblyai import VoiceAgent

async def handle_tool_call(tool_call: dict) -> dict:
    """
    AssemblyAI Voice Agent sends tool_call events.
    This handler executes the tool and returns result.

    tool_call structure from AssemblyAI:
    {
        "type": "tool.call",
        "tool": "extract_brand_brain",
        "parameters": {
            "transcript": "...",
            "turn_count": 6
        }
    }
    """
    tool_name = tool_call["tool"]
    parameters = tool_call["parameters"]

    # Route to specific tool handler
    if tool_name == "extract_brand_brain":
        result = await brand_brain_extractor.extract(parameters)
    elif tool_name == "approve_catalog":
        result = await catalog_approver.approve(parameters)
    # ... more tools

    # Return result to AssemblyAI
    return {
        "type": "tool.result",
        "tool": tool_name,
        "result": result
    }
```

### 4. Agent Acknowledges Result (Automatic)

AssemblyAI Voice Agent automatically:
- Receives `tool.result`
- Adds result to conversation context
- Continues speaking with knowledge from tool

### 5. Async Background Jobs with `reply.create`

```python
# In app/render/hyperframes.py
from assemblyai import Client

async def render_video(script_id: str) -> dict:
    """
    Long-running render job (5-10 minutes).
    Use reply.create to send result when ready, NOT hold.
    """
    # 1. Enqueue render job (non-blocking)
    job = render_queue.enqueue(script_id)

    # 2. When render completes (called by worker):
    async def on_render_complete():
        video_url = await hyperframes_client.render(job.script)

        # 3. Send reply.create to inform agent
        client.voice.reply.create(
            agent_id agent.id,
            user_id user_id,
            text=f"Tu video está listo: {video_url}",
            reply_to=job.original_message_id
        )

    return {"status": "enqueued", "job_id": job.id}
```

---

## 🎨 DESIGN SYSTEM — DO NOT IGNORE

From `CONTEXTO_MAESTRO.md` §12:

```css
/* Cool Paper palette -- NOT Ink Blue */
:root {
    --accent: #2B4CD8;      /* Cobalto */
    --accent-light: #5B7CFF;
    --accent-dark: #1E3490;
    
    /* Typography */
    --font-headline: 'Space Grotesk', system-ui, sans-serif;
    --font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-code: 'JetBrains Mono', 'Fira Code', monospace;
}

/* 3-zone fixed layout */
.voice-zone {
    width: 420px;
    height: 100vh;
    overflow-y: auto;
}

.document-zone {
    flex: 1;  /* Flexible middle */
    overflow-y: auto;
}

.production-zone {
    width: 380px;
    height: 100vh;
    overflow-y: auto;
}
```

---

## ⚠️ NON-NEGOTIABLE CONSTRAINTS

1. **NO shortcuts with SQLite** — Supabase PostgreSQL already decided in spec
2. **NO plot twists with Flight SDK** — AssemblyAI puro + FastAPI orchestration
3. **NO ZERO-HARDCODING** — Users enter cold, never seed brand_brain
4. **NO MAGIC without citation** — Every claim in output must have citation source
5. **NO toll fraud** — Pieza 1 spend_guard blocks before any credit spending
6. **NO premature full-stack** — Implement block by block: A → B → C → D
7. **NO skipping prompts** — PIEZA_1_PROMPT.md through PIEZA_3_PROMPT.md exists, find them

---

## 🎯 CRITICAL PATH TO SUCCESS

1. ✅ **Find PIEZA_1_PROMPT.md** — Spend guard implementation prompt
2. ✅ **Find PIEZA_2_PROMPT.md** — Bloque A extraction prompt
3. ✅ **Find PIEZA_3_PROMPT.md** — Bloque B catalog generation prompt
4. ✅ **Design Supabase schema** — Users + Sessions + BrandBrains + Catalogs + Scripts
5. ✅ **Implement Phase 1** — Spend guard + Session + Database connection
6. ✅ **Implement Phase 2** — brand_brain extraction tool (FIRST REAL TOOL)
7. ✅ **Test tool invocation flows** — Agent calls extractor → Backend executes → Saves to Supabase
8. ✅ **Fix amnesia bug** — On reload, agent loads brand_brain from Supabase and says "I know you"
9. ✅ **Measure real credit costs** — Eject in Pieza 8 (first full A→D cycle)
10. ✅ **Implement Phases 3-5** — Complete workflow A→B→C→D

---

## 📊 DECISION MATRICES — What's Already Decided vs What Needs Decision

| Decision | Status | Making | Context |
|----------|--------|--------|---------|
| Architecture (Render + Supabase) | ✅ DECIDED | spec.md Line 270-286 | Opción B NON-NEGOTIABLE |
| Design System (cobalto #2B4CD8) | ✅ DECIDED | CONTEXTO_MAESTRO.md §12 | Cool Paper palette |
| Voice Engine (AssemblyAI) | ✅ DECIDED | spec.md + ARCHITECTURE.md | NOT Flight SDK |
| Session Cookie pattern | ✅ DECIDED | Neural Editor precedent | 30 days expiry |
| In-process queue | ✅ DECIDED | plan.md + ARCHITECTURE.md | From Neural Editor |
| LLM provider (OpenAI vs Claude) | ⚠️ RECOMMENDED | OpenAI gpt-4o-mini | Cost + JSON output |
| Framework Flight SDK | ⚠️ RECOMMENDED NO | NO integration | Adds complexity |
| Pieza 1 spend_guard | ⚠️ RECOMMENDED YES | PIEZA_1_PROMPT.md (find it) | First blocker |

---

## 🔍 SEARCH TASKS — What Claude Code Must Find

### Critical Files NOT Yet Located
1. **`PIEZA_1_PROMPT.md`** — Spend guard implementation prompt
2. **`PIEZA_2_PROMPT.md`** — Bloque A extraction prompt
3. **`PIEZA_3_PROMPT.md`** — Bloque B catalog generation prompt
4. **Prompts directory** — Expected at `../.claude/specs/PROMPTS/` but empty?
5. **Supabase schema file** — May exist in `../.claude/specs/` (search)
6. **Neural Editor precedent** — Session persistence code pattern (search)
7. **Build logs** — To inform framework decision (search)

### Search Commands for Claude Code
```bash
# Find prompt files
find ../.claude/specs/ -name "*PROMPT*" -type f

# Find Supabase schema
find ../.claude/specs/ -name "*supabase*" -type f

# Find Neural Editor precedent
find ../.claude/specs/ -name "*neural*editor*" -type f

# Find session middleware reference (old project)
grep -r "session.*cookie" ../.claude/specs/ --include="*.md"

# Find HyperFaces integration reference
grep -r "hyperframes" ../.claude/specs/ --include="*.md"
```

---

## 🚀 SESSION STRUCTURE — How This Monday Session Should Run

### Phase 1: PROOF OF UNDERSTANDING (10-15 mins)
1. List all 4 workflow blocks (A, B, C, D) with their functions
2. Explain the tool calling pattern (agent → tool.call → backend → tool.result → agent)
3. Explain the session persistence pattern (cookie → Supabase → load on reload)
4. Explain the non-negotiable mandates from spec.md

### Phase 2: DISCOVERY (30-40 mins)
5. Search for PIEZA_1/2/3_PROMPT.md files
6. Search for Supabase schema definition
7. Search for Neural Editor session persistence precedent
8. Analyze prototype JS logic (brandy-script.js) for tool contract

### Phase 3: ARCHITECTURE DECISION (20-30 mins)
9. Confirm: NO Flight SDK integration (keep AssemblyAI puro)
10. Confirm: OpenAI gpt-4o-mini as primary LLM provider
11. Confirm: Supabase PostgreSQL as persistence layer (NOT SQLite)
12. Confirm: spend_guard must be implemented BEFORE any other piece blocks toll fraud

### Phase 4: IMPLEMENTATION BLUEPRINT (30-40 mins)
13. Define tool invocation handler architecture (tool_registry.py structure)
14. Define Supabase schema (CREATE TABLE statements with foreign keys)
15. Define session middleware (extract cookie, load from Supabase, attach to request.state)
16. Define brand_brain extraction tool (LLM prompt + validation logic)

### Phase 5: FIRST IMPLEMENTATION STEP (20-30 mins)
17. Write `app/tools/brand_brain.py` — The first REAL tool
18. Write `app/session/middleware.py` — Session cookie + Supabase integration
19. Write `app/db/schemas/` — Pydantic models for brand_brain, sessions
20. Test: Agent calls extract_brand_brain → Backend executes → Saves to Supabase → Agent acknowledges

### Phase 6: ASYNC BACKGROUND JOBS (20-30 mins)
21. Implement render queue (in-process, from Neural Editor pattern)
22. Demonstrate `reply.create` pattern for long-running jobs
23. Test: Render job enqueues → Worker executes → reply.create informs agent

### Phase 7: COST & RISK ANALYSIS (15-20 mins)
24. Map LLM capabilities to workflow components (Bloque A/B/C/D)
25. Estimate credit cost per full A→D cycle (conservative)
26. Identify when Pieza 8 will measure REAL costs (when first cycle completes)
27. Document risk table (tol fraud, amnesia, tool failure, HyperFaces integration)

### Phase 8: HANDOFF TO NEXT SESSION (10-15 mins)
28. Summarize findings in `.claude/specs/ARCHITECTURE_IMPLEMENTATION.md`
29. List all files created/modified in this session
30. Document open questions for next session (Claude Code iteration)
31. Save research context in `.research_context.md` for Gemini Deep Research reference

---

## 📁 EXPECTED FILES CREATED IN THIS SESSION

1. `app/tools/brand_brain/` — Tool extraction implementation
   - `extractor.py` — LLM extraction from 6-turn interview
   - `validator.py` — Ralston/Hormozi framework checks
   - `schemas.py` — Pydantic models (BrandBrain, Journey, Stage, etc.)

2. `app/session/` — Session persistence
   - `middleware.py` — FastAPI session middleware
   - `manager.py` — Load/save sessions from Supabase

3. `app/db/` — Database connection
   - `supabase_client.py` — Async client
   - `schemas/` — All Pydantic models
   - `migrations/001_initial_schema.sql` — Supabase schema

4. `docs/` — Documentation
   - `supabase_schema.sql` — Final schema with comments
   - `tool_invocation_blueprint.md` — Tool calling architecture
   - `session_persistence_pattern.md` — Session management pattern

5. `tools/` — Tool definitions (JSON schemas for AssemblyAI)
   - `brand_extraction_schema.json` — Tool contract

6. `llm_capability_mapping.csv` — LLM provider + model + cost mapping

7. `.claude/specs/ARCHITECTURE_IMPLEMENTATION.md` — Architecture summary

---

## 🎯 SUCCESS CHECKLIST FOR MONDAY

By end of session, Claude Code must:

- ✅ Have read all 10 document references (1-8 mandatory, 9-10 research outputs)
- ✅ Have located PIEZA_1/2/3_PROMPT.md files (or documented NOT found)
- ✅ Have created `app/tools/brand_brain/extractor.py` (first REAL tool)
- ✅ Have created `app/session/middleware.py` (session cookie integration)
- ✅ Have designed Supabase schema with foreign keys (CREATE TABLE statements)
- ✅ Have demonstrated tool invocation flow (agent → backend → Supabase → agent)
- ✅ Have confirmed NO Flight SDK integration decision
- ✅ Have confirmed OpenAI gpt-4o-mini as primary LLM provider
- ✅ Have documented credit cost estimation frame (when Pieza 8 measures real costs)
- ✅ Have populated risk table (toll fraud, amnesia, tool failure, HyperFaces)
- ✅ Have saved research context in `.research_context.md`
- ✅ Have summarized architecture in `.claude/specs/ARCHITECTURE_IMPLEMENTATION.md`

---

## 🔄 ITERATION PATTERN FOR SUBSEQUENT SESSIONS

### Claude Code Session 2 (Tuesday):
- Implement Pieza 1 (spend_guard) blockade
- Implement Bloque A extraction tool end-to-end
- Test full A→B gate (catalog generation)

### Claude Code Session 3 (Wednesday):
- Implement Bloque C (Viralidad Noir judge + Script writer)
- Implement Bloque D (Render pipeline + Teleprompter)
- Measure first real A→D cycle cost

### Claude Code Session 4 (Thursday):
- Fix bugs from full workflow test
- Optimize LLM calls (reduce credit spend)
- Iterate on design system (COOL PAPER palette)

### Claude Code Session 5 (Friday):
- Full production readiness test
- Deploy to Render
- Celebrate 🎉

---

## 💬 DIALOGUE EXPECTATION — Questions Claude Code ASK In Session

Claude Code should ask:
1. "Should I implement brand_brain extraction first, or spend_guard?"
   - ANSWER: **Spend_guard first (Pieza 1) — it's BLOCKER for everything else**

2. "Should I use SQLite for quick prototype?"
   - ANSWER: **NO — Supabase PostgreSQL already decided in spec. Do NOT use shortcuts.**

3. "Should I integrate Flight SDK?"
   - ANSWER: **NO — AssemblyAI purito + FastAPI orchestration. Keep it simple.**

4. "Where is PIEZA_1_PROMPT.md file?"
   - ANSWER: **Search for it in .claude/specs/PROMPTS/ — if NOT found, document as GAPA.**

5. "What is the credit cost estimation?"
   - ANSWER: **We DON'T know yet. That's why Pieza 8 exists — measure after first A→D cycle.**

6. "Should I implement all tools in one file?"
   - ANSWER: **NO — One tool per file with base_handler pattern. Modular is better.**

---

## 🚨 STOP CONDITIONS — DO NOT PROCEED WITHOUT

Claude Code session must STOP and WAIT when:
- ❌ Cannot find PIEZA_1_PROMPT.md (spend guard prompt)
- ❌ Cannot find PIEZA_2_PROMPT.md (Bloque A prompt)
- ❌ Cannot find PIEZA_3_PROMPT.md (Bloque B prompt)
- ❌ User asks to implement SQLite instead of Supabase
- ❌ User asks to integrate Flight SDK
- ❌ User asks to skip spend_guard (Anti-toll fraud)
- ❌ Cannot locate prototype `brandy-script.js` for reference
- ❌ Cannot understand the async `reply.create` pattern

---

## 📚 GLOSSARY — Terms In This Handoff

- **Bloque A**: 9-section brand extraction (Ralston, Segués, Noske, Gray, Hormozi)
- **Bloque B**: 30-idea catalog generation with hard gate
- **Bloque C**: Viralidad Noir judge (score ≥9) + Script writer
- **Bloque D**: HyperFaces render pipeline + Teleprompter + MP4/thumbnail/shorts
- **Opción B**: Architecture (Render + Supabase + in-process queue + HyperFrames)
- **tool.call**: Agent message to backend requesting function execution
- **tool.result**: Backend response to agent with function return value
- **reply.create**: Async message from backend to agent when long-running job completes
- **session.ready**: AssemblyAI event indicating agent can receive audio
- **amnesia bug**: Agent forgets user on reload (no session persistence)
- **spend_guard**: Rate limit + budget cap to prevent toll fraud
- **Viralidad Noir**: Virality scoring rubric (purity + score + axes + citations)

---

## 🎮 QUICK NAVIGATION — Jump To Section

| Section | Purpose | Key Files |
|---------|---------|-----------|
| Current State | What works, what doesn't | `app/main.py`, `app/static/app.js` |
| Documents of Truth | Reading order (MANDATORY) | spec.md, plan.md, ARCHITECTURE.md |
| Spec Analysis | Contract vs implementation | ANALISIS_CRUZADO.html |
| Prototype Gold | Interview flow reference | brandy-script.js |
| Research Outputs | What Deep Research found | .research_context.md |
| Implementation Phases | Phase 1-5 roadmap | cake |
| Tool Pattern | AssemblyAI tool calling explainer | tool_registry.py |
| Budget Decided | Non-negotiable decisions | table |
| Session Structure | Monday agenda | phases 1-8 |
| Success Criteria | When session is complete | checklist |
| Stop Conditions | Do not proceed without | table |

---

## 🏁 FINAL STATEMENT

This handoff contains EVERYTHING Claude Code needs to:

1. ✅ Understand the current MVP wrapper (what works, what doesn't)
2. ✅ Read the official documents (spec, plan, architecture, prototype)
3. ✅ Implement the FIRST real tool (brand_brain extraction)
4. ✅ Fix the amnesia bug (session persistence)
5. ✅ Establish non-negotiable constraints (Supabase, NO Flight SDK, spend_guard first)
6. ✅ Create a solid foundation for subsequent sessions (A→B→C→D workflow)

**Monday's goal**: Foundation complete (Phase 1 + Phase 2) → First real tool invocation working

---

*Document Version: HANDOFF v1.0*
*Created: 2026-09-05*
*Status: READY FOR CLAUDE CODE SESSION (MONDAY)*
