"""
PIEZA 19 — Demostrar sin gastar creditos: cada nodo se pinta al confirmar,
y el Brand Soul se genera de verdad.

Que prueba esto (spec: .claude/specs/PIEZA_19_PRUEBA_SIN_VOZ.md):

  Parte A: recorre los 9 nodos EN ORDEN via el WebSocket falso, y por cada
  uno afirma sobre el DOM REAL (no sobre la respuesta HTTP) que se pinta como
  Confirmed/Proposed, con la cita literal del fundador, con el contador
  correcto, y con el hueco gris (.ghost) de ese nodo ya removido. Incluye un
  nodo en dos pasos (Proposed -> Confirmed) y un caso negativo (cita que el
  fundador nunca dijo: no se pinta, y aparece en skipped_sections con motivo
  cita_no_encontrada).

  Parte B: al llegar a 9/9, hace clic en el boton, espera el overlay real
  "Your Brand Soul", y afirma que el HTML generado trae al menos 3 de las 9
  citas literales del fundador. Guarda el HTML y dos screenshots en
  tests/e2e/_salida/ para que el CEO los abra.

CERO cambios en codigo de produccion (regla dura de la pieza). Todo lo que
sigue es andamiaje de PRUEBA:

  - Backend FastAPI REAL corriendo en un hilo de este mismo proceso
    (TEST_MODE=true -> guard en memoria, no toca Supabase, no gasta
    creditos de AssemblyAI: ver app/main.py linea 118 y app/config.py).
  - app/static/app.js + index.html REALES, sin modificar. Es lo que se
    prueba.
  - /api/brain/extract, /api/soul, /api/soul/generate: REALES. Extraccion,
    verificacion de citas, redaccion de plantilla y render son de verdad.
  - Autenticacion Supabase: SUSTITUIDA via interceptacion de red del script
    de supabase-js (nunca sale a internet) por un cliente falso cuyo
    getSession() entrega un JWT HS256 acuñado con el MISMO helper que ya usa
    el resto de la suite (tests/jwt_helpers.create_test_jwt, que a su vez lee
    el mismo secreto/issuer que app/auth/supabase_auth.py usa en TEST_MODE).
  - WebSocket del Voice Agent: SUSTITUIDO por una clase falsa inyectada via
    page.add_init_script (corre antes que cualquier script de la pagina).
    Permite emitir eventos del agente (transcript.*, tool.call) a voluntad.
  - /api/token y /api/agent-token: INTERCEPTADOS con page.route() y
    respondidos con un token falso — son los unicos que llamarian de verdad
    a AssemblyAI, y ahi es donde se gasta dinero. (TEST_MODE=true ya los
    hace inofensivos en el propio backend, pero esto es cinturon-y-tirantes:
    ni siquiera llegan a la red).

  HALLAZGO DE ARQUITECTURA (documentado, no arreglado aqui — la pieza dice
  "si aparece un fallo real, anotalo, no lo arregles"): en TEST_MODE=true,
  app/tools/brand_brain/store.py devuelve SIEMPRE None/False desde
  get_brand_brain()/save_brand_brain() (linea 21-22 y 51: "Allow test mode to
  skip initialization" / "allow mocking in tests"). Sin sustituir esa
  frontera, cada llamada HTTP a /api/brain/extract arrancaria con un
  BrandBrain vacio y NUNCA se acumularian los 9 nodos entre llamadas: es
  literalmente el problema que el CEO describe ("nadie ha visto nunca los
  nueve nodos llenarse en pantalla"). Se sustituye esa MISMA frontera (no
  Supabase entero, solo las dos funciones que el propio modulo documenta
  como pensadas para mockearse en test) por un diccionario en memoria,
  exactamente el mismo patron que ya usan los tests unitarios existentes
  (tests/test_nueve_nodos.py, con @patch en las mismas dos funciones) pero
  con estado que persiste entre llamadas HTTP dentro de esta prueba. Cero
  lineas de app/ tocadas.
"""
import asyncio
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

