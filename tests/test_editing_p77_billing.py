"""
Unit tests for PIEZA 77:
- Charge lock reversal (release_charge)
- find_jobs query helper
- Spend guard tracking render CPU cost in SPEND_KINDS
- Storage output path and create_signed_upload_url_at validation
- Guard credit refunding (refund_credits)
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.audiovisual import jobs, spend_guard, storage
from app.guard import guard


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure local memory mode for jobs, storage, and guard in tests."""
    monkeypatch.setattr(jobs, "_get_jobs_client", lambda: None)
    monkeypatch.setattr(storage, "_get_storage_client", lambda: None)
    jobs._reset_local_jobs()
    guard._sessions.clear()
    guard._use_supabase = False
    yield
    jobs._reset_local_jobs()
    guard._sessions.clear()


def test_release_charge():
    """
    1. release_charge: job con charged=True -> True y queda False; segunda llamada -> False.
    Job con charged=False -> False.
    """
    job = jobs.create_job("sess1", "idea1", 1, "render", credits=20, cost_usd=0.01)
    # Initially charged=False
    assert jobs.release_charge(job["id"]) is False

    # Set charged=True
    assert jobs.mark_charged(job["id"]) is True

    # release_charge should succeed once and set charged=False
    assert jobs.release_charge(job["id"]) is True
    updated = jobs.get_job(job["id"])
    assert updated["charged"] is False

    # Second release_charge call returns False
    assert jobs.release_charge(job["id"]) is False


def test_mark_charged_and_release_cycle():
    """
    2. mark_charged -> release_charge -> mark_charged de nuevo funciona (ciclo completo).
    """
    job = jobs.create_job("sess1", "idea1", 1, "render", credits=20)
    assert jobs.mark_charged(job["id"]) is True
    assert jobs.get_job(job["id"])["charged"] is True

    assert jobs.release_charge(job["id"]) is True
    assert jobs.get_job(job["id"])["charged"] is False

    assert jobs.mark_charged(job["id"]) is True
    assert jobs.get_job(job["id"])["charged"] is True


def test_find_jobs():
    """
    3. find_jobs(["render"], ["failed"], charged=True) devuelve solo los que cumplen las 3 condiciones
    y en orden de creación; limit se respeta.
    """
    # Create jobs with specific created_at timestamps
    j1 = jobs.create_job("sess1", "idea1", 1, "render", credits=20)
    jobs.mark_failed(j1["id"], "failed")
    jobs._local_jobs[j1["id"]]["created_at"] = "2026-09-25T10:00:00Z"

    j2 = jobs.create_job("sess1", "idea1", 1, "render", credits=20)
    jobs.mark_failed(j2["id"], "failed")
    jobs._local_jobs[j2["id"]]["created_at"] = "2026-09-25T10:05:00Z"

    j3 = jobs.create_job("sess1", "idea1", 1, "raw_render", credits=0)
    jobs.mark_failed(j3["id"], "failed")
    jobs._local_jobs[j3["id"]]["created_at"] = "2026-09-25T10:02:00Z"

    j4 = jobs.create_job("sess1", "idea1", 1, "render", credits=20)
    jobs.mark_done(j4["id"], {})
    jobs._local_jobs[j4["id"]]["created_at"] = "2026-09-25T10:01:00Z"

    # Mark j1 and j2 as charged
    jobs.mark_charged(j1["id"])
    jobs.mark_charged(j2["id"])

    found = jobs.find_jobs(["render"], ["failed"], charged=True)
    assert len(found) == 2
    assert found[0]["id"] == j1["id"]
    assert found[1]["id"] == j2["id"]

    # Test limit parameter
    found_limited = jobs.find_jobs(["render"], ["failed"], charged=True, limit=1)
    assert len(found_limited) == 1
    assert found_limited[0]["id"] == j1["id"]


def test_spend_guard_spend_kinds():
    """
    4. SPEND_KINDS contiene ai_image, ai_video, music_lyria, raw_render y render;
    AI_KINDS sigue siendo exactamente {"ai_image","ai_video","music_lyria"};
    monthly_ai_spend_usd() suma un job render done del mes con cost_usd=0.01.
    """
    expected_spend_kinds = {"ai_image", "ai_video", "music_lyria", "raw_render", "render"}
    assert spend_guard.SPEND_KINDS == expected_spend_kinds
    assert spend_guard.AI_KINDS == {"ai_image", "ai_video", "music_lyria"}

    now_iso = datetime.now(timezone.utc).isoformat()
    job = jobs.create_job("sess1", "idea1", 1, "render", credits=20, cost_usd=0.01)
    job["status"] = "done"
    job["created_at"] = now_iso

    spend = spend_guard.monthly_ai_spend_usd()
    assert pytest.approx(spend, 0.0001) == 0.01


def test_editing_output_path():
    """
    5. editing_output_path("tok", "idea1", "job9", 2) termina en /idea1/video/job9_a2.mp4 y no contiene tok.
    """
    path = storage.editing_output_path("tok", "idea1", "job9", 2)
    assert path.endswith("/idea1/video/job9_a2.mp4")
    assert "tok" not in path


def test_create_signed_upload_url_at():
    """
    6. create_signed_upload_url_at con ruta válida -> dict con las 3 claves;
    con ../x.mp4, /abs.mp4, a\\b.mp4, x.exe -> ValueError.
    """
    valid_path = "abc12345/idea1/video/job1_a1.mp4"
    res = storage.create_signed_upload_url_at(valid_path)
    assert isinstance(res, dict)
    assert set(res.keys()) == {"storage_path", "signed_upload_url", "token"}
    assert res["storage_path"] == valid_path

    invalid_paths = [
        "../x.mp4",
        "/abs.mp4",
        "a\\b.mp4",
        "x.exe",
        "path with space.mp4",
        "invalid@char.png",
    ]
    for inv in invalid_paths:
        with pytest.raises(ValueError):
            storage.create_signed_upload_url_at(inv)


def test_refund_credits():
    """
    7. refund_credits: en memoria, sesión con 10 créditos + refund 20 -> 30;
    token inexistente -> None; amount=0 -> ValueError.
    """
    token = "session_token_123456"
    guard._sessions[token] = {"credits": 10, "created_at": 100.0}

    new_balance = guard.refund_credits(token, 20, source="test_refund")
    assert new_balance == 30
    assert guard.get_remaining_credits(token) == 30

    assert guard.refund_credits("non_existent_token", 10) is None

    with pytest.raises(ValueError):
        guard.refund_credits(token, 0)

    with pytest.raises(ValueError):
        guard.refund_credits(token, -5)
