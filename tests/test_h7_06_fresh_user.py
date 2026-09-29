"""H7-06 — a brand-new account walks the lap with no seeded data (report piece).

Every external dependency (LLMs, Supabase, render service) is mocked and the network
is locked by tests/conftest.py. Credits go through the REAL in-memory guard, so the
numbers printed here are the numbers the endpoints charge.

Run with `-s` to see the step table:
    python -m pytest -q -s tests/test_h7_06_fresh_user.py
"""
import os

os.environ["TEST_MODE"] = "true"

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.audiovisual.jobs import _reset_local_jobs
from app.audiovisual.pricing import CREDITS_TABLE
from app.config import settings
from app.editing import config as editing_config
from app.editing.store import _reset_local_edits
from app.main import app
from tests.jwt_helpers import create_test_jwt

IDEA_ID = "idea_h7_06"


class _Script:
    """Locked 6-scene script: 3 a-roll, 2 stock B-roll, 1 motion graphic."""

    state = "locked"
    title = "H7-06 script"
    funnel_stage = "tofu"
    target_seconds = 30
    timestamp = None
    id = "script-h7-06"
    music_prompt = "calm"
    angle = "expert"
    recording_format = "selfie_natural"
    frame_zero = {"visual": "v", "on_screen_text": "Hook", "why_it_stops_the_scroll": "w"}

    def __init__(self) -> None:
        kinds = ["a_roll", "stock", "a_roll", "motion_graphic", "stock", "a_roll"]
        phases = ["hook", "problem", "insight", "proof", "solution", "cta"]
        self.scenes = [
            SimpleNamespace(
                n=i + 1,
                start_s=i * 5.0,
                end_s=(i + 1) * 5.0,
                phase=phases[i],
                spoken_text=f"Spoken {i + 1}",
                shot="medium",
                on_screen_text=f"Text {i + 1}",
                acting_note="clear",
                sound="",
                asset_type=kinds[i],
            )
            for i in range(6)
        ]

    def model_dump(self, mode: str = "json") -> dict:
        d = {k: getattr(self, k) for k in (
            "state", "title", "funnel_stage", "target_seconds", "frame_zero")}
        d["scenes"] = [vars(s).copy() for s in self.scenes]
        return d


@pytest.fixture(autouse=True)
def _clean():
    _reset_local_jobs()
    _reset_local_edits()
    yield
    _reset_local_jobs()
    _reset_local_edits()


def _row(step: str, resp, credits_after) -> None:
    print(f"STEP | {step:<34} | HTTP {resp.status_code} | credits_after={credits_after}")


