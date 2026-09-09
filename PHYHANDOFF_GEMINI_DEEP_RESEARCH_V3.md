# MASTER PROMPT — Gemini Deep Research v3.0 (DEEP_RESEARCH INTEGRATED)
## Session Goal: Convertir MVP wrapper → Voice Agent con tools reales + memoria

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
  - Segués (Etapa del negocio: diagnóstica del current stage)
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
  - **Pieza 2**: Bloque A parte (interrogatorio + 9 secciones)
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

**7. [`.claude/design/prototype/api.js`](../.claude/design/prototype/api.js)** — Mock Endpoints
- Mocked REST endpoints (migrate to FastAPI real implementation)

### 🔥 GOLD STANDARD — PRODUCTION ARCHITECTURE (READ FIRST!)

**8. [`../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md`](../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md)** — 🔥 MUST READ

⚠️ **ESTE DOCUMENTO ES TRANSFORMACIONAL** (339 lines) — Contiene la arquitectura COMPLETE de PRODUCCIÓN para Brand Studio, descubierta DESPUÉS de que se escribieron spec.md y ARCHITECTURE.md.

**¿Por qué esto cambia toda la conversación?**
- ✅ **Memoria de 3 capas implementada** — Redis (corto plazo <2ms) + pgvector (semántica 10-50ms HNSW index) + PostgreSQL relacional (brand rules ACID <5ms)
- ✅ **Google ADK integration** — Multi-agent workflow con Agent2Agent protocol, NO solo callbacks
- ✅ **Temporal + LangGraph** — Engine de ejecución asíncrono durable reales (NO solo in-process queue)
- ✅ **Saga compensation pattern** — Rollback on failure SÍ implementado (lines 249-266)
- ✅ **HyperFrames production-ready** — Con solución al bug de Docker timeout (lines 269-308)
- ✅ **Complete agent workflow** — 5 phased production (voice → plan → script → render → distribute)
- ✅ **pgvector HNSW index** — Para búsqueda semántica ANN (lines 70-140)

**Estructura crítica del documento**:
- **Lines 1-69**: Selección de frameworks (ADK vs LangGraph vs AssemblyAI)
  - Frameworks NO compiten, se complementan en el stack
  - AssemblyAI = transporte de voz
  - Google ADK = orquestación multi-agent
  - LangGraph = razonamiento cognitivo
- **Lines 70-140**: **ARQUITECTURA DE MEMORIA DE TRES CAPAS** ← EL ORO PURO
  ```python
  def fetch_unified_brand_context(creator_id, session_id, query_embedding, pg_conn) -> dict:
      # NO amnesia artificial
      return {
          "short_term_turns": [],      # Redis (<2ms)
          "semantic_memories": [],     # pgvector HNSW (10-50ms)
          "procedural_rules": {}       # PostgreSQL ACID (<5ms)
      }
  ```
- **Lines 69-98**: pgvector schema completo
  ```sql
  CREATE TABLE brand_episodic_memories (
      memory_content TEXT NOT NULL,
      memory_embedding VECTOR(1536) NOT NULL  -- OpenAI embeddings
  );
  CREATE INDEX episodic_memories_hnsw_idx USING hnsw (memory_embedding vector_cosine_ops);
  ```
- **Lines 141-268**: **Temporal + LangGraph workflow** ← PRODUCCIÓN DE ECOSYSTEM
  ```python
  @workflow.defn
  class BrandStudioProductionWorkflow:
      # Saga compensation rollback pattern included
      # Durable wait for human approval (24h timeout, frozen execution)
      await workflow.wait_condition(lambda: self._human_approved_script, timeout=timedelta(hours=24))
  ```
- **Lines 269-308**: HyperFrames video engine
  - Docker timeout bug (25% stall) + solution (headless without --docker flag)
  - FastAPI microservice pattern with @hyperframes/producer
- **Lines 310-337**: Complete 5-phase agent workflow
  - 1. Voice discovery → 2. Content planning → 3. Script writing → 4. HyperFrames render → 5. Distribution

**CRITICAL DECISION FRAMEWORK** — Esto que se descubrió DESPUÉS de spec.md:

