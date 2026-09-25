"""Tests for Editing Router Stage 1 (Pieza 81 — Bloque E)."""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
    list_jobs,
    mark_failed,
)
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_or_create_edit, save_edit

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class MockScript:
    """Mock script model for testing."""

    def __init__(self, state: str = "locked", num_scenes: int = 2) -> None:
        self.state = state
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 60
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Texto Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
        scenes_list = []
        for i in range(1, num_scenes + 1):
            scenes_list.append({
                "n": i,
                "start_s": (i - 1) * 5.0,
                "end_s": i * 5.0,
                "phase": "hook" if i == 1 else "body_1",
                "spoken_text": f"Spoken text for scene {i}",
                "shot": "medium shot",
                "on_screen_text": f"Text scene {i}",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            })
        self.scenes = scenes_list

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }


# Balance for guard credit mock
_user_credits = 100


def _mock_deduct_credits(session_token: str, amount: int) -> int:
    global _user_credits
    if _user_credits < amount:
        raise HTTPException(status_code=402, detail="Insufficient credits balance")
    _user_credits -= amount
    return _user_credits


def _mock_get_remaining_credits(session_token: str) -> int:
    global _user_credits
    return _user_credits


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resets storage and mocks external dependencies."""
    global _user_credits
    _user_credits = 100
    _reset_local_jobs()
    _reset_local_edits()

    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr(
        "app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test"
    )
    monkeypatch.setattr("app.guard.guard.deduct_credits", _mock_deduct_credits)
    monkeypatch.setattr("app.guard.guard.get_remaining_credits", _mock_get_remaining_credits)
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)

    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret")


def _add_scene_takes_and_transcripts(session_token: str = "tok_test", idea_id: str = "idea1") -> None:
    """Helper to add takes and transcripts for scenes 1 and 2."""
    # Scene 1 take & transcript
    t1 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="a_roll_take",
        credits=0,
    )
    t1["status"] = "done"
    t1["output"] = {"storage_path": "takes/s1.mp4", "duration_ms": 5000}
    _reset_local_jobs_insert(t1)

    tr1 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=1,
        kind="transcript",
        credits=0,
        input={"take_job_id": t1["id"]},
    )
    tr1["status"] = "done"
    tr1["output"] = {
        "words": [
            {"text": "Hola", "start_ms": 100, "end_ms": 600},
            {"text": "mundo", "start_ms": 700, "end_ms": 1200},
        ]
    }
    _reset_local_jobs_insert(tr1)

    # Scene 2 take & transcript
    t2 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=2,
        kind="a_roll_take",
        credits=0,
    )
    t2["status"] = "done"
    t2["output"] = {"storage_path": "takes/s2.mp4", "duration_ms": 4000}
    _reset_local_jobs_insert(t2)

    tr2 = create_job(
        session_token=session_token,
        idea_id=idea_id,
        scene_n=2,
        kind="transcript",
        credits=0,
        input={"take_job_id": t2["id"]},
    )
    tr2["status"] = "done"
    tr2["output"] = {
        "words": [
            {"text": "Segunda", "start_ms": 100, "end_ms": 800},
            {"text": "escena", "start_ms": 900, "end_ms": 1500},
        ]
    }
    _reset_local_jobs_insert(tr2)


def _reset_local_jobs_insert(job: dict[str, Any]) -> None:
    from app.audiovisual.jobs import _jobs_lock, _local_jobs
    with _jobs_lock:
        _local_jobs[job["id"]] = job


def test_1_auth_and_script_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """1. Sin header -> 401. Guion no bloqueado -> 409 script_not_locked."""
    # Sin header -> 401
    resp_no_auth = client.get("/api/editing/idea1")
    assert resp_no_auth.status_code == 401

    # Guion no bloqueado (draft)
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="draft")
    )
    resp_draft = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_draft.status_code == 409
    assert resp_draft.json()["code"] == "script_not_locked"

    # Guion no existe (None)
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: None
    )
    resp_none = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_none.status_code == 409
    assert resp_none.json()["code"] == "script_not_locked"


def test_2_get_state_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """2. GET con tomas + transcripciones -> timeline, captions_words, ir con frame_zero, raw.status ausente."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    resp = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["edit_version"] >= 1
    assert data["timeline"] is not None
    assert len(data["captions_words"]) > 0
    assert data["missing_takes"] == []
    assert data["ir"] is not None
    assert data["ir"]["frame_zero"]["text"] == "Texto Hook"
    assert "status" not in data["raw"] or data["raw"].get("status") is None