# TEST_MODE debe estar en true ANTES de importar app.* (guard/store/config lo
# leen a la primera importacion). tests/conftest.py (ancestro) ya lo hace,
# pero lo reafirmamos aqui por si este archivo se corre suelto.
os.environ["TEST_MODE"] = "true"
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- Sustituir la frontera de persistencia del brand_brain (ver docstring) -
# app/tools/brand_brain/store.py ya documenta estas dos funciones como
# pensadas para mockearse en TEST_MODE ("allow mocking in tests"). Se
# sustituyen ANTES de importar app.main para que los `from ... import
# get_brand_brain` que hacen extractor.py y generator.py (al cargarse, la
# primera vez que se usan) capturen ya la version parcheada.
import app.tools.brand_brain.store as _brand_store  # noqa: E402

_FAKE_BRAIN_DB: dict = {}


def _fake_get_brand_brain(session_token):
    return _FAKE_BRAIN_DB.get(session_token)


def _fake_save_brand_brain(session_token, brand_brain):
    if not brand_brain.all_sections_valid():
        from app.tools.brand_brain.models import CitationInvariantError

        raise CitationInvariantError(
            f"seccion invalida para session_token={session_token}"
        )
    _FAKE_BRAIN_DB[session_token] = brand_brain
    return True


_brand_store.get_brand_brain = _fake_get_brand_brain
_brand_store.save_brand_brain = _fake_save_brand_brain

import uvicorn  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from app.main import app as fastapi_app  # noqa: E402
from tests.jwt_helpers import create_test_jwt  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "_salida"
OUT_DIR.mkdir(exist_ok=True)

TEST_USER_ID = "e2e00000-0000-4000-8000-000000000019"

SECTION_ORDER = [
    "diagnostico",
    "brand_journey",
    "charco",
    "icp",
    "contrarian",
    "asociaciones",
    "identidad",
    "oferta",
    "lead_magnet",
]

# Contenido + cita literal por seccion. Los campos de "content" son
# exactamente los que app/tools/brand_brain/extractor.py::normalize_section_content
# espera por nodo (todos los campos obligatorios 🔒 de
# app/tools/brand_brain/questions.py estan cubiertos).
SECTIONS = {
    "diagnostico": {
        "citation": (
            "Right now I honestly consider myself a stuck creator, I have "
            "been posting content for two years without any real "
            "monetization to show for it."
        ),
        "content": {
            "etapa": "creador atascado",
            "habilidad_a_desbloquear": "ingenieria de ofertas",
            "prohibicion": "no lanzar cursos genericos",
            "postura": "estudiante",
        },
    },
    "brand_journey": {
        "citation": (
            "What I actually want is to become the go-to authority for "
            "bootstrapped SaaS founders who are stuck doing marketing on "
            "their own."
        ),
        "content": {
            "resultado_deseado": "become the go-to authority for bootstrapped SaaS founders",
            "de_que_ser_conocido": "turning technical founders into confident marketers",
            "que_hacer": "publish weekly teardown videos of real founder funnels",
            "que_aprender": "how to structure a signature framework people can repeat",
        },
    },
    "charco": {
        "citation": (
            "I have helped eleven founders cut their acquisition cost in "
            "half last year, that is the achievement that backs me up here."
        ),
        "content": {
            "problema": "founders burning ad budget on channels that never convert",
            "nivel": "charco",
            "logro_que_lo_respalda": "helped eleven founders cut acquisition cost in half last year",
        },
    },
    "icp": {
        "citation": (
            "My ideal client is a solo founder who just raised a seed "
            "round and suddenly the burn rate is climbing fast."
        ),
        "content": {
            "quien_decide": "solo founder or head of growth with signing power",
            "disparador_de_urgencia": "just raised a seed round and burn rate is climbing fast",
            "poder_adquisitivo": "two to five thousand dollars a month marketing budget",
        },
    },
    "contrarian": {
        "citation": (
            "Everyone believes you need to post daily on every platform, "
            "but I honestly think two platforms mastered beat five "
            "mediocre ones."
        ),
        "content": {
            "creencia_comun": "everyone believes you need to post daily on every platform",
            "postura_opuesta": "two platforms mastered beat five platforms mediocre",
            "prueba": "clients who cut down to two platforms doubled their engagement",
        },
    },
    "asociaciones": {
        "citation": (
            "I want to be associated with brands like Basecamp and Ahrefs, "
            "definitely not with growth hacking gurus."
        ),
        "content": {
            "deseadas": "Basecamp, Ahrefs, indie hackers community",
            "prohibidas": "growth hacking gurus, fake urgency countdown timers",
        },
    },
    "identidad": {
        "citation": (
            "My brand voice should feel direct and technical, with a bit "
            "of dry humor, in cobalt blue and near black."
        ),
        "content": {
            "voz": "direct, technical, dry humor",
            "colores": "cobalt blue and near black",
            "tipografias": "Space Grotesk and Inter",
        },
    },
    "oferta": {
        "citation": (
            "Our offer is built to double qualified demo bookings in "
            "ninety days, with the client reviewing content only thirty "
            "minutes a week."
        ),
        "content": {
            "resultado_sonado": "double qualified demo bookings in ninety days",
            "probabilidad_percibida": "forty case studies with verified before and after numbers",
            "retraso": "first qualified demo booked within two weeks",
            "esfuerzo": "client only reviews content thirty minutes a week",
            "componentes": "three landing page rewrites plus weekly funnel audit for ninety days",
        },
    },
    "lead_magnet": {
        "citation": (
            "The lead magnet is a free landing page audit that solves "
            "problem A but reveals they actually need a full funnel "
            "rebuild."
        ),
        "content": {
            "tipo": "revelador",
            "problema_A": "founders do not know why their landing page conversion is low",
            "problema_B_que_revela": "the real fix requires a full funnel rebuild, not a headline tweak",
        },
    },
}