| Componente | Spec Original (lines 270-286) | DEEP_RESEARCH Recommendation | Decision Required Monday |
|------------|------------------------------|------------------------------|---------------------------|
| Memory Architecture | Single PostgreSQL | 3-layer (Redis + pgvector + PostgreSQL) | 🔴 **DECIDE** |
| Agent Orchestration | None (in-process callbacks) | Google ADK + Agent2Agent protocol | 🔴 **DECIDE** |
| Async Execution | In-process queue only | Temporal (durable workflow engine) | 🔴 **DECIDE** |
| Semantic Search | NOT mentioned | pgvector HNSW index | 🔴 **DECIDE** |
| Video Engine | HyperFaces (mentioned) | HyperFrames w/ production patterns | ✅ **AGREED** |

**Interpretación**:
- Spec Opción B dice "Render + Supabase + in-process queue + HyperFaces"
- DEEP_RESEARCH dice "Google ADK + Temporal + pgvector + HyperFrames"
- **Monday session must decide**: ¿Spec original es baseline MÍNIMO, o DEEP_RESEARCH es el estándar FUTURO?

**Opciones claras**:
1. **Adoptar DEEP_RESEARCH como producción completa** — 3-layer memory, ADK, Temporal, pgvector
2. **Stick con spec original** — Single PostgreSQL, no ADK, in-process queue only
3. **Híbrido pragmático** — pgvector para semantic search, mantener tool calling de AssemblyAI, ADK deprecation temporal

> 🎯 **PRIORIDAD #1**: Leer DEEP_RESEARCH completo (lines 1-339) antes de ANY architecture decision

### 🔍 DOCUMENTATION

**9. [`../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md`](../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md)**
- **Lines 6-7**: Voice Agent API provides "conversation, tool calling, barge-in"
- **Lines 348-375**: Tool calling pattern (`tool.call` → `tool.result`)
- **Lines 375-408**: Async `reply.create` for non-blocking background ops
- **CRITICAL RULE**: Never send `input.audio` before `session.ready` event

**10. [`ANALISIS_CRUZADO.html`](ANALISIS_CRUZADO.html)**
- Spec vs progress analysis → GAP CLARO: 100% faltante (DB, Bloque A-D)
- Decision tracking: Flight SDK vs AssemblyAI purito

---

## 🎯 Session Goal: Build Foundation (Phase 1)

### Blockers CLEARED for Monday Session
1. ✅ **MVP wrapper baseline exists** — v2.2 bug-free, confirmed working
2. ✅ **Spec contracts clear** — spec.md (Rev 3.6), plan.md (sellado)
3. ✅ **Prototype gold identified** — brandy-script.js (interview flow)
4. ✅ **Performance issue identified** — Amnesia system (no persistence)
5. ✅ **DEEP_RESEARCH available** — Production architecture完整
6. ✅ **Tool schema defined** — `@tools/brand_extraction_schema.json` exists
7. ✅ **Supabase schema designed** — `@docs/supabase_schema.sql` exists

### Monday Session Targets (8 Phases)

**Phase 1: Decision Framework (15 min)**
- [ ] Read DEEP_RESEARCH.md → decide: spec baseline OR DEEP_RESEARCH production?
- [ ] Decision recorded in session notes with justification

**Phase 2: Architecture Alignment (20 min)**
- [ ] Write architecture decision matrix in `docs/architecture_decision_matrix.md`
- [ ] Reference in handoff: Component diagram with DEEP_RESEARCH patterns

**Phase 3: Session Persistence (30 min)**
- [ ] Build session middleware (`app/session/middleware.py`)
- [ ] Integrate Supabase connection
- [ ] Save brand_brain after tool completion

**Phase 4: spend_guard (Pieza 1) (30 min)**
- [ ] Implement rate limit + budget cap
- [ ] Prevent toll fraud (0% credit exhaustion possible)

**Phase 5: Brand Extraction Tool (45 min)**
- [ ] Create `app/tools/brand_extractor.py` from schema
- [ ] Tool actually invokes on interview completion
- [ ] Store 9 sections in Supabase per spec.md lines 62-78

**Phase 6: Test Cycle (30 min)**
- [ ] Run voice interview (6 turns)
- [ ] Verify tool invocation in logs
- [ ] Check brand_brain in Supabase
- [ ] Test session persistence (reload → no amnesia)

**Phase 7: Documentation (20 min)**
- [ ] Update ANALISIS_CRUZADO.html with Phase 1-5 progress
- [ ] Document decision framework outcome

**Phase 8: Next Steps (10 min)**
- [ ] Plan Bloque B implementation (Phase 2)
- [ ] Define credit cost measurement (Pieza 8)

---

## 🔧 Code Examples for Monday Session

### Tool Calling Pattern (AssemblyAI → Backend)