def test_3_missing_take(monkeypatch: pytest.MonkeyPatch) -> None:
    """3. Falta una toma -> GET da missing_takes=[2] y POST /raw 409 missing_takes."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    # Solo agregar toma para escena 1
    t1 = create_job(
        session_token="tok_test", idea_id="idea1", scene_n=1, kind="a_roll_take"
    )
    t1["status"] = "done"
    t1["output"] = {"storage_path": "takes/s1.mp4", "duration_ms": 5000}
    _reset_local_jobs_insert(t1)

    resp_get = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["missing_takes"] == [2]
    assert resp_get.json()["timeline"] is None

    resp_post = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_post.status_code == 409
    assert resp_post.json()["code"] == "missing_takes"
    assert resp_post.json()["scenes"] == [2]


def test_4_post_raw_idempotency_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """4. POST /raw crea un raw_render con credits=0; repetirlo no crea otro; tras failed crea uno nuevo (retry1)."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # 1. Crear raw_render
    resp1 = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp1.status_code == 202
    data1 = resp1.json()
    assert data1["created"] is True
    job1 = data1["job"]
    assert job1["credits"] == 0
    assert job1["kind"] == "raw_render"

    # 2. Repetir POST con mismo timeline -> created=False
    resp2 = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["created"] is False
    assert data2["job"]["id"] == job1["id"]

    # 3. Marcar job1 como failed -> nuevo POST crea retry1
    mark_failed(job1["id"], error="Render test error")
    resp3 = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp3.status_code == 202
    data3 = resp3.json()
    assert data3["created"] is True
    assert data3["job"]["id"] != job1["id"]
    assert ":retry1" in data3["job"]["idempotency_key"]


