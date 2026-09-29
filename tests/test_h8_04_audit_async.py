"""H8-04: the audit trail follows async jobs to the end.

In production every render row stayed `queued` forever (no result_ref, credits
null). These tests pin the fix, with Supabase mocked (in-memory stores):

* the audit middleware stores the created job id as `result_ref` (and the
  charged credits) from a 202/200 body, without altering the response;
* the background worker moves those rows to done/failed when the job ends;
* a failing audit-trail write never raises out of the worker;
* the production panel refreshes exactly once per `brandstudio:action-finished`
  event, and a failed card shows the job's error.

Like tests/test_agent_f02_audit.py this never imports app.main.app: it builds
its own FastAPI() with only the agent router + the audit middleware.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.agent import store as agent_store
from app.agent.middleware import AgentActionsAuditMiddleware
from app.agent.router import router as agent_router
from app.audiovisual.jobs import _reset_local_jobs, create_job, get_job
from app.audiovisual.worker import RESOLVERS, process_one_job
from app.guard import guard
from tests.jwt_helpers import create_test_jwt

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = REPO_ROOT / "app" / "static" / "production_panel.js"

USER = "550e8400-e29b-41d4-a716-4466554400a4"
JOB_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _clean_state():
    agent_store._reset_local_actions()
    _reset_local_jobs()
    RESOLVERS.clear()
    yield
    agent_store._reset_local_actions()
    _reset_local_jobs()
    RESOLVERS.clear()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(agent_router)
    app.add_middleware(AgentActionsAuditMiddleware)

    @app.post("/api/editing/{idea_id}/render")
    async def _render(idea_id: str) -> JSONResponse:
        return JSONResponse(
            status_code=202,
            content={"job": {"id": JOB_ID, "status": "pending", "credits": 20}, "created": True},
        )

    @app.post("/api/editing/{idea_id}/render-again")
    async def _render_reused(idea_id: str) -> JSONResponse:
        # Reused job: nothing was charged by this request.
        return JSONResponse(
            status_code=200,
            content={"job": {"id": JOB_ID, "credits": 20}, "created": False},
        )

    @app.post("/api/catalog/{idea_id}/lock")
    async def _lock(idea_id: str) -> JSONResponse:
        return JSONResponse(status_code=200, content={"locked": True})

    return TestClient(app)


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_test_jwt(USER)}"}


def _rows(client: TestClient, headers: dict[str, str], idea_id: str) -> list[dict]:
    res = client.get(f"/api/agent/actions?idea_id={idea_id}", headers=headers)
    assert res.status_code == 200
    return res.json()["actions"]


# ---------------------------------------------------------------- middleware


def test_middleware_stores_result_ref_and_credits_from_202_body(client, headers):
    res = client.post("/api/editing/idea-1/render?idea_id=idea-1", headers=headers)

    # The client still gets the untouched response.
    assert res.status_code == 202
    assert res.json() == {
        "job": {"id": JOB_ID, "status": "pending", "credits": 20},
        "created": True,
    }

    (row,) = _rows(client, headers, "idea-1")
    assert row["status"] == "queued"
    assert row["result_ref"] == JOB_ID
    assert row["credits"] == 20


def test_middleware_records_no_credits_for_a_reused_job(client, headers):
    res = client.post("/api/editing/idea-2/render-again?idea_id=idea-2", headers=headers)
    assert res.status_code == 200

    (row,) = _rows(client, headers, "idea-2")
    assert row["result_ref"] == JOB_ID
    assert row["credits"] is None


def test_middleware_leaves_bodies_without_a_job_alone(client, headers):
    res = client.post("/api/catalog/idea-3/lock", headers=headers)
    assert res.json() == {"locked": True}

    (row,) = _rows(client, headers, "idea-3")
    assert row["result_ref"] is None
    assert row["credits"] is None


def test_voice_row_updated_via_header_also_gets_result_ref(client, headers):
    session = guard.get_or_create_user_session(USER)
    pending = agent_store.create_action(
        session_token=session,
        step="editing",
        source="voice",
        action="editing.render",
        idea_id="idea-4",
        status="proposed",
    )
    res = client.post(
        "/api/editing/idea-4/render?idea_id=idea-4",
        headers={**headers, "X-Agent-Action-Id": pending["id"]},
    )
    assert res.status_code == 202

    (row,) = _rows(client, headers, "idea-4")
    assert row["id"] == pending["id"]
    assert row["result_ref"] == JOB_ID
    assert row["credits"] == 20


# -------------------------------------------------------------------- worker


def _queued_row(session: str, job_id: str) -> dict:
    return agent_store.create_action(
        session_token=session,
        step="audiovisual",
        source="button",
        action="POST /api/audiovisual/{idea_id}/generate",
        idea_id="idea-w",
        status="queued",
        result_ref=job_id,
    )


@pytest.mark.asyncio
async def test_worker_completion_marks_the_row_done():
    session = guard.create_user_session("h8-04-worker-ok", initial_credits=100)
    job = create_job(
        session_token=session, idea_id="idea-w", scene_n=1, kind="ai_image",
        credits=5, cost_usd=0.03, idempotency_key="h804-ok",
    )
    row = _queued_row(session, job["id"])

    async def resolver(_job):
        return {"storage_path": "x/y/z.png", "mime": "image/png"}

    RESOLVERS["ai_image"] = resolver
    assert await process_one_job() is True

    assert get_job(job["id"])["status"] == "done"
    settled = agent_store.get_action(row["id"])
    assert settled["status"] == "done"
    assert settled["error"] is None
    assert settled["updated_at"] >= row["updated_at"]


@pytest.mark.asyncio
async def test_worker_failure_marks_the_row_failed_with_the_job_error():
    session = guard.create_user_session("h8-04-worker-fail", initial_credits=100)
    job = create_job(
        session_token=session, idea_id="idea-w", scene_n=1, kind="ai_video",
        credits=90, cost_usd=0.3, idempotency_key="h804-fail",
    )
    row = _queued_row(session, job["id"])

    async def resolver(_job):
        raise RuntimeError("Render service timed out")

    RESOLVERS["ai_video"] = resolver
    assert await process_one_job() is True

    settled = agent_store.get_action(row["id"])
    assert settled["status"] == "failed"
    assert settled["error"] == "Render service timed out"


@pytest.mark.asyncio
async def test_worker_only_closes_rows_of_its_own_job():
    session = guard.create_user_session("h8-04-worker-iso", initial_credits=100)
    job = create_job(
        session_token=session, idea_id="idea-w", scene_n=1, kind="ai_image",
        credits=0, cost_usd=0.0, idempotency_key="h804-iso",
    )
    mine = _queued_row(session, job["id"])
    other = _queued_row(session, "another-job-id")

    async def resolver(_job):
        return {"storage_path": "a/b.png"}

    RESOLVERS["ai_image"] = resolver
    await process_one_job()

    assert agent_store.get_action(mine["id"])["status"] == "done"
    assert agent_store.get_action(other["id"])["status"] == "queued"


@pytest.mark.asyncio
async def test_update_failures_are_swallowed_by_the_worker(monkeypatch):
    session = guard.create_user_session("h8-04-worker-swallow", initial_credits=100)
    job = create_job(
        session_token=session, idea_id="idea-w", scene_n=1, kind="ai_image",
        credits=5, cost_usd=0.03, idempotency_key="h804-swallow",
    )

    def boom(*_a, **_k):
        raise RuntimeError("Supabase unreachable")

    monkeypatch.setattr(agent_store, "settle_actions_for_job", boom)

    async def resolver(_job):
        return {"storage_path": "a/b.png"}

    RESOLVERS["ai_image"] = resolver
    assert await process_one_job() is True  # no exception escaped
    assert get_job(job["id"])["status"] == "done"


def test_settle_actions_never_raises_when_the_table_call_fails(monkeypatch):
    class _Broken:
        def table(self, *_a, **_k):
            raise RuntimeError("relation agent_actions does not exist")

    monkeypatch.setattr(agent_store, "_get_actions_client", lambda: _Broken())
    assert agent_store.settle_actions_for_job(JOB_ID, "done") == 0


def test_settle_ignores_rows_that_already_finished():
    session = guard.create_user_session("h8-04-settle-final", initial_credits=10)
    done_row = agent_store.create_action(
        session_token=session, step="editing", source="button", action="POST /x",
        status="done", result_ref=JOB_ID,
    )
    assert agent_store.settle_actions_for_job(JOB_ID, "failed", "late") == 0
    assert agent_store.get_action(done_row["id"])["status"] == "done"


# --------------------------------------------------------------------- panel

PANEL_HARNESS = r"""
'use strict';
const registry = Object.create(null);
function El(tag) { this.tagName = String(tag).toUpperCase(); this._children = []; this._attrs = {};
  this.style = {}; this._classes = []; this._text = null; }
