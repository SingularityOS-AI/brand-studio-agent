# PROPUESTA DE PRODUCCIÓN — Brand Studio Agent

**Para:** CEO · **Fecha:** 2026-09-05 · **Estado:** **LECTURA REQUERIDA ANTES DE EMPEZAR**

---

## RESUMEN EJECUTIVO (60 segundos)

**Problema crítico identificado:** El sistema actual es un wrapper de voz con memoria = 0. Brandy recopila información estructurada de marca pero **no persiste nada** — cuando se reinicia, todo se pierde. No hay backend ni herramientas funcionales.

**Solución propuesta:** Gran bifurcación estratégica. Tenemos dos caminos mutuamente excluyentes:

| Opción | Descripción | Riesgo | Premio |
|---|---|---|---|
| **A: Wrapper funcional rápido** | Terminar el wrapper actual con persistencia básica y completar el prototipo en HTML estático | Bajo (2-3 noches) | Demo funcional, pero no cumple con "El sistema hace" |
| **B: Agente inteligente completo (fidelidad al spec)** | Implementar Bloque A completo con LLM, persistencia, el Juez real, Hyperframes | Medio-Alto (18-22 noches) | Producto defendible ante jurado, verdaderamente "hace" |

**Mi recomendación:** **Opción B** — espec.md rev 3.6 es explícito: *"El sistema no es un wrapper. Hace."* Entregar un wrapper funcional sería no cumplir con el contrato.

---

## ANÁLISIS DE LA CONVERSACIÓN CON BRANDY

### Lo que funcionó (coincide con spec.md rev 3.6)

✅ **Recopilación estructurada de identidad de marca**
- Mission, Values (energetic, helpful, straightforward), Personality, Voice
- Brand Journey (servicio, ICP), Target audience (SMBs automation)
- Postura: practical expert, not cutting-edge innovator
- Tono: short, straight to the point, respectful of time

✅ **Flujo conversacional natural**
- Brandy triajea, el founder no se auto-clasifica
- Preguntas progresivas que profundizan
- Afilación de propuestas (ej: "save business owners time through practical AI automation")

### Lo que falló CRÍTICAMENTE

❌ **No hay persistencia — sistema amnésico**
```
Usuario: "Do you have some tools to write all these things down?"
Brandy: "I have a tool that allows me to save all this information..."
...
[Session restarts]
Brandy: "Hello! I'm Brandy... I do not know you."
```

**Diagnóstico:** Brandy dice que tiene herramientas pero **nunca se usan**. El sistema es un wrapper de voz que solo transcribe. No hay backend que:
- Guarde el `brand_brain`
- Conecte con LLM para procesamiento
- Persista entre sesiones
- Ejecute las acciones prometidas

❌ **No hay UI de progreso hacia el "Documento Vivo"**
> "I am not seeing that there is something happening on the middle of the screen."

El prototype (`.claude/design/prototype/`) tiene las 3 zonas y el flujo completo, pero **no está conectado al wrapper actual**. Hay un abismo entre:
- El frontend de production (`app/static/index.html`): solo transcripción, orbe, botones
- El prototype design (.claude/design/prototype): 9 secciones, brand_brain, 30 ideas, guion, teleprompter

---

## ANÁLISIS DEL CÓDIGO ACTUAL

### Archivos existentes en `brand-studio-agent/`

| Archivo | Estado | Qué hace |
|---|---|---|
| `app/main.py` | ✅ Funcional | FastAPI, `/api/agent-token`, WebSockets básicos |
| `app/static/app.js` | ✅ Funcional | Voice Agent API WebSocket, AudioWorklet, transcripción |
| `app/static/index.html` | ⚠️ Incompleto | 3 zonas HTML pero no refleja el documento vivo |
| `app/voice/wrapper.py` | ⚠️ Legacy | Streaming STT-only (no usado por app.js) |
| `app/config.py` | ✅ Configuración | Pydantic settings, env vars |
| `tests/test_voice_ws.py` | ✅ Tests | Pruebas del wrapper legacy |