def test_5_service_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Servicio no configurado -> 503 en /raw y /render."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "")

    resp_raw = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_raw.status_code == 503
    assert resp_raw.json()["code"] == "render_service_not_configured"

    resp_render = client.post(
        "/api/editing/idea1/render", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_render.status_code == 503
    assert resp_render.json()["code"] == "render_service_not_configured"


def test_6_rate_limit_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """6. 13 raw en la última hora -> 429."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # Crear 13 jobs raw_render
    for i in range(13):
        create_job(
            session_token="tok_test",
            idea_id="idea1",
            scene_n=None,
            kind="raw_render",
            idempotency_key=f"raw_job_limit_{i}",
        )

    resp = client.post(
        "/api/editing/idea1/raw", headers={"authorization": "Bearer tok_test"}
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limit_exceeded"


def test_7_patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """7. PATCH settings face, version_conflict, trim acotado, op desconocida -> 422."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # 1. Cambiar face de escena 1 a False
    resp1 = client.patch(
        "/api/editing/idea1/settings",
        json={"op": "face", "scene_n": 1, "value": False, "expected_version": 1},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["edit_version"] == 2

    # 2. Intento con versión vieja (1) -> 409 version_conflict
    resp_conf = client.patch(
        "/api/editing/idea1/settings",
        json={"op": "face", "scene_n": 1, "value": True, "expected_version": 1},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp_conf.status_code == 409
    assert resp_conf.json()["code"] == "version_conflict"
    assert resp_conf.json()["current"] == 2

    # 3. Trim 900 -> acotado a 500
    resp_trim = client.patch(
        "/api/editing/idea1/settings",
        json={
            "op": "trim",
            "scene_n": 1,
            "value": {"start_ms": 900, "end_ms": -800},
            "expected_version": 2,
        },
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp_trim.status_code == 200
    trim_val = resp_trim.json()["timeline"]["scenes"][0]["trim"]
    assert trim_val["start_ms"] == 500
    assert trim_val["end_ms"] == -500

    # 4. Op desconocida -> 422
    resp_bad = client.patch(
        "/api/editing/idea1/settings",
        json={"op": "invalid_op", "expected_version": 3},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp_bad.status_code == 422


def test_8_patch_captions(monkeypatch: pytest.MonkeyPatch) -> None:
    """8. PATCH captions -> GET muestra edited_text; word_id malo -> 422; texto 41 chars -> 422."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # 1. PATCH caption exitoso
    resp = client.patch(
        "/api/editing/idea1/captions/s1w0",
        json={"text": "Editado", "expected_version": 1},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp.status_code == 200

    # GET posterior muestra edited_text
    get_resp = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    words = get_resp.json()["captions_words"]
    edited_word = next((w for w in words if w["id"] == "s1w0"), None)
    assert edited_word is not None
    assert edited_word["edited_text"] == "Editado"

    # 2. word_id malo -> 422
    resp_bad_id = client.patch(
        "/api/editing/idea1/captions/bad_word_format",
        json={"text": "Text", "expected_version": 2},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp_bad_id.status_code == 422

    # 3. texto de 41 caracteres -> 422
    resp_long = client.patch(
        "/api/editing/idea1/captions/s1w0",
        json={"text": "a" * 41, "expected_version": 2},
        headers={"authorization": "Bearer tok_test"},
    )
    assert resp_long.status_code == 422


def test_9_post_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """9. POST /render sin crudo listo -> 409; listo -> crea render, descuenta 20; doble clic -> created=False; sin saldo -> 402."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # 1. Sin crudo done/fresh -> 409 raw_not_ready
    resp_no_raw = client.post(
        "/api/editing/idea1/render", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_no_raw.status_code == 409
    assert resp_no_raw.json()["code"] == "raw_not_ready"

    # Preparar crudo done & fresh
    get_resp = client.get(
        "/api/editing/idea1", headers={"authorization": "Bearer tok_test"}
    )
    t_hash = get_resp.json()["timeline"]["hash"]
    edit_ver = get_resp.json()["edit_version"]

    save_edit(
        "tok_test",
        "idea1",
        {
            "raw_render": {
                "status": "done",
                "storage_path": "renders/raw.mp4",
                "timeline_hash": t_hash,
            }
        },
        expected_version=edit_ver,
    )

    # 2. POST /render exitoso: crea render con credits=20, charged=True, descuenta 20
    resp_render1 = client.post(
        "/api/editing/idea1/render", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_render1.status_code == 202
    data1 = resp_render1.json()
    assert data1["created"] is True
    assert data1["job"]["credits"] == 20
    assert data1["job"]["charged"] is True
    assert data1["credits_remaining"] == 80

    # 3. Doble clic -> created=False y el saldo no vuelve a bajar
    resp_render2 = client.post(
        "/api/editing/idea1/render", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_render2.status_code == 202
    data2 = resp_render2.json()
    assert data2["created"] is False
    assert data2["credits_remaining"] == 80

    # 4. Sin saldo (deduct lanza 402) -> 402, el job queda cancelled y charged=False
    global _user_credits
    _user_credits = 5  # Menos de 20 créditos

    # Marcar el job anterior como failed para forzar un nuevo intento de render
    mark_failed(data1["job"]["id"], error="Failed render")

    resp_402 = client.post(
        "/api/editing/idea1/render", headers={"authorization": "Bearer tok_test"}
    )
    assert resp_402.status_code == 402

    # Verificar que el job creado quedó cancelled y charged=False
    jobs = list_jobs("tok_test", "idea1")
    failed_render_jobs = [
        j for j in jobs if j.get("kind") == "render" and j.get("status") == "cancelled"
    ]
    assert len(failed_render_jobs) > 0
    cancelled_job = failed_render_jobs[0]
    assert cancelled_job["charged"] is False


def test_10_share_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """10. share-link: 404 sin render; con render done -> URL firmada."""
    monkeypatch.setattr(
        "app.editing.router._check_script", lambda tok, idea: MockScript(state="locked")
    )
    _add_scene_takes_and_transcripts()

    # 1. Sin render -> 404
    resp1 = client.get(
        "/api/editing/idea1/share-link", headers={"authorization": "Bearer tok_test"}
    )
    assert resp1.status_code == 404

    # 2. Con render done -> 200 con url firmada
    edit = get_or_create_edit("tok_test", "idea1")
    save_edit(
        "tok_test",
        "idea1",
        {"render": {"status": "done", "storage_path": "renders/final.mp4"}},
        expected_version=edit["version"],
    )

    resp2 = client.get(
        "/api/editing/idea1/share-link", headers={"authorization": "Bearer tok_test"}
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "url" in data2
    assert data2["expires_in"] == 604800


def test_11_internal_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """11. progress interno: sin/malo Bearer -> 401; bueno -> 204 y el job tiene pct en su output."""
    # Crear un job para actualizar progress
    job = create_job(
        session_token="tok_test",
        idea_id="idea1",
        scene_n=None,
        kind="render",
    )
    job_id = job["id"]

    # 1. Sin Bearer -> 401
    resp_no_auth = client.post(f"/api/editing/internal/jobs/{job_id}/progress")
    assert resp_no_auth.status_code == 401

    # 2. Bearer incorrecto -> 401
    resp_bad_bearer = client.post(
        f"/api/editing/internal/jobs/{job_id}/progress",
        headers={"authorization": "Bearer wrong_secret"},
        json={"pct": 50},
    )
    assert resp_bad_bearer.status_code == 401

    # 3. Bearer correcto -> 204 y job actualizado
    resp_ok = client.post(
        f"/api/editing/internal/jobs/{job_id}/progress",
        headers={"authorization": "Bearer test_secret"},
        json={"pct": 75},
    )
    assert resp_ok.status_code == 204

    updated_job = get_job(job_id)
    assert updated_job is not None
    assert updated_job.get("output", {}).get("pct") == 75