El.prototype.setAttribute = function (n, v) { this._attrs[n] = String(v); };
El.prototype.getAttribute = function (n) { return n in this._attrs ? this._attrs[n] : null; };
El.prototype.appendChild = function (c) { this._children.push(c); this._text = null; return c; };
El.prototype.removeChild = function (c) { const i = this._children.indexOf(c); if (i >= 0) this._children.splice(i, 1); return c; };
Object.defineProperty(El.prototype, 'firstChild', { get() { return this._children[0] || null; } });
Object.defineProperty(El.prototype, 'childNodes', { get() { return this._children; } });
Object.defineProperty(El.prototype, 'className', {
  get() { return this._classes.join(' '); }, set(v) { this._classes = String(v).split(/\s+/).filter(Boolean); } });
Object.defineProperty(El.prototype, 'textContent', {
  get() { return this._text !== null ? this._text : this._children.map((c) => c.textContent).join(''); },
  set(v) { this._children = []; this._text = String(v); } });
Object.defineProperty(El.prototype, 'innerHTML', { get() { return ''; }, set() { throw new Error('innerHTML'); } });

for (const id of ['Prod-Jobs', 'Prod-Empty', 'Prod-Subtext']) { registry[id] = new El('div'); }

const listeners = {};
global.document = {
  createElement: (t) => new El(t),
  getElementById: (id) => registry[id] || null,
  addEventListener: (name, fn) => { (listeners[name] = listeners[name] || []).push(fn); },
  head: new El('head'),
};
function fire(name) { (listeners[name] || []).forEach((fn) => fn({ type: name })); }