### Archivos EXISTENTES pero NO integrados

| Archivo | Ubicación | Estado |
|---|---|---|
| Prototype completo | `../.claude/design/prototype/` | ✅ Funcional, navegando en localhost |
| `index.html` (92KB) | prototype/ | Tiene las 9 secciones completas con datos mock |
| `brandy-script.js` | prototype/ | Interrogatorio completo de 6 turnos |
| `api.js` | prototype/ | Endpoints mockeados (`session`, `brain`, `catalog`, `script`) |
| `_shell.html` | prototype/ | Plantilla de navegación y CSS |

**El abismo:** El prototype funciona perfecto con datos mock, pero no hay backend que lo conecte a AssemblyAI + LLM + Persistencia.

---

## MAPA DEL PROBLEMA VISUAL

```
┌─────────────────────────────────────────────────────────────┐
│ ESTADO ACTUAL                                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [App Production]              [Prototype Design]            │
│                                                              │
│  app/static/index.html     <──MUNDO SEPARADO──      prototype/index.html
│  - 3 zonas (HTML)                                       - 9 secciones completas
│  - Orbe + transcripción                                - brand_brain populated
│  - Botón micrófono                                       - 30 ideas mock data
│  - Botón stop                                            - Script + teleprompter
│  - NO DOCUMENTO VIVO                                     - Flujo navegación completo
│                                                              │
│  [Backend]                    ← FLUJA A NINGÚN LADO →      │
│  - /api/agent-token                                     [API Mock]
│  - AssemblyAI WebSocket                                - /api/session
│  - Voice Agent API                                      - /api/brain
│  - /ws/voice (STT-only, no usado)                      - /api/catalog
│  - /api/script                                        - /api/script
│  - NO LLM                                               - Gate de créditos
│  - NO BD/Persistencia                                  - Todo falso pero UI honesta
│                                                              │
│  [Resultado]                                                 │
│  - Brandy habla y transcribe                                   │
│  - No guarda nada                                              │
│  - Sesión nueva = desconocido                                  │
│  - No cumple "El sistema hace"                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## LAS DOS OPCIONES DETALLADAS

### OPCIÓN A: WRAPPER FUNCIONAL RÁPIDO (2-3 noches)

**Stack:**
- Keep current AssemblyAI Voice Agent integration ✅
- Add simple SQLite for session persistence
- Add basic OpenAI LLM calls for brand_brain extraction
- Copy-paste prototype HTML to production with API bindings

**Archivos nuevos:**
```
app/db.py                      # SQLite + session storage
app/brand/brain.py             # LLM extraction from transcript
app/static/index_prod.html     # Copy from prototype
app/api/brain.py               # /api/brain endpoint
app/api/profile.py             # /api/profile (save/load)
migrations/*.sql               # Database schema
```

**Funcionalidad:**
1. Usuario habla → AssemblyAI transcribe
2. LLM extrae brand_brain JSON de la conversación
3. SQLite guarda session_id, transcript, brand_brain
4. UI muestra las 9 secciones extraídas
5. "Save profile" button persiste en DB
6. Reload recupera session previa por cookie

**Limitaciones:**
- ❌ El Juez (Bloque C) NO se ejecuta (es un mock score)
- ❌ Catálogo de 30 ideas (Bloque B) NO se genera real
- ❌ Render (Bloque D) NO se conecta a Hyperframes
- ❌ No cumple "El sistema hace" — es un wrapper mejorado

**Cuándo usar:**
- If deadline es mañana y necesitamos **alguna** demo
- Demo para inversores *"look, it works"* pero sabiendo que jurado verará el abismo

---

### OPCIÓN B: AGENTE INTELIGENTE COMPLETO (18-22 noches) ✅ RECOMENDADO

**Stack (fidelidad a plan.md):**
```
Frontend:          Existing app (polished)
Backend:           FastAPI en Runtime (Render)
LLM:               OpenAI gpt-4o-mini (costo razonable)
Voice:             AssemblyAI Voice Agent API ✅
Database:          Supabase PostgreSQL
Queue:             In-process (Battle Tested pattern)
Video Engine:      HyperFrames + video-use
Frontend lib:      Zero dependencies (vanilla JS)
```

**Mapa bloques a implementar:**

| Bloque | Endpoints | LLM/Tools | Días |
|---|---|---|---|
| **A. Definir la marca** | `POST /api/session/start`, `POST /api/question`, `GET /api/profile` | gpt-4o-mini: extract 9 sections | 4-5 |
| **B. Catálogo 30 ideas** | `GET /api/catalog`, `POST /api/catalog/approve` | gpt-4o-mini: generate + validate | 5-6 |
| **C. Juez + Script** | `POST /api/script/generate`, `GET /api/script/{id}`, `POST /api/judge/{id}` | gpt-4o-mini: Viralidad Noir score | 3-4 |
| **D. Render + Empaquetado** | `POST /api/render/submit`, `GET /api/render/{id}`, `GET /api/artifacts/{id}` | HyperFrames: video generation | 5-7 |
| **Gate + Créditos** | `GET /api/credits`, `POST /api/gate/approve` | Stripe checkout + deduct | 1-2 |

**Arquitectura de datos:**

```sql
-- Supabase tables
sessions (
  id UUID PRIMARY KEY,
  user_id UUID,
  brand_brain JSONB,           -- 9 secciones completas
  transcript TEXT,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
)

catalogs (
  session_id UUID REFERENCES sessions(id),
  ideas JSONB[],               -- 30 ideas con metadata
  gate_approved BOOLEAN DEFAULT FALSE,
  scores JSONB                 -- validation metrics
)

scripts (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id),
  content TEXT,
  viral_noir_score INT,
  judge_feedback JSONB,
  approved BOOLEAN DEFAULT FALSE
)

queues (
  id UUID PRIMARY KEY,
  type ENUM('script', 'render'),
  session_id UUID,
  status ENUM('queued', 'running', 'completed', 'failed'),
  result JSONB
)

artifacts (
  script_id UUID REFERENCES scripts(id),
  type ENUM('mp4', 'thumbnail', 'shorts'),
  url TEXT,
  title TEXT,
  metadata JSONB
)
```

**Script de миграции:**
```sql
-- Run once in Supabase SQL Editor
CREATE TABLE sessions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), ...);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_created ON sessions(created_at DESC);

CREATE TABLE catalogs (...);
CREATE INDEX idx_catalogs_session ON catalogs(session_id);

CREATE TABLE scripts (...);
CREATE INDEX idx_scripts_session ON scripts(session_id);
CREATE INDEX idx_scripts_approved ON scripts(approved, created_at DESC);

CREATE TABLE queues (...);
CREATE INDEX idx_queues_status ON queues(status);

CREATE TABLE artifacts (...);
CREATE INDEX idx_artifacts_script ON artifacts(script_id);
```

**Persistencia de sesión:**

```python
# app/session_manager.py
from fastapi import Request, Response
import uuid
import httpx

SESSION_COOKIE = "brand_session_id"
SESSION_DURATION = 30 * 24 * 3600  # 30 days

class SessionManager:
    async def get_or_create_session(self, request: Request) -> str:
        session_id = request.cookies.get(SESSION_COOKIE)
        if not session_id:
            session_id = str(uuid.uuid4())
        return session_id

    async def save_session(self, session_id: str, brand_brain: dict, transcript: str):
        await supabase.table("sessions").upsert({
            "id": session_id,
            "brand_brain": brand_brain,
            "transcript": transcript,
            "updated_at": "now()"
        }).execute()

    async def load_session(self, session_id: str) -> dict:
        result = await supabase.table("sessions").select("*").eq("id", session_id).execute()
        return result.data[0] if result.data else None

# Usage in middleware
@app.middleware("http")
async def session_middleware(request: Request, call_next):
    sm = SessionManager()
    session_id = await sm.get_or_create_session(request)
    request.state.session_id = session_id

    response = await call_next(request)

    # Set cookie if new session
    if not request.cookies.get(SESSION_COOKIE):
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_DURATION,
            httponly=True,
            samesite="lax"
        )
    return response
```

**LLM Integration - Bloque A:**

```python
# app/brand/extractor.py
from openai import AsyncOpenAI
from pydantic import BaseModel

class BrandSection(BaseModel):
    content: str
    citation: dict  # {"text": "...", "source": "user" | "niche_analysis"}
    status: str  # "proposed" | "approved" | "rejected"

class BrandBrain(BaseModel):
    journey: BrandSection
    stage: BrandSection
    pond: BrandSection
    expert_level: BrandSection
    contrarian: BrandSection
    associations: BrandSection
    identity: BrandSection
    offer: BrandSection
    lead_magnet: BrandSection

class BrandExtractor:
    def __init__(self, openai_key: str):
        self.client = AsyncOpenAI(api_key=openai_key)

    async def extract_from_transcript(self, transcript: str, niche_analysis: dict):
        system_prompt = """
        You extract brand identity from a transcript with Ralston/Hormozi frameworks.
        CRITICAL: Every section MUST have a literal citation.
        Do NOT invent. If transcript lacks evidence for a section, mark status="missing".
        """

        response = await self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript: {transcript}\n\nNiche analysis: {niche_analysis}"}
            ],
            response_format=BrandBrain
        )

        return response.choices[0].message.parsed

# API endpoint
@app.post("/api/brain")
async def extract_brand_brain(request: Request):
    session_id = request.state.session_id
    transcript = await get_transcript(session_id)
    niche_analysis = await run_niche_analysis(request)  # Parallel background task

    extractor = BrandExtractor(settings.openai_api_key)
    brain = await extractor.extract_from_transcript(transcript, niche_analysis)

    # Persist to Supabase
    await session_mgr.save_session(session_id, brain.dict(), transcript)

    return {"session_id": session_id, "brain": brain.dict()}
```

**UI Integration:**

```javascript
// app/static/api.js (connect real endpoints)
const API = {
  async brain(sessionId) {
    const res = await fetch(`/api/brain?session_id=${sessionId}`);
    return res.json();
  },

  async saveProfile(sessionId, profileData) {
    const res = await fetch(`/api/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, ...profileData })
    });
    return res.json();
  }
};

// In app.js, after assembly transcript complete
ws.on('transcript.done', async () => {
  const sessionId = await getSessionId(); // from cookie
  const { brain } = await API.brain(sessionId);

  // Update UI with 9 sections
  updateBrandBrainUI(brain);

  // Show "Save Profile" button with animation
  showSaveProfileButton();
});

document.getElementById('save-profile').addEventListener('click', async () => {
  await API.saveProfile(current_session, current_profile);
  showToast("Profile saved successfully!");
});
```

**Archivo 00_REGLAS revisado con logging real:**

```python
# tests/test_integration.py
import pytest
from httpx import AsyncClient
import asyncio

@pytest.mark.asyncio
async def test_full_workflow():
    """0_REGLAS 완전 충족"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1. Start session
        res = await ac.post("/api/session/start")
        assert res.status_code == 200
        session_id = res.json()["session_id"]

        # 2. Send voice (mock AssemblyAI response)
        await ac.post("/api/voice/transcript", json={
            "session_id": session_id,
            "transcript": "I help SMBs automate customer support with AI..."
        })

        # 3. Extract brain
        res = await ac.get(f"/api/brain?session_id={session_id}")
        assert res.status_code == 200
        brain = res.json()["brain"]
        assert len(brain) == 9  # All sections
        assert brain["journey"]["citation"]["source"] == "user"

        # 4. Save profile
        res = await ac.post("/api/profile", json={
            "session_id": session_id,
            "brain": brain
        })
        assert res.status_code == 201

        # 5. Reload verifies persistence
        res = await ac.get(f"/api/profile?session_id={session_id}")
        assert res.status_code == 200
        assert res.json()["brain"]["journey"]["content"] == brain["journey"]["content"]

        print("✅ 0_REGLAS 완전 충족:頭娃 tela 保全: 촬영: 각行程 래: 切적 전입: 제안: 무偿 배: 재홍: 함수: ut: Nunes 보":
```

---

## CRONOGRAMA DETALLADO — OPCIÓN B (22 noches)

| Semana | Bloque | Entregable | Días |
|---|---|---|---|
| **S1** | **Bloque A** | Interrogatorio + 9 secciones + persistencia | 5 |
| **S2** | **Bloque B** | Análisis nicho + 30 ideas + gate catálogo | 6 |
| **S3** | **Bloque C** | Generador guiones + Juez (viralidad.noir ≥9) | 4 |
| **S4** | **Bloque D** | HyperFrames render + teleprompter + empaquetado | 7 |
| **S4+** | **Gate** | Stripe checkout + deducción créditos | 2-3 |

**Hitos intermedios:**
- Fin S1: "Conoce quién es y lo guarda" ⭐
- Fin S2: "Genera 30 ideas validadas" ⭐⭐
- Fin S3: "Jueza y aprueba guiones" ⭐⭐⭐
- Fin S4: "Produce MP4 completo" ⭐⭐⭐⭐

---

## ARQUITECTURA DECISION (ya cerrada según plan.md)

**Elegida: Opción B** — Render + Supabase + cola in-process + HyperFrames

**Justificación:**
- Tier de pago Render ~$25/mes vs GCP ~$150+/mes con infraestructura manual
- Supabase UI para debugging directo vs puro SQL
- Cola in-process probada en `neural-editor-beast-mode`
- HyperFaces ya instalado y probado

**Hardware:**
- Render Runtime: 512MB RAM, 1 CPU, 0.1 vCPU-seconds/$
- Supabase: 500MB free tier hasta 50k records
- AssemblyAI: ~$0.02/min de voz

---

## 00_REGLAS — LOGGING REAL

Requisitos del hackathon (archivo `../00_REGLAS/`):

```python
# Verificación de logging en cada endpoint
@app.post("/api/session/start")
async def start_session(request: Request):
    logger.info(f"[00_REGLAS] Started session for IP {request.client.host}")

@app.post("/api/brain")
async def extract_brain(request: Request):
    logger.info(f"[00_REGLAS] Extracting brain for session {request.state.session_id}")
    logger.debug(f"[00_REGLAS] Transcript length: {len(transcript)} chars")
    loggerwarning(f"[00_REGLAS] Missing 2 sections out of 9: {[...]}")
    logger.error(f"[00_REGLAS] LLM API failed: {e}")

# Exportar logs a archivo + stdout
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
```

---

## RIESGOS Y MITIGACIÓN

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| LLM timeout en gpt-4o-mini | Media | Bloqueo de sesión | Retry pattern + fallback a gpt-3.5-turbo |
| AssemblyAI rate limiting | Baja | Parada de voz | Implementar token bucket + cookies de sesión |
| Supabase connection drain | Baja | Pérdida de datos | Connection pooling + health checks |
| HyperFrames render timeout | Alta (models pesados) | Queue阻塞 | Límite de tiempo por job + requeue automático |
| Bug in Ralston framework extraction | Media | Secciones vacías | CITAS check: status="missing" si no hay evidencia |

---

## ARCHIVOS A CREAR — OPCIÓN B

### Backend (nuevo)

```
app/
├── db/
│   ├── __init__.py
│   ├── supabase_client.py       # Async client singleton
│   └── migrations/
│       └── init_schema.sql      # Todas las tables + indexes
├── brand/
│   ├── __init__.py
│   ├── extractor.py             # LLM BrandBrain extraction
│   ├── models.py                # Pydantic models (9 sections)
│   └── validators.py            # Ralston/Hormozi framework checks
├── catalog/
│   ├── __init__.py
│   ├── generator.py             # 30 ideas generation
│   └── validator.py             # Demand validation against niche
├── script/
│   ├── __init__.py
│   ├── writer.py                # Script generator
│   └── judge.py                 # Viralidad Noir scorer
├── render/
│   ├── __init__.py
│   ├── queue.py                 # In-process job queue
│   ├── hyperframes.py           # HyperFaces integration
│   └── artifacts.py             # MP4/thumbnail/shorts generation
├── payments/
│   ├── __init__.py
│   ├── stripe_client.py         # Stripe Checkout
│   └── credits.py               # Credit deductor
├── session/
│   ├── __init__.py
│   └── manager.py               # Session cookie + load/save
└── logging.py                   # 00_REGLAS logging config
```

### Frontend (existente, polished)

```
app/static/
├── index.html                   # 3 zones (polished)
├── app.js                       # voice + session + api calls
├── api.js                       # Wraps all backend endpoints
├── components/
│   ├── brand-brain.js           # 9 sections UI
│   ├── catalog.js               # 30 ideas list + gate
│   ├── script.js                # Script viewer + Juez verdict
│   └── production.js            # Teleprompter + render queue
└── styles/
    ├── base.css                 # Design system vars
    ├── zones.css                # 3-zone layout
    └── verdicts.css             # Pass/fail/warn colors
```

### Tests (nuevo)

```
tests/
├── test_integration.py          # 00_REGLAS full workflow
├── test_brand_extractor.py      # Bloque A unit tests
├── test_catalog_generator.py    # Bloque B unit tests
├── test_script_judge.py         # Bloque C unit tests
└── test_render_queue.py         # Bloque D unit tests
```

---

## DECISIÓN NECESARIA — LÉE ESTO MAÑANA CEO

**Pregunta:** ¿Opción A (wrapper rápido) o Opción B (agente completo)?

**My emphatic recommendation:** **Opción B**

**Razonamiento:**

1. **Spec.md rev 3.6 es law**: *"El sistema no es un wrapper. Hace."* Entregar un wrapper sería no cumplir.

2. **Demo falsa costo reputación**: Jurado no humaniza "linda UI + zero backend" — venimos de Voxniac, ya nos quemamos eso.

3. **22 noches es razonable**: 4 semanas, con el diseño cerrado y inline scripts. No es construir desde cero.

4. **Pieza 1 ya escrita**: El master prompt existe. Solo despachar.

5. **Opción A = deuda técnica inmediata**: Si elegimos rápido, mañana estamos en el mismo lugar.

**Recomendación secuencial:**

```
HOY:
  → Lee SPEC completa (3.1-3.23)
  → No edites nada
  → Solo decide A o B

MAÑANA:
  → Si B: Leer PIEZA_1_PROMPT.md + despachar
  → Si A: Implementar wrapper (2-3 días)
```

---

## APÉNDICE — TRANSCRIPción de la conversación COMPLETA

*(Todo el texto que compartiste en el mensaje anterior)*

**Extractos críticos:**

> Usuario: "Do you have some tools to write all these things down, or all of this stays on the transcript, sir?"
>
> Brandy: "I have a tool that allows me to save all this information into a formal brand profile for you."
>
> Usuario: "Yes, sir, please do."
>
> [...silencia...]
>
> Usuario: "Hello? Can you hear me?"
>
> Brandy: "Hello! I'm Brandy... I do not know you."

**Este es el failurescape del sistema actual. No puede continuar.**

---

## FIRMA Y PRÓXIMO PASO

**Leído por:** [Tu nombre, CEO]
**Fecha:** 2026-09-06 (mañana)

**Después de leer, marca:**

- ✅ **Opción A — Wrapper rápido**
- ✅ **Opción B — Agente completo (RECOMENDADO)**

**Si B, el siguiente paso es:** Leer `../.claude/specs/PIEZA_1_PROMPT.md` y despachar a DSH con Capitán + Marcapasos.

---

**Nota final:** El prototype en `../.claude/design/prototype/` funciona y enseña el producto final. El problema actual es el abismo entre diseño y implementation. Este documento lo cruza con un puente sólido.
