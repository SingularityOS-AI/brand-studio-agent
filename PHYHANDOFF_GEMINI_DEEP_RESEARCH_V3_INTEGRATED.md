# MASTER PROMPT — Gemini Deep Research v3.0 (DEEP_RESEARCH INTEGRATED)
## Session Goal: Convertir MVP wrapper → Voice Agent con tools reales + memoria

---

## ⚠️ CRITICAL DISCOVERY — READ THIS FIRST

### Document 9: `@../01_INVESTIGACION/DEEP_RESEARCH_PRIMER_WRAPPER.md` — 🔥 GOLD STANDARD

This document (339 lines) contains the **COMPLETE PRODUCTION ARCHITECTURE** for Brand Studio, discovered AFTER spec.md and ARCHITECTURE.md were written. It SUPERSEDES the simpler single-database approach in those original documents.

**Why This Changes Everything**:
- ✅ **Three-Layer Memory Architecture** — Redis (<2ms) ← pgvector (10-50ms) ← PostgreSQL (<5ms)
- ✅ **Google ADK Integration** — Multi-agent with Agent2Agent (A2A) protocol for cross-language
- ✅ **Temporal + LangGraph** — Asynchronous execution with durable state (NOT just callbacks)
- ✅ **HyperFrames production-ready** — Code-based video, generative diffusion AVOIDED
- ✅ **Saga compensation pattern** — Rollback on failure SÍ implemented (lines 249-266)
- ✅ **pgvector HNSW index** — For ANN semantic search (lines 70-140)

**Architecture Decision FRAMEWORK** — This research clashes with spec.md Opción B:

| Component | Spec Original (lines 270-286) | DEEP_RESEARCH Recommendation | Decision Required Monday |
|-----------|------------------------------|------------------------------|---------------------------|
| **Memory Architecture** | Single PostgreSQL | **Three-layer: Redis + pgvector + PostgreSQL** | 🔴 **DECIDE** |
| **Agent Orchestration** | AssemblyAI Voice API only | **Google ADK + AssemblyAI Voice API** | 🔴 **DECIDE** |
| **Async Execution** | In-process queue only | **Temporal + LangGraph AsyncPostgresSaver** | 🔴 **DECIDE** |
| **Semantic Search** | NOT mentioned | **PostgreSQL pgvector with HNSW index** | 🔴 **DECIDE** |
| **Video Engine** | HyperFaces (mentioned) | **HyperFrames with production patterns** | ✅ **AGREED** |

