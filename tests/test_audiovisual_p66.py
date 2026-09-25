"""
Unit and integration tests for PIEZA 66:
POST /api/audiovisual/{idea_id}/prepare endpoint tests.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scripting.scripts import FrameZero, Scene, Script, _save_script

from app.guard import guard

TEST_IDEA_ID = "idea_p66_audiovisual"


@pytest.fixture(autouse=True)
def clean_p66_environment():
    guard._sessions.clear()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    guard._sessions.clear()


def make_scene(n: int, stock_q: str | None = None, visual_p: str | None = None) -> Scene:
    return Scene(
        n=n,
        start_s=float((n - 1) * 5),
        end_s=float(n * 5),
        phase="hook" if n == 1 else "body_1",
        spoken_text=f"Spoken text for scene {n} in short video.",
        shot="Medium shot",
        b_roll=None,
        on_screen_text=f"Scene {n}",
        acting_note="Normal tone",
        sound="upbeat",
        asset_type="a_roll",
        stock_query=stock_q,
        visual_prompt=visual_p,
    )


def test_prepare_without_auth_returns_401(authenticated_client):
    res = authenticated_client.post(
        f"/api/audiovisual/{TEST_IDEA_ID}/prepare",
        headers={"authorization": ""},
    )
    assert res.status_code == 401


def test_prepare_draft_script_returns_409(authenticated_client):
    session_token = authenticated_client._test_session_token

    draft_script = Script(
        session_id=session_token,
        idea_id=TEST_IDEA_ID,
        title="Draft Title",
        angle="Draft Angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="o", why_it_stops_the_scroll="w"),
        scenes=[make_scene(i) for i in range(1, 6)],
        state="draft",
    )
    _save_script(draft_script)

    res = authenticated_client.post(f"/api/audiovisual/{TEST_IDEA_ID}/prepare")
    assert res.status_code == 409


def test_prepare_locked_script_fills_prompts_and_is_idempotent(authenticated_client):
    session_token = authenticated_client._test_session_token

    locked_script = Script(
        session_id=session_token,
        idea_id=TEST_IDEA_ID,
        title="Locked Title",
        angle="Locked Angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=FrameZero(visual="v", on_screen_text="o", why_it_stops_the_scroll="w"),
        scenes=[
            make_scene(1, stock_q=None, visual_p=None),
            make_scene(2, stock_q="null", visual_p="null"),
            make_scene(3, stock_q="clean query", visual_p="clean visual prompt"),
            make_scene(4, stock_q=None, visual_p=None),
            make_scene(5, stock_q=None, visual_p=None),
        ],
        state="locked",
    )
    _save_script(locked_script)

    llm_fill_response = {
        "scenes": [
            {"n": 1, "stock_query": "office laptop desk", "visual_prompt": "Office worker with laptop on desk, cinematic, 9:16"},
            {"n": 2, "stock_query": "programmer coding computer", "visual_prompt": "Programmer coding on computer, cinematic, 9:16"},
            {"n": 4, "stock_query": "server room technology", "visual_prompt": "Server room technology, cinematic, 9:16"},
            {"n": 5, "stock_query": "business handshake deal", "visual_prompt": "Business handshake deal, cinematic, 9:16"},
        ]
    }

    mock_gen_model = MagicMock()
    mock_gen_model.generate_content_async = AsyncMock(
        return_value=MagicMock(text=json.dumps(llm_fill_response))
    )

    with patch("app.scripting.scripts._save_script", wraps=_save_script) as mock_save, \
         patch("vertexai.generative_models.GenerativeModel", return_value=mock_gen_model):

        # First call: fills missing prompts, returns changed: true
        res1 = authenticated_client.post(f"/api/audiovisual/{TEST_IDEA_ID}/prepare")
        assert res1.status_code == 200
        body1 = res1.json()
        assert body1["changed"] is True
        assert len(body1["scenes"]) == 5
        mock_save.assert_called_once()

        for s in body1["scenes"]:
            assert s["stock_query"] is not None and s["stock_query"] != "null"
            assert s["visual_prompt"] is not None and s["visual_prompt"] != "null"

        # Second call: all full, returns changed: false without calling model again
        mock_gen_model.generate_content_async.reset_mock()
        mock_save.reset_mock()

        res2 = authenticated_client.post(f"/api/audiovisual/{TEST_IDEA_ID}/prepare")
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["changed"] is False
        mock_gen_model.generate_content_async.assert_not_called()
        mock_save.assert_not_called()