def test_fresh_account_walk_and_lap_cost():
    user_id = str(uuid.uuid4())  # brand-new user: no session, no rows, no files
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {create_test_jwt(user_id)}"})

    brain = SimpleNamespace(
        sections=[object()] * 9,
        _metadata={"missing_sections": [], "skipped_sections": []},
        to_dict=lambda: {"sections": {}},
    )
    catalog = SimpleNamespace(
        gate_passed=True, catalog_locked=False,
        model_dump=lambda mode="json": {"ideas": []},
    )
    locked_catalog = SimpleNamespace(
        gate_passed=True, catalog_locked=True,
        model_dump=lambda mode="json": {"ideas": []},
    )

    with patch("app.tools.brand_brain.extractor.extract_and_persist", return_value=brain), \
         patch("app.tools.brand_soul.generator.generate_brand_soul",
               return_value=("<html>soul</html>", "generated")), \
         patch("app.catalog.ideas._check_catalog_cache", return_value=None), \
         patch("app.catalog.ideas.get_or_generate_catalog", new=AsyncMock(return_value=catalog)), \
         patch("app.catalog.ideas.lock_catalog_session", return_value=locked_catalog), \
         patch("app.scripting.scripts._check_script", return_value=None), \
         patch("app.main.generate_script", new=AsyncMock(return_value=_Script())), \
         patch("app.main.lock_script", return_value=_Script()), \
         patch("app.tools.brand_brain.store._get_client", return_value=None), \
         patch("app.editing.router._check_script", return_value=_Script()), \
         patch("app.editing.router.get_brand_brain", return_value=None):

        r = client.get("/api/session")
        _row("GET /api/session (new user)", r, r.json().get("credits_remaining"))
        assert r.status_code == 200
        start = r.json()["credits_remaining"]
        assert start == settings.initial_session_credits

        r = client.post("/api/brain/extract",
                        json={"transcript": "hello world " * 20, "tool_result": {}})
        _row("POST /api/brain/extract", r, r.json().get("credits_remaining"))
        assert r.status_code == 200

        r = client.post("/api/soul/generate", json={"regenerate": False})
        _row("POST /api/soul/generate", r, r.json().get("credits_remaining"))
        assert r.status_code == 200

        r = client.post("/api/catalog/generate")
        _row("POST /api/catalog/generate", r, r.json().get("credits_remaining"))
        assert r.status_code == 200

        r = client.post("/api/catalog/lock")
        _row("POST /api/catalog/lock", r, client.get("/api/session").json()["credits_remaining"])
        assert r.status_code == 200

        r = client.post(f"/api/script/generate?idea_id={IDEA_ID}", json={
            "interview_transcript": "x", "source_mode": "brand_brain", "idea_kind": "standard"})
        _row("POST /api/script/generate", r, r.json().get("credits_remaining"))
        assert r.status_code == 200, r.text

        r = client.post(f"/api/script/{IDEA_ID}/lock")
        _row("POST /api/script/{id}/lock", r, client.get("/api/session").json()["credits_remaining"])
        assert r.status_code == 200

        with patch("app.scripting.scripts._check_script", return_value=_Script()):
            r = client.get(f"/api/audiovisual/{IDEA_ID}/estimate")
        _row("GET /api/audiovisual/{id}/estimate", r,
             client.get("/api/session").json()["credits_remaining"])
        assert r.status_code == 200, r.text
        print("ESTIMATE | credits_total =", r.json()["credits_total"],
              "| by scene =", [(s["asset_type"], s["credits"]) for s in r.json()["scenes"]])

        r = client.get(f"/api/editing/{IDEA_ID}")
        _row("GET /api/editing/{id}", r, client.get("/api/session").json()["credits_remaining"])
        assert r.status_code == 200, r.text
        print("EDITING STATE | render_price =", r.json().get("render_price"),
              "| render_price_kind =", r.json().get("render_price_kind"),
              "| missing_takes =", r.json().get("missing_takes"))

        end = client.get("/api/session").json()["credits_remaining"]

    charged = start - end
    print(f"WALK | start={start} end={end} charged={charged}")
    assert charged == 1 + 20 + 15 + 10  # extract + soul + catalog + script


def test_lap_cost_table():
    """Cost of one lap from code constants (no I/O)."""
    from app.catalog.ideas import CREDITS_COST as CATALOG
    from app.scripting.scripts import CREDITS_COST_GENERATE as SCRIPT

    extract, soul = 1, 20
    render, rerender = editing_config.RENDER_CREDITS, editing_config.RERENDER_CREDITS
    assets_stock = 2 * CREDITS_TABLE["stock"] + CREDITS_TABLE["motion_graphic"]
    assets_ai = 2 * CREDITS_TABLE["ai_image"] + CREDITS_TABLE["motion_graphic"]
    base = extract + soul + CATALOG + SCRIPT + CREDITS_TABLE["base"]
    initial = settings.initial_session_credits

    rows = []
    for label, assets in (("B-roll = stock", assets_stock), ("B-roll = ai_image", assets_ai)):
        for minutes in (15, 30):
            for per_min, tag in ((8, "reserve 8/min (code path)"),
                                 (settings.voice_credits_per_minute, "7.5/min (config)")):
                voice = minutes * per_min
                total = base + assets + render + rerender + voice
                rows.append((label, minutes, tag, voice, total, initial - total))
    for row in rows:
        print("LAP | {} | {} min | {} | voice={} | total={} | left={}".format(*row))
    print(f"LAP-CONSTANTS | extract={extract} soul={soul} catalog={CATALOG} script={SCRIPT} "
          f"render={render} rerender={rerender} initial={initial}")
    assert base == 1 + 20 + 15 + 10