let rows = [
  { id: 'r1', source: 'button', step: 'editing', action: 'POST /api/editing/{idea_id}/render',
    status: 'failed', credits: 20, created_at: new Date().toISOString(),
    error: 'Render service timed out', result_ref: 'job-1' },
  { id: 'r2', source: 'button', step: 'editing', action: 'POST /api/editing/{idea_id}/render',
    status: 'done', credits: null, created_at: new Date().toISOString(), error: null, result_ref: null },
];
const fetchCalls = [];
global.window = {
  BrandStudio: {
    authenticatedFetch: async (url) => { fetchCalls.push(url); return { ok: true, json: async () => ({ actions: rows }) }; },
    getCurrentScriptIdeaId: () => 'idea-1',
  },
};
global.console = console;
eval(require('fs').readFileSync(process.argv[1], 'utf8'));

function find(el, cls) {
  if ((el.className || '').split(' ').includes(cls)) return el;
  for (const c of el._children) { const f = find(c, cls); if (f) return f; }
  return null;
}
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  const out = { listeners: (listeners['brandstudio:action-finished'] || []).length };

  fire('brandstudio:action-finished');
  await tick(); await tick();
  out.callsAfterOneEvent = fetchCalls.length;

  fire('brandstudio:action-finished');
  await tick(); await tick();
  out.callsAfterTwoEvents = fetchCalls.length;

  const cards = registry['Prod-Jobs']._children;
  out.cardCount = cards.length;
  const err = find(cards[0], 'pp-error');
  out.failedCardError = err ? err.textContent : null;
  out.doneCardError = find(cards[1], 'pp-error') ? 'present' : null;
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
"""


def test_panel_refreshes_once_per_action_finished_event_and_shows_failure_detail():
    node = shutil.which("node")
    assert node is not None, "Node.js must be in PATH"
    res = subprocess.run(
        [node, "-e", PANEL_HARNESS, str(PANEL_JS)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), check=False,
    )
    assert res.returncode == 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    out = json.loads(res.stdout.strip().splitlines()[-1])

    assert out["listeners"] == 1
    assert out["callsAfterOneEvent"] == 1
    assert out["callsAfterTwoEvents"] == 2
    assert out["cardCount"] == 2
    assert out["failedCardError"] == "Render service timed out"
    assert out["doneCardError"] is None


def test_app_js_announces_non_get_requests_with_a_single_line():
    app_js = (REPO_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert app_js.count("brandstudio:action-finished") == 1
    line = next(ln for ln in app_js.splitlines() if "brandstudio:action-finished" in ln)
    assert "toUpperCase() !== 'GET'" in line
