# MASTER PROMPT — Gemini Deep Research
## Session Goal: Convertir MVP wrapper → Voice Agent con tools reales + memoria

## Contexto Crítico (NO OMITIR TUS LECTURAS)

Tienes un MVP wrapper de AssemblyAI Voice Agent que funciona SIN BUGS (transcripción, scroll, audio playback).
Ahora necesitamos convertilo en un AGENTE REAL con:
1. **Tools que se invocan** — el dice "tengo herramientas" pero NUNCA las llama
2. **Memoria de sesión** — al recargar desconoce todo ("sistema amnésico")
3. **Persistencia en Supabase** — guardar/leer brand_brain (9 secciones del Bloque A)

## Documentos de Referencia OBLIGATORIOS (Leer en este orden exacto)

1. **CONTRATO PRINCIPAL**: `@../.claude/specs/spec.md` (Rev 3.6 FIRMADA)
   - Líneas 270-286: Opción B: Render + Supabase + in-process queue + HyperFrames
   - Líneas 62-78: Bloque A estructura (9 secciones con frameworks)
   - Mandato: "El sistema no es un wrapper. Hace."
   - Mandato: "Ninguna afirmación sin cita literal"

2. **PLANIFICACIÓN**: `@../.claude/specs/plan.md` (SELLADO)
   - §6: 10 piezas en orden
   - Pieza 1: spend_guard (gate duro anti-toll fraud)
   - Prompts 1, 2, 3 escritos → ubicación desconocida (buscarlos)

3. **ARQUITECTURA**: `@docs/ARCHITECTURE.md`
   - Task split: Voice Agent API (conversación) → Backend (tools, persistencia)
   - Async pattern: `reply.create` permite encolar jobs sin bloquear
   - Judge contract: JSON forzado + citaciones obligatorias