# Cita que el fundador JAMAS dijo (caso negativo, spec paso "Incluye un caso
# negativo"). Se ataca contra "contrarian" antes de mandar su cita real.
INVENTED_CITATION = "the loch ness monster personally endorsed this exact business plan"


# =============================================================================
# Servidor FastAPI real, en un hilo de este mismo proceso (para que el parche
# de store.py de arriba aplique dentro del mismo interprete que sirve las
# peticiones).
# =============================================================================
class _ServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        # Sin esto, uvicorn intenta instalar signal handlers y revienta
        # porque este hilo no es el hilo principal del proceso.
        self.server.install_signal_handlers = lambda: None

    def run(self):
        asyncio.run(self.server.serve())

    def stop(self):
        self.server.should_exit = True


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_server():
    import httpx

    port = _free_port()
    thread = _ServerThread(fastapi_app, "127.0.0.1", port)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    up = False
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1)
            if r.status_code == 200:
                up = True
                break
        except Exception:
            pass
        time.sleep(0.2)
    if not up:
        raise RuntimeError("el servidor de prueba (uvicorn en hilo) no levanto a tiempo")

    yield base_url

    thread.stop()
    thread.join(timeout=5)


# =============================================================================
# Andamiaje del navegador: supabase-js falso (interceptado por red, nunca
# sale a internet), WebSocket falso (add_init_script), y /api/token +
# /api/agent-token interceptados.
# =============================================================================
FAKE_SUPABASE_JS_TEMPLATE = """
window.supabase = {
  createClient: function(url, key) {
    return {
      auth: {
        onAuthStateChange: function(cb) { window.__authStateCb = cb; },
        getSession: async function() {
          return {
            data: {
              session: {
                access_token: %(token)r,
                user: { id: %(user_id)r }
              }
            }
          };
        },
        signInWithOAuth: async function() { return { data: {}, error: null }; },
        signOut: async function() { return {}; }
      }
    };
  }
};
"""