**Estructura crítica de DEEP_RESEARCH.md**:
- **Lines 1-69**: Framework selection — ADK vs LangGraph vs AssemblyAI (they complement, don't compete)
- **Lines 70-140**: **ARQUITECTURA DE MEMORIA DE TRES CAPAS** ← EL ORO PURO
  ```python
  def fetch_unified_brand_context(creator_id, session_id, query_embedding, pg_conn) -> dict:
      # NO artificial amnesia
      return {
          "short_term_turns": [],      # Redis (<2ms)
          "semantic_memories": [],     # pgvector HNSW (10-50ms)
          "procedural_rules": {}       # PostgreSQL ACID (<5ms)
      }
  ```
- **Lines 69-98**: pgvector schema complete
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
      # Saga compensation rollback included
      # Durable wait for human approval (24h timeout, frozen)
      await workflow.wait_condition(lambda: self._human_approved_script, timeout=timedelta(hours=24))
  ```
- **Lines 269-308**: HyperFrames video engine
  - Docker timeout bug (25% stall) discovered
  - Solution: use headless WITHOUT --docker flag (lines 308-309)
- **Lines 310-337**: Complete 5-phase agent workflow
  - Voice discovery → Content planning → Script writing → HyperFrames render → Distribution

**Interpretación**:
- Spec Opción B (lines 270-286): "Render + Supabase + in-process queue + HyperFaces"
- DEEP_RESEARCH: "Google ADK + Temporal + pgvector + HyperFrames"
- **Monday session must decide**: ¿Spec is MINIMUM baseline, or DEEP_RESEARCH is FUTURE standard?

**Tres opciones claras**:
1. **[ ] Adoptar DEEP_RESEARCH como producción completa** — 3-layer memory, ADK, Temporal, pgvector
2. **[ ] Stick con spec original** — Single PostgreSQL, no ADK, in-process queue only
3. **[ ] Híbrido pragmático** — pgvector para semantic search, mantener tool calling de AssemblyAI, ADK deprecation temporal

> 🎯 **PRIORIDAD #1**: Leer DEEP_RESEARCH.md completo (lines 1-339) antes de ANY architecture decision

---

## Contexto Crítico (NO OMITIR TUS LECTURAS)

Tienes un MVP wrapper de AssemblyAI Voice Agent que funciona SIN BUGS (transcripción, scroll, audio playback).
Ahora necesitamos convertilo en un AGENTE REAL con:
1. **Tools que se invocan** — el dice "tengo herramientas" pero NUNCA las llama
2. **Memoria de sesión** — al recargar desconoce todo ("sistema amnésico")
3. **Persistencia en Supabase** — guardar/leer brand_brain (9 secciones del Bloque A)

---

## Documentos de Referencia OBLIGATORIOS (Leer en este orden exacto)

### 🔴 PRINCIPAL CONTRACT

**1. [`.claude/specs/spec.md`](../.claude/specs/spec.md)** — Rev 3.6 FIRMADA
- Líneas 270-286: Opción B: Render + Supabase + in-process queue + HyperFrames
- Líneas 62-78: Bloque A estructura (9 secciones con frameworks)
- Mandato: "El sistema no es un wrapper. Hace."
- Mandato: "Ninguna afirmación sin cita literal"

**2. [`.claude/specs/plan.md`](../.claude/specs/plan.md)** — SELLADO
- §6: 10 piezas en orden
- Pieza 1: spend_guard (gate duro anti-toll fraud)
- Prompts 1, 2, 3 escritos → ubicación desconocida (buscarlos)

### 🔶 TECHNICAL DESIGN

**3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**
- Task split: Voice Agent API → Backend (tools, persistencia)
- Async pattern: `reply.create` permite encolar jobs sin bloquear
- Judge contract: JSON forzado + citaciones obligatorias

**4. [`../CONTEXTO_MAESTRO.md`](../CONTEXTO_MAESTRO.md)**
- §12: Design system (cobalto #2B4CD8)
- Estado actual: "Mockup de AssemblyAI, sin UI. Ninguna pieza despachada todavía"

### 🔶 PROTOTYPE GOLD

**5. [`.claude/design/prototype/brandy-script.js`](../.claude/design/prototype/brandy-script.js)** — Interview Flow GOLD
- Contains complete 6-turn interview logic
- Turn structure: Context → Discovery → Journey → Stage → Pain → Offer → Identity

**6. [`.claude/design/prototype/index.html`](../.claude/design/prototype/index.html)** — UI Mock (92KB)
- Shows 9 sections structure
- Use as data contract reference ONLY

**7. [`.claude/design/prototype/api.js`](../.claude/design/prototype/api.js)** — Mock Endpoints
- Mocked endpoints (migrate to FastAPI real)

### 🔍 DOCUMENTATION

**8. [`../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md`](../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md)**
- Lines 6-7: Voice Agent API provides "conversation, tool calling, barge-in"
- Lines 348-375: Tool calling pattern (`tool.call` → `tool.result`)
- Lines 375-408: Async `reply.create` for non-blocking background ops
- **CRITICAL REGLE**: Never send `input.audio` before `session.ready` event

---

## Código Existente Funcional (NO TOCAR sin entender)

- `app/main.py` v1.2 — FastAPI + `/api/agent-token`
- `app/static/app.js` v1.2 — Voice Agent API WebSocket + AudioWorklet
- `app/static/index.html` v1.2 — 3-zone layout (sin conectores backend)

- `app/voice/wrapper.py` — OBSOLETO (Streaming STT-only, NOT used)

---

## Perfiles de prompt preexistentes (Goal: Encontrar y reutilizar)

Encontrar estos archivos en el workspace:
- `@../.claude/specs/PROMPTS/PIEZA_1_PROMPT.md` — spend_guard implementation prompt
- `@../.claude/specs/PROMPTS/PIEZA_2_PROMPT.md` — Bloque A (9 secciones extraction)
- `@../.claude/specs/PROMPTS/PIEZA_3_PROMPT.md` — Bloque B (30 ideas catalog)

NOTA: Si no existen, documentar en tu reporte: "Prompts 1,2,3 written in plan but NOT found in .claude/specs/PROMPTS/"

---

## Tareas de Deep Research

### 任务 1: Construir perfil de usuario + journey completo

Investigación driving:
- Crisis del empresario: Market search results zero.
- Discovery journeys: What hooks businesses into viral content creators.
- Competitor analysis: What brands succeed talking about.
- Expert to_categorical_concept: Salty Emotional ROI metrics.

Output: 5-8 page深度报告 en el留存 context_for_next_prompt como研究员上下文 (ver abajo).

### 任务 2: Reverse engineer el prototype para construir tool definitions

Examination required:
- `@../.claude/design/prototype/brandy-script.js` — Extract exact interview flow
- `@../.claude/design/prototype/index.html` — Extract 9-section structure data contract
- `@../.claude/design/prototype/api.js` — Extract mock endpoint contracts

Output: JSON schema para tool definitions (guardar en `tools/brand_extraction_schema.json`):
```json
{
  "tool_name": "extract_brand_brain",
  "description": "Extract 9 brand sections from 6-turn interview",
  "parameters": {
    "transcript": "string",
    "turn_count": "integer (should be 6)",
    "turns": {
      "1": "Brand discovery context",
      "2": "Brand journey (Ralston framework)",
      "3": "Business stage (Segués framework)",
      "4": "Pain point (Noske approach)",
      "5": "Offer & lead magnet (Gray + Hormozi)",
      "6": "Identity & lead magnet final (Hormozi final)"
    },
    "output": {
      "brand_brain": {
        "ralston_journey": "object (5 stages)",
        "segues_stage": "string",
        "noske亟需": "string",
        "gray_offer": "object",
        "hormozi_posture": "string",
        "hormozi_associations": "array",
        "hormozi_identity": "string",
        "hormozi_lead_magnet": "object"
      },
      "validation_status": "boolean (true if all 9 sections extracted)"
    }
  }
}
```

**NOTE**: This schema already exists at `tools/brand_extraction_schema.json` — use it as baseline.

### 任务 3: Definir arquitectura de persistencia (Supabase)

Research required:
- `@../.claude/specs/spec.md` lines 270-286 → Opción B mandates Supabase
- Review DEEP_RESEARCH.md lines 70-140 → Three-layer memory (Redis + pgvector + PostgreSQL)
- Define MOST appropriate indexed schema for:
  - **IF spec baseline**: Single PostgreSQL with JSONB columns
  - **IF DEEP_RESEARCH**: Redis + pgvector + PostgreSQL relacional

Output: `docs/supabase_schema.sql` con:
- CREATE TABLE statements
- Reactive extensions (with triggers if needed)
- Indexes para FR JOIN queries
- Comments referencing spec.md specific line numbers

**NOTE**: Schema already exists at `docs/supabase_schema.sql` — verify against DEEP_RESEARCH pgvector design.

### 任务 4: Mappear LLM capabilities a componentes del workflow

Research required:
- `@../.claude/specs/spec.md` lines 62-93 → Bloque A, B, C función calls
- `@docs/ARCHITECTURE.md` lines 67-94 → LLM Gateway pattern
- AssemblyAI LLM Gateway capabilities (ver docs)
- DEEP_RESEARCH patterns (Temporal + LangGraph workflow)

Output: CSV mapping (guardar en `llm_capability_mapping.csv`):
```csv
Workflow_Component,Llm_Task,Provider,Model,Configuration,Cost_per_1k
Bloque_Ralston,Journey_Analysis,OpenAI,gpt-4o-mini,temperature=0.3,$0.001
Bloque_Segues,Stage_Classification,OpenAI,gpt-3.5-turbo,temperature=0.2,$0.0005
Bloque_Noske,Research_Search,Perplexity,pplx-7b-online,serp=true,$0.005
Catalog_Generator,Idea_Generation,OpenAI,gpt-4o-mini,temperature=0.7,n=30,$0.010
Judge,Viral_Scorer,Claude,claude-3-5-haiku,temperature=0.1,$0.002
Script_Generator,Video_Script,OpenAI,gpt-4o-mini,temperature=0.5,$0.008
```

### 任务 5: Estimar crédito cost por vuelta A→D

Research required:
- crawler threshold calculation from LLM capability mapping
- Loop assistant for worst-case approximate credits PPI audio duration (viral 15 second video = ~30s required voice fetch + ~2 min background process)
- Reference plan.md lines 219-220: "Nadie ha medido cuánto cuesta en créditos una vuelta A→D real"

Output: `docs/credit_cost_estimation.md` con:
- Breakdown por componente (Bloque A, B, C, D)
- Per-source cost with margin
- Etapa donde se mide (Pieza 8 del plan)
- Llamada a acción: "Implementar tracking de costos real BEFORE Pieza 10"

### 任务 6: Build clear graduation from wrapper → tools + memory

Research required:
- Current state: `app/static/app.js` has `const agent = { tools: [...] }` but NO invocation
- AssemblyAI tool calling docs (`@../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md` lines 348-375)
- Session management pattern from Neural Editor precedent
- DEEP_RESEARCH.md three-layer memory implementation (lines 70-140)

Output: `docs/tool_invocation_blueprints.md` con:
- Diagrama de secuencia: Browser → Voice API → Backend Tool → Supabase → Reply.create
- Code snippets para:
  - Session middleware (`app/session/middleware.py` to publish session + restore from Supabase)
  - Tool handler base class (`app/tools/base_tool.py`)
  - Brand extraction tool (`app/tools/brand_extractor.py`) — ACTUAL implementation with LLM call
  - Async reply.create pattern needed for background jobs
  - **IF DEEP_RESEARCH adopted**: Redis integration + pgvector similarity search

NOTA CRÍTICA: El siguiente archivo NO existe aún pero debe crear:
- `@app/tools/brand_extractor.py` ← Implementación del tool que realmente guarda brand_brain en Supabase/Redis/pgvector

---

## Output esperado de Deep Research

Entrega en tres partes:

### PARTE 1: Research Report (5-8 pages)

Formato: Markdown with sections, tables, bullet points guaranteeing referencias

**Example format**:
```markdown
## 1. Crisis del empresario

- El 80% de pequeños negocios intentan crear videos virales pero fallan (cite: [source])
- Discovery pain: Search results frios colisionan con conocimiento tácito
- Expert to_categorical_concept: Qué significa un elevator pitch que eleva la conversión

**Referencias**:
- [1] Source title, URL
- [2] Source title, URL
```

### PARTE 2: Implementation Blueprint (Technical specs)

Formato: Markdown con code blocks en `file_path` relative to workspace root

```markdown
## Tool Definition Schema

File: `tools/brand_extraction_schema.json`
```json
{...}
```

## Implementation Steps

1. Create session middleware: `app/session/middleware.py`
2. Create tool handler base: `app/tools/base_tool.py`
3. Create brand extraction tool: `app/tools/brand_extractor.py`
4. Define Supabase schema: `docs/supabase_schema.sql` (review DEEP_RESEARCH pgvector)
5. Migration decision: spec baseline OR DEEP_RESEARCH three-layer memory
```

### PARTE 3: Cost & Risk Analysis

Formato: Table con tres colores标记 (🟢 mitigated, 🟡 partial, 🔴 unmitigated)

```markdown
| Risk | Mitigation | Status |
|------|------------|--------|
| Toll fraud (credit exhaustion) | Pieza 1 spend_guard implementation | 🟡 Partial – exists in PIEZA_1_PROMPT.md but not implemented |
| Agent amnesia | Session persistence in Supabase + Redis per DEEP_RESEARCH | 🔴 Unmitigated – DB not set up, no pgvector |
| Tool invocation failure | Async reply.create pattern with timeout | 🟡 Partial – documented in ARCHITECTURE.md but not implemented |
| HyperFaces integration cost | First-cycle cost measurement in Pieza 8 | 🔴 Unmitigated – cost unknown until Pieza 8 |
| Architecture mismatch | Decision: spec baseline vs DEEP_RESEARCH production | 🔴 **UNDECIDED** — Monday session decision required |
```

---

## Test Criteria for Research Completeness

Completar investigación cuando:
- [ ] Todas las referencias citadas tienen URLs reales
- [ ] Cada esquema JSON es válido (pass `python -m json.tool`)
- [ ] `supabase_schema.sql` tiene FOREIGN KEYS correctas
- [ ] `llm_capability_mapping.csv` alineado con spec.md line 62-93
- [ ] `credit_cost_estimation.md` hace referencia explícita a Pieza 8 del plan
- [ ] `tool_invocation_blueprints.md` tiene secuencia-diagram con actual file paths
- [ ] **DEEP_RESEARCH.md architecture decision documented** (adopt OR reject three-layer memory)

---

## Guardar Context for Next Prompt

Crea ANTES de running this research un archivo `@.research_context.md` containing:

```markdown
# Research Context for Next Iteration

## Session: Convert MVP → Voice Agent with tools + memory

## Research Date: {% now %}

## Lead Researcher: Gemini Deep Research

## Key Findings Saved:
- User crisis profile: `research/user_crisis_profile.md`
- Tool schema: `tools/brand_extraction_schema.json`
- Supabase schema: `docs/supabase_schema.sql`
- LLM mapping: `llm_capability_mapping.csv`
- Cost estimation: `docs/credit_cost_estimation.md`
- Tool blueprints: `docs/tool_invocation_blueprints.md`

## Open Questions Documented:
1. Can brand_extraction be performed by single LLM call or requires multi-step?
2. What is the max safe wait time for `reply.create` async ops in background?
3. Should we implement credit tracking in Pieza 1 or wait until Pieza 8?
4. **🔴 ARCHITECTURE DECISION**: Adopt DEEP_RESEARCH three-layer memory OR stick with spec baseline?

## Continue Reading References (Combined 4 sources必需继续读取):

Specify next step references tying to `app/tools/brand_extractor.py` implementation.

## Next Steps:
TBD (determined by Claude Code decision on Monday)
```

---

## CRITICAL SUMMARY PARA EL LUNES

El LUNES necesitas hablar con CLAUDE CODE para analizar esto DE CERO. Tienes:

1. ✅ MVP wrapper funcional sin bugs (existe y está TESTADO)
2. ✅ Análisis completo cruzando spec vs progreso (ANALISIS_CRUZADO.html)
3. ✅ Research outputs entregados (User profile, tool schema, schemas, mappings, costs, blueprints)
4. ✅ **DEEP_RESEARCH production architecture available** (three-layer memory, ADK, Temporal, HyperFrames)
5. 📋 **Architectural decision que define el roadmap entier** (spec baseline vs DEEP_RESEARCH production)

Result expectation:
- Gemini Deep Research puede deliver baseline research outputs (even if doesn't implement full production stack)
- NO OPACAR现有CEPTO spec revision3.xx
- **Monday session MUST decide**: Architecture path (baseline minimal OR production-heavy DEEP_RESEARCH)

---

## READING ORDER THEOREM FOR MONDAY

La sesión del LUNES debe seguir este orden LECTURA OBLIGATORIA:

1. **DEEP_RESEARCH_PRIMER_WRAPPER.md** → Primero! (lines 1-339) — Production architecture completo
2. `PHYHANDOFF_CLAUDE_CODE.md` → Full handoff with 10 documentos of truth
3. `.claude/specs/spec.md` (Rev 3.6) → Contract
4. `.claude/specs/plan.md` → 10 piezas
5. `docs/ARCHITECTURE.md` → Technical split
6. `.claude/design/prototype/brandy-script.js` → Interview flow GOLD
7. `.research_context.md` → Research findings (creado por Gemini)
8. `docs/supabase_schema.sql` → Suggested schema (verify against DEEP_RESEARCH pgvector)
9. `docs/tool_invocation_blueprints.md` → Tool implementation guide

ESTO INTERACTUARÁ AL 100% FUERA DEL VACÍO QUE HAY ENTRE MVP WRAPPER Y AGENTE REAL.

---

## FIN

Ejecuta este master prompt y entrega outputs en el workspace según las especificaciones anteriores.