4. **CONTEXTO MAESTRO**: `@../CONTEXTO_MAESTRO.md`
   - §12: Design system (cobalto #2B4CD8)
   - Estado actual: "Mockup de AssemblyAI, sin UI. Ninguna pieza despachada todavía"

5. **ANÁLISIS COMPLETO**: `@ANALISIS_CRUZADO.html`
   - Cruzó spec vs progreso → GAP CLARO: 100% faltante (DB, Bloque A, Bloque B, Bloque C, Bloque D)

## Código Existente Funcional (NO TOCAR estos archivos sin entender primero)

- `app/main.py` v1.2 — FastAPI + `/api/agent-token`
- `app/static/app.js` v1.2 — Voice Agent API WebSocket + AudioWorklet
- `app/static/index.html` v1.2 — 3-zone layout (sin conectores backend)

- `app/voice/wrapper.py` — OBSOLETO (Streaming STT-only, NO usado)

## PROTOtipo Navegable (Desconectado pero contiene gold)

- `@../.claude/design/prototype/` — Interrogatorio completo de 6 turnos + frameworks
  - `brandy-script.js` → Lógica del interrogatorio (6 turnos)
  - `index.html` → 92KB con 9 secciones mockeadas
  - `api.js` → Endpoints mock (migrar a FastAPI real)

## AssemblyAI Technical Docs (Read these to understand capabilities)

- `@../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md`
  - Lines 6-7: Voice Agent API provides "conversation, tool calling, barge-in"
  - Lines 348-375: Tool calling pattern (`tool.call` → `tool.result`)
  - Lines 375-408: Async `reply.create` for non-blocking background ops
  - **CRITICAL REGLE**: Never send `input.audio` before `session.ready` event

## Perfiles de prompt preexistentes (Goal: Encontrar y reutilizar)

 encontrar estos archivos en el workspace:
- `@../.claude/specs/PROMPTS/PIEZA_1_PROMPT.md` — spend_guard implementation prompt
- `@../.claude/specs/PROMPTS/PIEZA_2_PROMPT.md` — Bloque A (9 secciones extraction)
- `@../.claude/specs/PROMPTS/PIEZA_3_PROMPT.md` — Bloque B (30 ideas catalog)

NOTA: Si no existen, documentar en tu reporte: "Prompts 1,2,3WriterWritten en plan pero NOT encontrados en .claude/specs/PROMPTS/"

## Tareas de Deep Research

###任务 1: Construir perfil de usuario + journey completo
investigación driving:
- Crisis del empresario: Market search qui fax zero.
- Discovery journeys: What hooks businesses viral content creators.
- Competitor analysis: What brands succeed talking about.
- EXPERT to_categorical_concept: Salty Emotional ROI metrics.

Output: 5-8 page深度报告 en el留存 context_for_next_prompt como研究员上下文 (ver abajo).

###任务 2: Reverse engineer el prototype para construir tool definitions
examination required:
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

###任务 3: Definir arquitectura de persistencia (Supabase)
research required:
- `@../.claude/specs/spec.md` lines 270-286 → Opción B mandates Supabase
- Review Neural Editor precedent (likely exists in `.claude/specs/`)
- Define 최适宜.indexed schema for:
  - `users` → session_id, credits, brand_brain (JSONB)
  - `sessions` → session_id (UUID), user_id, transcript (TEXT), metadata (JSONB)
  - `brand_brains` → user_id, sections (JSONB), version (string)
  - `catalogs` → user_id, ideas (JSONB), status (pending/approved/rejected)
  - `scripts` → user_id, script (TEXT), verdict (JSONB), viral_score (decimal)

Output: `docs/supabase_schema.sql` con:
- CREATE TABLE statements
- Reactive extensions (with triggers if needed)
- Indexes para FR JOIN queries
- Comments referencing spec.md specific line numbers

###任务 4: Mappear LLM capabilities a componentes del workflow
research required:
- `@../.claude/specs/spec.md` lines 62-93 → Bloque A, B, C función calls
- `@docs/ARCHITECTURE.md` lines 67-94 → LLM Gateway pattern
- AssemblyAI LLM Gateway capabilities (ver docs)

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

###任务 5: Estimar crédito cost por vuelta A→D""
research required:
- crawler threshold calculation from LLM capability mapping
- Loop assistant for worst-case approximate credits PPI audio duration (viral 15 second video = ~30s required voice fetch + ~2 min background process) 
- etc.

Output: `docs/credit_cost_estimation.md` con:
- Breakdown por componente (Bloque A, B, C, D)
- Per-source cost with margin
- Etapa donde se mide (Pieza 8 del plan)
- Llamada a acción: "Implementarññ tracking de costos real BEFORE Pieza 10"

###任务 6: Build clear graduation from wrapper → tools + memor
research required:
- Current state: `app/static/app.js` has `const agent = { tools: [...] }` but NO invocation
- AssemblyAI tool calling docs (`@../03_DOCUMENTACION_TECNICA/06_VOICE_AGENT_API_DOCS.md` lines 348-375)
- Session management pattern from Neural Editor precedent

Output: `docs/tool_invocation_blueprints.md` con:
- Diagrama de secuencia: Browser → Voice API → Backend Tool → Supabase → Reply.create
- Code snippets para:
  - Session middleware (`app/session/middleware.py` to publish session + publish从Supabase)
  - Tool handler base class (`app/tools/base_tool.py`)
  - Brand extraction tool the king draw form(`app/tools/brand_extractor.py`)
  - Async reply.create pattern needed for background jobs

NOTA CRÍTICA: El siguiente archivo NO existe aún pero debe crearreferencia:
- `@app/tools/brand_extractor.py` ← Implementación del tool que realmente guarda brand_brain en Supabase

## Output esperado de Deep Research

Entrega en tres partes:

### PARTE 1: Research Report (5-8 pages)
Formato: Markdown with sections, tables, bullet points guaranteeing referencias

**Maduración de Display outsourcing**:
```markdown
## 1. Crisis del empresario

- Văn đánh mất audiencia: X% of small businesses attempt zero viral videos (cite: [source])
- Discovery pain: H冰冷 search resultsозит collision with知己
- EXPERT to_categorical_concept: Что означает кадра升华 за ма

**Referencias**:
- [1] Source title, URL
- [2] Source title, URL

```

### PARTE 2: Implementation Blueprint (Technical specs)
Formato: Markdown con code blocks en `file_path` relative a workspace root

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
4. Define Supabase schema: `docs/supabase_schema.sql`
5. Migrate prototype JS logic to Python LLM extraction

```

### PARTE 3: Cost & Risk Analysis
Formato: Table con三种颜色标记 (🟢 mitigated, 🟡 partial, 🔴 unmitigated)

```markdown
| Risk | Mitigation | Status |
|------|------------|--------|
| Toll fraud (credit exhaustion) | Pieza 1 spend_guard implementation | 🟡 Partial – exists in PIEZA_1_PROMPT.md but not implemented |
| Agent amnesia | Session persistence in Supabase | 🔴 Unmitigated – DB not set up |
| Tool invocation failure | Async reply.create pattern with timeout | 🟡 Partial – documented in ARCHITECTURE.md but not implemented |
| HyperFaces integration cost | First-cycle cost measurement in Pieza 8 | 🔴 Unmitigated – cost unknown until Pieza 8 |
```

## Test Criteria for Research Completeness

Completar investigación cuando:
- [ ] Todas las referencias citadas tienen URLs reales
- [ ] Cada esquema JSON es válido (pass `python -m json.tool`)
- [ ] `supabase_schema.sql` tiene FOREIGN KEYS正确
- [ ] `llm_capability_mapping.csv` alineado con spec.md line 62-93
- [ ] `credit_cost_estimation.md` hace referencia explícita a Pieza 8 del plan
- [ ] `tool_invocation_blueprints.md` tiene secuencia-diagram con actual file paths

##保存 Context for Next Prompt

Creaafter running this research un archivo `@.research_context.md` containing:

```markdown
# Research Context for Next Iteration

## Session: Convert MVP → Voice Agent with tools + memory

## Research Date: {% now %}

## Lead Researcher出土合同: Gemini Deep Research

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

## Wout继续 Reading References (Combined 4 sources必需继续读取):

Specify next step references tying to `app/tools/brand_extractor.py` implementation.

## qemu_raw_pipeline：
TBD (determined by Claude Opus decision)session总结.
```

---

## CRITICAL SUMMARY PARA EL LUNES

El LUNES necesitas hablar con CLAUDE OPUS para analizar esto DE CERO. Tienes:

1. ✅ MVP wrapper funcional sin bugs (existe y está TESTADO)
2. ✅ Análisis completo cruzando spec vs progreso (ANALISIS_CRUZADO.html)
3. ✅ Research outputs交付 = Tipo以上
4. 📋 Generative Algorithm建议而不(plans through� validating without targets)

Result expectation: 
- Gemini Deep Research puede兵临day (jueces even if implements全部to Berkeley北极良知research)
- NO OPACAR现有CEPTOspec revision3.xx

---

## READING ORDER THEOREM FOR MONDAY

La sesión del LUNES debe seguir este orden LECTURA OBLIGATORIA:

1. `ANALISIS_CRUZADO.html` → Visualizar GAPs
2. `.claude/specs/spec.md` (Rev 3.6) → Contract
3. `.claude/specs/plan.md` → 10 piezas
4. `docs/ARCHITECTURE.md` → Technical split
5. `.claude/design/prototype/brandy-script.js` → Interview flow GOLD
6. `.research_context.md` → Research findings (creado ahora)
7. `docs/supabase_schema.sql` → Suggested schema (en research)
8. `docs/tool_invocation_blueprints.md` → Tool implementation guide (en research)

ESTO INTERACTUARÁ AL 100% FUERA DEL VACÍO QUE HAY ENTRE MVP WRAPPER Y AGENTE REAL.

---

## FIN

Ejecuta este master prompt y entrega outputs en el workspace según las especificaciones anteriores.