FAKE_WEBSOCKET_INIT_SCRIPT = """
(function() {
  window.__wsSent = [];
  window.__lastWs = null;

  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0; // CONNECTING
      this.onopen = null;
      this.onmessage = null;
      this.onerror = null;
      this.onclose = null;
      window.__lastWs = this;
      const self = this;
      setTimeout(function() {
        self.readyState = 1; // OPEN
        if (self.onopen) self.onopen({});
      }, 0);
    }
    send(data) {
      window.__wsSent.push(data);
    }
    close() {
      this.readyState = 3; // CLOSED
      if (this.onclose) this.onclose({});
    }
  }
  FakeWebSocket.CONNECTING = 0;
  FakeWebSocket.OPEN = 1;
  FakeWebSocket.CLOSING = 2;
  FakeWebSocket.CLOSED = 3;

  window.WebSocket = FakeWebSocket;

  // Puente para que Python empuje eventos del agente al ultimo WS creado.
  window.__emitWs = function(msg) {
    if (window.__lastWs && window.__lastWs.onmessage) {
      window.__lastWs.onmessage({ data: JSON.stringify(msg) });
    }
  };
})();
"""


def _emit_ws(page, msg: dict):
    page.evaluate("(m) => window.__emitWs(m)", msg)


def _fake_token_route(route):
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"token": "fake-e2e-assemblyai-token", "credits_remaining": 999}),
    )


def _section_locator(page, section_id: str):
    return page.locator(f'.brain-section[data-section-id="{section_id}"]')


def _brand_soul_label_text(page) -> str:
    return page.locator("#BrandSoul-Label").inner_text()