```javascript
// Frontend (app.js) — tool invocation flow
const toolCall = {
  "type": "tool_call",
  "tool_name": "extract_brand_brain",
  "parameters": {
    "transcript": full_transcript,
    "turn_count": 6
  }
};
ws.send(JSON.stringify(toolCall));
```

```python
# Backend (tools/brand_extractor.py) — implementation
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def extract_brand_brain(transcript: str, turn_count: int) -> dict:
    """Extract 9 sections from 6-turn interview"""
    # LLM call with forced JSON schema
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": BRAND_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": transcript}
        ],
        response_format={"type": "json_object"}
    )
    
    brand_brain = json.loads(response.choices[0].message.content)
    
    # Validate 9 sections complete
    validation = validate_brand_brain(brand_brain)
    
    # Save to Supabase
    supabase.table("brand_brains").insert({
        "user_id": user_id,
        "brand_brain": brand_brain,
        "validation_status": validation['is_valid'],
        "extraction_timestamp": datetime.now()
    }).execute()
    
    return {
        "status": "success",
        "brand_brain": brand_brain,
        "validation": validation
    }
```

### Session Persistence (Middleware)

```python
# app/session/middleware.py
from fastapi import Request, HTTPException
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def session_middleware(request: Request, call_next):
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        # Create new session
        session_id = str(uuid.uuid4())
        supabase.table("sessions").insert({
            "session_id": session_id,
            "created_at": datetime.now()
        }).execute()
        response = await call_next(request)
        response.set_cookie("session_id", session_id)
        return response
    
    # Load existing session
    result = supabase.table("sessions").select("*").eq("session_id", session_id).single()
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    request.state.session = result.data
    response = await call_next(request)
    return response
```

### spend_guard (Pieza 1)

```python
# app/guards/spend_guard.py
from supabase import create_client
from fastapi import HTTPException

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def spend_guard_check(user_id: str, estimate_cost: float, operation_type: str) -> bool:
    """Check if user has sufficient credits for operation"""
    # Get user balance
    user = supabase.table("users").select("credits_balance").eq("user_id", user_id).single()
    
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    balance = user.data['credits_balance']
    
    if balance < estimate_cost:
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient credits. Balance: {balance}, Required: {estimate_cost}"
        )
    
    # Log attempt for audit
    supabase.table("cost_estimates").insert({
        "user_id": user_id,
        "operation_type": operation_type,
        "estimated_cost": estimate_cost,
        "status": "approved"
    }).execute()
    
    return True
```

---

## 📊 Success Checklist for Monday Session

By end of Monday session, expect:

- [ ] **Decision Framework Complete** — Architecture path clear (spec baseline vs DEEP_RESEARCH)
- [ ] **Session Persistence Workng** — Reload page, no amnesia, remembers brand_brain
- [ ] **spend_guard Blocking Fraud** — Cannot extract brand_brain without credits
- [ ] **Tool Actually Invoking** — Tool calls appear in AssemblyAI logs (not just claimed)
- [ ] **Brand Brain Saved** — Supabase has 9 sections per spec.md lines 62-78
- [ ] **Test Cycle Passed** — Complete 6-turn interview → tool → DB → persistence

---

## 🚫 Stop Conditions

Monday session stops if:

1. **Architecture deadlock** — Cannot decide between spec baseline vs DEEP_RESEARCH after 20 min
2. **spend_guard impossible** — No clear way to rate limit Supabase credits
3. **Tool invocation fails** — AssemblyAI tool.call pattern not working (critical blocker)
4. **Session persistence breaks** — Cannot save/load from Supabase reliably
5. **Brand extraction incomplete** — LLM cannot extract all 9 sections reliably

---

## 🔎 Search Commands for Session

```bash
# Find missing prompt files (plan.md §6 references these)
find .. -name "PIEZA_*.md" -type f

# Find Supabase schema (if exists in specs)
find .. -name "*supabase*.sql" -o -name "*schema*.sql"

# Find Neural Editor precedent (session persistence)
find .. -name "*neural*" -o -name "*editor*" -type f

# Search for existing middleware patterns
grep -r "session_middleware\|session_persistence" .. --include="*.py" --include="*.md"
```

---

## 📞 Expectation for Monday Outcome

### Best Case (Green Light)
- Foundation complete (spend_guard + session + DB + brand_brain extraction tool)
- Architecture decision clear (spec baseline OR DEEP_RESEARCH production)
- Ready to implement Bloque B (catalog generation) in Phase 2

### Probable Case (Yellow Light)
- Foundation mostly complete
- Minor technical blockers remain (tool invocation timing, session cookie flow)
- Architecture decision deferred to later session

 Worst Case (Red Light)