def test_lock_pinta_y_brand_soul(live_server):
    jwt_token = create_test_jwt(TEST_USER_ID)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        context = browser.new_context(permissions=["microphone"])
        page = context.new_page()
        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"[pageerror] {exc}"))

        # --- Sustituciones de red / runtime (ver docstring del modulo) ----
        context.route(
            "**/supabase-js@2",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=FAKE_SUPABASE_JS_TEMPLATE
                % {"token": jwt_token, "user_id": TEST_USER_ID},
            ),
        )
        context.route("**/api/token", _fake_token_route)
        context.route("**/api/agent-token", _fake_token_route)
        page.add_init_script(FAKE_WEBSOCKET_INIT_SCRIPT)

        page.goto(live_server)

        # Login: la sesion falsa ya "existe" (getSession la devuelve), asi
        # que el Main-App debe aparecer sin tocar el boton de Google.
        expect(page.locator("#Main-App")).to_be_visible(timeout=10000)

        # Estado inicial: 9 ghosts, 0 brain-section.
        expect(page.locator(".ghost")).to_have_count(9)
        expect(page.locator(".brain-section")).to_have_count(0)

        # Arranca la "sesion de voz" (todo simulado: WS falso, mic falso,
        # /api/agent-token interceptado).
        page.click("#micBtn")

        # Espera a que el WS falso este abierto y app.js haya mandado
        # session.update (onopen dispara sync, dale un respiro al loop de
        # eventos del navegador).
        page.wait_for_function("window.__lastWs && window.__lastWs.readyState === 1", timeout=10000)
        _emit_ws(page, {"type": "session.ready", "session_id": "e2e-fake-session"})

        painted_ids: set[str] = set()

        def _confirm_section(section_id: str, confirmed: bool, call_id: str):
            """Emite transcript.user + tool.call y espera la respuesta real
            de /api/brain/extract del backend REAL, devolviendo su JSON."""
            data = SECTIONS[section_id]
            _emit_ws(page, {"type": "transcript.user", "text": data["citation"]})
            with page.expect_response(
                lambda r: r.url.endswith("/api/brain/extract") and r.request.method == "POST"
            ) as resp_info:
                _emit_ws(
                    page,
                    {
                        "type": "tool.call",
                        "name": "extract_brand_brain",
                        "call_id": call_id,
                        "arguments": {
                            "sections": [
                                {
                                    "id": section_id,
                                    "citation_text": data["citation"],
                                    "citation_source": "usuario",
                                    "confirmed": confirmed,
                                    "content": data["content"],
                                }
                            ]
                        },
                    },
                )
            resp = resp_info.value
            assert resp.status == 200, f"/api/brain/extract devolvio {resp.status} para {section_id}"
            return resp.json()

        def _attempt_invented_citation(section_id: str, call_id: str) -> dict:
            """Caso negativo: NO se emite ningun transcript.user con esta
            cita (el fundador nunca la dijo). El backend debe descartarla."""
            with page.expect_response(
                lambda r: r.url.endswith("/api/brain/extract") and r.request.method == "POST"
            ) as resp_info:
                _emit_ws(
                    page,
                    {
                        "type": "tool.call",
                        "name": "extract_brand_brain",
                        "call_id": call_id,
                        "arguments": {
                            "sections": [
                                {
                                    "id": section_id,
                                    "citation_text": INVENTED_CITATION,
                                    "citation_source": "usuario",
                                    "confirmed": True,
                                    "content": SECTIONS[section_id]["content"],
                                }
                            ]
                        },
                    },
                )
            resp = resp_info.value
            assert resp.status == 200
            return resp.json()

        # ------------------------------------------------------------------
        # PARTE A — los 9 nodos, en orden, pintandose al confirmarse.
        # ------------------------------------------------------------------

        # 01 diagnostico — confirmado directo
        _confirm_section("diagnostico", confirmed=True, call_id="call_1")
        painted_ids.add("diagnostico")
        loc = _section_locator(page, "diagnostico")
        expect(loc).to_have_count(1)
        expect(loc).to_contain_text("Confirmed")
        expect(loc).to_contain_text(SECTIONS["diagnostico"]["citation"])
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 1 of 9 sections ready")
        expect(page.locator(".ghost")).to_have_count(9 - len(painted_ids))

        # 02 brand_journey — confirmado directo
        _confirm_section("brand_journey", confirmed=True, call_id="call_2")
        painted_ids.add("brand_journey")
        loc = _section_locator(page, "brand_journey")
        expect(loc).to_contain_text("Confirmed")
        expect(loc).to_contain_text(SECTIONS["brand_journey"]["citation"])
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 2 of 9 sections ready")
        expect(page.locator(".ghost")).to_have_count(9 - len(painted_ids))

        # 03 charco — confirmado directo
        _confirm_section("charco", confirmed=True, call_id="call_3")
        painted_ids.add("charco")
        loc = _section_locator(page, "charco")
        expect(loc).to_contain_text("Confirmed")
        expect(loc).to_contain_text(SECTIONS["charco"]["citation"])
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 3 of 9 sections ready")

        # 04 icp — EN DOS PASOS: primero propuesto, luego confirmado.
        _confirm_section("icp", confirmed=False, call_id="call_4a")
        painted_ids.add("icp")  # existe (propuesto) desde este punto
        loc = _section_locator(page, "icp")
        expect(loc).to_have_count(1)
        expect(loc).to_contain_text("Proposed")
        expect(loc).to_contain_text(SECTIONS["icp"]["citation"])
        assert loc.evaluate("el => getComputedStyle(el).borderStyle") == "dotted"
        # Propuesto no confirmado: el contador NO debe subir todavia.
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 3 of 9 sections ready")

        _confirm_section("icp", confirmed=True, call_id="call_4b")
        loc = _section_locator(page, "icp")
        expect(loc).to_contain_text("Confirmed")
        assert loc.evaluate("el => getComputedStyle(el).borderStyle") == "solid"
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 4 of 9 sections ready")

        # CASO NEGATIVO — una cita que el fundador NUNCA dijo, contra
        # "contrarian" (antes de mandarle su cita real). No debe pintar, y
        # debe reportarse como descarte explicito.
        rejected = _attempt_invented_citation("contrarian", call_id="call_5_negativo")
        assert rejected.get("skipped_sections") == [
            {"id": "contrarian", "reason": "cita_no_encontrada"}
        ], f"se esperaba el descarte explicito, llego: {rejected.get('skipped_sections')}"
        expect(_section_locator(page, "contrarian")).to_have_count(0)
        expect(page.locator(".ghost")).to_have_count(9 - len(painted_ids))
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 4 of 9 sections ready")

        # 05 contrarian — ahora con su cita REAL, confirmado directo.
        _confirm_section("contrarian", confirmed=True, call_id="call_6")
        painted_ids.add("contrarian")
        loc = _section_locator(page, "contrarian")
        expect(loc).to_contain_text("Confirmed")
        expect(loc).to_contain_text(SECTIONS["contrarian"]["citation"])
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 5 of 9 sections ready")

        # 06 asociaciones
        _confirm_section("asociaciones", confirmed=True, call_id="call_7")
        painted_ids.add("asociaciones")
        loc = _section_locator(page, "asociaciones")
        expect(loc).to_contain_text("Confirmed")
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 6 of 9 sections ready")

        # 07 identidad
        _confirm_section("identidad", confirmed=True, call_id="call_8")
        painted_ids.add("identidad")
        loc = _section_locator(page, "identidad")
        expect(loc).to_contain_text("Confirmed")
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 7 of 9 sections ready")

        # 08 oferta
        _confirm_section("oferta", confirmed=True, call_id="call_9")
        painted_ids.add("oferta")
        loc = _section_locator(page, "oferta")
        expect(loc).to_contain_text("Confirmed")
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 8 of 9 sections ready")

        # 09 lead_magnet — el ultimo, cierra 9/9.
        _confirm_section("lead_magnet", confirmed=True, call_id="call_10")
        painted_ids.add("lead_magnet")
        loc = _section_locator(page, "lead_magnet")
        expect(loc).to_contain_text("Confirmed")

        assert painted_ids == set(SECTION_ORDER), "faltan nodos por pintar"
        expect(page.locator(".ghost")).to_have_count(0)
        expect(page.locator(".brain-section")).to_have_count(9)
        expect(page.locator("#BrandSoul-Label")).to_have_text("Brand Soul — 9 of 9 sections ready")
        expect(page.locator("#BrandSoul-Btn")).to_be_enabled()

        # Screenshot del panel con los 9 nodos pintados (antes de abrir el
        # overlay del Brand Soul).
        panel_screenshot_path = OUT_DIR / "panel_9_nodos_pintados.png"
        page.screenshot(path=str(panel_screenshot_path), full_page=True)

        # ------------------------------------------------------------------
        # PARTE B — el Brand Soul se genera de verdad.
        # ------------------------------------------------------------------
        with page.expect_response(
            lambda r: r.url.endswith("/api/soul/generate") and r.request.method == "POST"
        ) as generate_resp_info:
            page.click("#BrandSoul-Btn")

        expect(page.locator("#BrandSoul-Overlay")).to_be_visible(timeout=10000)

        generate_resp = generate_resp_info.value
        assert generate_resp.status == 200, (
            f"/api/soul/generate devolvio {generate_resp.status}: {generate_resp.text()}"
        )
        soul_data = generate_resp.json()
        html_doc = soul_data["html"]
        assert "<html" in html_doc.lower(), "la respuesta no trae un documento HTML"

        # Al menos 3 de las 9 citas literales del fundador deben aparecer
        # textualmente en el documento generado (invariante del producto:
        # ninguna cita inventada, todas verbatim de lo que dijo el fundador).
        citations_present = [
            section_id
            for section_id in SECTION_ORDER
            if SECTIONS[section_id]["citation"] in html_doc
        ]
        assert len(citations_present) >= 3, (
            f"solo {len(citations_present)} citas literales aparecieron en el "
            f"Brand Soul generado: {citations_present}"
        )

        # Espera a que el overlay termine de pintar el contenido real en el
        # DOM (no solo la respuesta de red) antes del segundo screenshot.
        expect(page.locator("#BrandSoul-Loading")).to_be_hidden(timeout=10000)
        expect(page.locator("#BrandSoul-Content")).not_to_be_empty()

        soul_html_path = OUT_DIR / "brand_soul_generado.html"
        soul_html_path.write_text(html_doc, encoding="utf-8")

        soul_screenshot_path = OUT_DIR / "brand_soul_abierto.png"
        page.screenshot(path=str(soul_screenshot_path), full_page=True)

        context.close()
        browser.close()

    # Verificacion final de que los 3 artefactos quedaron en disco para el CEO.
    assert soul_html_path.exists()
    assert panel_screenshot_path.exists()
    assert soul_screenshot_path.exists()
    print(f"\n[PIEZA 19] HTML del Brand Soul: {soul_html_path}")
    print(f"[PIEZA 19] Screenshot panel 9 nodos: {panel_screenshot_path}")
    print(f"[PIEZA 19] Screenshot Brand Soul abierto: {soul_screenshot_path}")