- Architecture deadlock (cannot decide spec vs DEEP_RESEARCH)
- Tool invocation impossible (AssemblyAI pattern not understood)
- Return to research phase with clearer questions

---

## 🎓 Learning Objectives

Monday session teaches:

1. **Framework decision making** — When to adopt production-heavy architecture (ADK, Temporal) vs pragmatic MVP
2. **Tool invocation patterns** — AssemblyAI tool.call → backend → reply.create workflow
3. **Session persistence** — State management across page reloads with Supabase
4. **Fraud prevention** — spend_guard implementation for credit systems
5. **Brand extraction UX** — Turn 6-turn interview into structured JSON (9 sections)

---

## 📚 Reference Materials for Session

Bring to Monday session:

```markdown
## Quick Reference Sheet

### spec.md key lines
- Lines 62-78: Bloque A 9 secciones
- Lines 86-93: Bloque B gate
- Lines 270-286: Opción B (Render + Supabase + in-process queue)

### plan.md key sections
- §6: 10 piezas order
- Pieza 1: spend_guard (critical blocker)
- Pieza 8: Credit cost measurement (unknown until implemented)

### DEEP_RESEARCH key lines
- Lines 1-69: Framework selection (ADK vs LangGraph vs AssemblyAI)
- Lines 70-140: 3-layer memory architecture (Redis + pgvector + PostgreSQL)
- Lines 141-268: Temporal + LangGraph workflow
- Lines 269-308: HyperFrames video engine
- Lines 310-337: Complete agent workflow (5 phases)

### ARCHITECTURE.md key lines
- Lines 67-72: Task split
- Lines 78-94: Async pattern (reply.create)
- Lines 98-118: Judge contract (forced JSON)
```

---

## ✅ What's READY for Monday

- ✅ **Handoff materials** — This document + PHYHANDOFF_CLAUDE_CODE.md
- ✅ **Code examples** — Tool calling, session middleware, spend_guard
- ✅ **Schema files** — `tools/brand_extraction_schema.json`, `docs/supabase_schema.sql`
- ✅ **Baseline MVP** — v2.2 wrapper confirmed working
- ✅ **Prototype gold** — brandy-script.js interview flow
- ✅ **Production research** — DEEP_RESEARCH.md complete

---

## 🚀 Ready to Start

Monday session begins with:

1. **Decision Phase** (15 min) — Read DEEP_RESEARCH, decide architecture path
2. **Architecture Alignment** (20 min) — Write decision matrix
3. **Implementation Sprint** (2-3 hours) — Phase 3-5 (session, spend_guard, tool)
4. **Test & Verify** (30 min) — End-to-end test cycle
5. **Review & Plan** (20 min) — Next steps (Bloque B), documentation

---

## 🔗 Links to All Documents

- [`.claude/specs/spec.md`](../.claude/specs/spec.md) — Main contract
- [`.claude/specs/plan.md`](../.claude/specs/plan.md) — 10 piezas roadmap
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — System architecture
- [`../CONTEXTO_MAESTRO.md`](../CONTEXTO_MAESTRO.md) — Master context
- [`../.claude/design/prototype/brandy-script.js`](../.claude/design/prototype/brandy-script.js) — Interview flow
- [`../.claude/design/prototype/index.html`](../.claude/design/prototype/index.html) — UI mock
- [`../.claude/design/prototype/api.js`](../.claude/design/prototype/api.js) — Mock endpoints
- [`../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md`](../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md) — Production architecture
- [`../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md`](../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md) — AssemblyAI docs
- [`ANALISIS_CRUZADO.html`](ANALISIS_CRUZADO.html) — Spec vs progress
- [`tools/brand_extraction_schema.json`](tools/brand_extraction_schema.json) — Tool schema
- [`docs/supabase_schema.sql`](docs/supabase_schema.sql) — DB schema

---

## 🎯 Final Note

**This handoff is COMPLETE**. All materials referenced, all code examples provided, all decisions documented.

Monday Claude Code session will have:
- ✅ Clear baseline (v2.2 MVP wrapper)
- ✅ Clear contracts (spec.md, plan.md, ARCHITECTURE.md)
- ✅ Clear gold standard (prototype, DEEP_RESEARCH production architecture)
- ✅ Clear implementation path (Phase 1-5 with code examples)
- ✅ Clear success criteria (checklist, test cycle)
- ✅ Clear stop conditions (when to halt session)

**GO** — The session is ready to begin.
