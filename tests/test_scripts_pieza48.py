"""
Tests for PIEZA 48 — Generar guion no puede morir por el formato de b_roll.

Requirements:
1. _normalize_b_roll handles str, None, "", dict con description, dict sin claves conocidas, lista, int.
2. Un guion mockeado cuya escena 3 trae b_roll como dict se construye sin error.
3. LLM mockeado que primero devuelve JSON inválido y luego uno válido: 1 reintento, guion devuelto, 1 cobro.
4. LLM que devuelve inválido dos veces: error propagado, 0 cobros, sin tercer intento.
5. Prompt schema updated: "b_roll": "plain text string describing the overlay, or null — never an object".
"""
import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.catalog.ideas import Catalog, CatalogIdea
from app.guard import guard
from app.scripting.scripts import (
    CREDITS_COST_GENERATE,
    _build_generation_prompt,
    _normalize_b_roll,
    _parse_and_build_script,
)
from app.tools.brand_brain.models import BrandBrain, Section


@pytest.fixture(autouse=True)
def _isolate_p66_prompt_fill(monkeypatch):
    """P66 fills missing asset prompts with one extra LLM call after generation.
    These tests count the generation/retry calls only, so that step is stubbed here
    (its own behavior is covered in tests/test_scripts_pieza66.py)."""
    from unittest.mock import AsyncMock

    import app.scripting.scripts as scripts_mod

    monkeypatch.setattr(scripts_mod, "_fill_missing_asset_prompts", AsyncMock(return_value=False))


@pytest.fixture
def api_client():
    """TestClient against app with mocked auth matching test_scripts_pieza45.py pattern."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch("app.auth.supabase_auth.supabase_auth.get_user_id", return_value="550e8400-e29b-41d4-a716-446655440000"):
        with patch.object(guard, "get_or_create_user_session", return_value="test_session_p48"):
            yield client


def _create_mock_script_dict() -> dict:
    """Helper returning a valid script dictionary."""
    return {
        "title": "Scaling Operations with AI",
        "angle": "From manual data entry to automated pipelines",
        "target_seconds": 60,
        "recording_format": "selfie_natural",
        "music_prompt": "upbeat corporate tech",
        "frame_zero": {
            "visual": "Founder holding tablet showing automated workflow dashboard",
            "on_screen_text": "Stop manual work",
            "why_it_stops_the_scroll": "High contrast graphic of manual vs automated efficiency metrics",
        },
        "scenes": [
            {
                "phase": "hook",
                "spoken_text": "Are you still wasting hours every single day copying data manually across spreadsheets?",
                "shot": "medium close-up",
                "b_roll": None,
                "on_screen_text": "Wasting hours?",
                "acting_note": "Direct eye contact, sharp energetic opening, pause slightly on hours",
                "sound": "whoosh",
                "asset_type": "a_roll",
            },
            {
                "phase": "lock_in",
                "spoken_text": "Manual workflow management is quietly draining thousands of dollars from your company every single month.",
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Draining revenue",
                "acting_note": "Serious, authoritative cadence, leaning slightly forward",
                "sound": "subtle pulse",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_1",
                "spoken_text": "Our intelligent automation platform connects directly to your databases and tools. It extracts, validates, and synchronizes data in real time without human intervention. Teams report saving fifteen hours each week while completely eliminating human errors across every single department.",
                "shot": "medium",
                "b_roll": "dashboard overlay",
                "on_screen_text": "Save 15 hours weekly",
                "acting_note": "Measured explanatory tone, emphasize real time and zero errors",
                "sound": "ambient synth",
                "asset_type": "stock",
                "stock_query": "modern office tech dashboard",
            },
            {
                "phase": "rehook",
                "spoken_text": "Stay with me, because that is only the beginning of what changes.",
                "shot": "close-up",
                "b_roll": None,
                "on_screen_text": "Stay with me",
                "acting_note": "Lower pitch, intense direct gaze, deliberate pause before changes",
                "sound": "riser sound effect",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_2",
                "spoken_text": "The real power comes from predictive analytics and automated notifications. When a discrepancy occurs, your team gets alerted immediately with root cause context. You move from putting out daily fires to proactively driving high-impact strategic initiatives.",
                "shot": "medium",
                "b_roll": "notification graphic",
                "on_screen_text": "Predictive alerts",
                "acting_note": "Enthusiastic and clear, open palm gestures pointing to metrics",
                "sound": "tech shimmer",
                "asset_type": "stock",
                "stock_query": "clean modern charts and data analytics",
            },
            {
                "phase": "close_cta",
                "spoken_text": "Start streamlining your company operations today. Visit our official website now to claim your free personalized workflow consultation with our experts.",
                "shot": "medium close-up",
                "b_roll": None,
                "on_screen_text": "Claim free audit",
                "acting_note": "Warm, confident smile, nodding encouragingly, pointing to screen text",
                "sound": "resolving chime",
                "asset_type": "a_roll",
            },
        ],
        "sources": ["Internal benchmark study 2026 showing 15 hours saved per week"],
    }


# =============================================================================
# 1. NORMALIZATION TESTS FOR _normalize_b_roll
# =============================================================================

def test_normalize_b_roll_all_types():
    """_normalize_b_roll handles str, None, "", dict con description, dict sin claves conocidas, lista, int."""
    # 1. str -> stripped string
    assert _normalize_b_roll("overlay text") == "overlay text"
    assert _normalize_b_roll("  founder typing on laptop  ") == "founder typing on laptop"

    # 2. None -> None
    assert _normalize_b_roll(None) is None

    # 3. "" / whitespace -> None
    assert _normalize_b_roll("") is None
    assert _normalize_b_roll("   ") is None

    # 4. dict con description
    d1 = {"type": "stock", "description": "close up of typing on mechanical keyboard"}
    assert _normalize_b_roll(d1) == "close up of typing on mechanical keyboard"

    # Other known keys: text, visual, query
    assert _normalize_b_roll({"text": "graph climbing"}) == "graph climbing"
    assert _normalize_b_roll({"visual": "office landscape aerial"}) == "office landscape aerial"
    assert _normalize_b_roll({"query": "warehouse logistics automation"}) == "warehouse logistics automation"

    # Priority order: description before text/visual/query
    assert _normalize_b_roll({"description": "first", "text": "second"}) == "first"

    # 5. dict sin claves conocidas -> values joined with " — "
    d_unknown = {"source": "archive", "camera": "side-angle", "detail": "coffee cup steaming"}
    assert _normalize_b_roll(d_unknown) == "archive — side-angle — coffee cup steaming"
    # dict with non-string values
    assert _normalize_b_roll({"count": 12, "flag": True}) is None
    assert _normalize_b_roll({}) is None

    # 6. list -> elementos de texto unidos con "; "
    assert _normalize_b_roll(["overlay 1", "overlay 2"]) == "overlay 1; overlay 2"
    assert _normalize_b_roll(["  clip A  ", "clip B  "]) == "clip A; clip B"
    assert _normalize_b_roll(["single item"]) == "single item"
    assert _normalize_b_roll([]) is None
    assert _normalize_b_roll(["", "   "]) is None

    # 7. int / cualquier otro tipo -> str(value)
    assert _normalize_b_roll(123) == "123"
    assert _normalize_b_roll(0) == "0"
    assert _normalize_b_roll(99.5) == "99.5"


# =============================================================================
# 2. MOCKED SCRIPT WITH SCENE 3 b_roll AS DICT BUILDS WITHOUT ERROR
# =============================================================================

def test_script_with_scene_3_b_roll_as_dict_builds_without_error():
    """Un guion mockeado cuya escena 3 trae b_roll como dict se construye sin error."""
    script_dict = _create_mock_script_dict()
    # Reproduce the exact bug from production QA:
    # Scene 3 has b_roll as dict: {"type": "stock", "description": "..."}
    script_dict["scenes"][2]["b_roll"] = {
        "type": "stock",
        "description": "Founder pointing at dynamic data visualization on screen"
    }

    raw_json = json.dumps(script_dict)
    script, _ = _parse_and_build_script("test_session_p48", "idea_p48_scene3", raw_json)

    assert script is not None
    assert len(script.scenes) == 6
    scene_3 = script.scenes[2]
    # b_roll must be normalized to str matching the description
    assert isinstance(scene_3.b_roll, str)
    assert scene_3.b_roll == "Founder pointing at dynamic data visualization on screen"


# =============================================================================
# 3. PROMPT SCHEMA CONTAINS NEW b_roll SPECIFICATION
# =============================================================================

def test_generation_prompt_b_roll_schema_updated():
    """Prompt schema changed from 'what overlays (or null)' to plain text string or null."""
    idea = CatalogIdea(
        id="idea_test_p48",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Scaling operations with AI pipelines",
        demand_signal="Demand signal with sufficient length for validation requirements",
        status="approved",
    )
    prompt = _build_generation_prompt(
        brand_context="Brand context here",
        idea=idea,
        interview_transcript="Founder: We automate workflows.",
        source_mode="brand_brain",
        script_kind="tutorial",
    )

    assert '"b_roll": "plain text string describing the overlay, or null — never an object"' in prompt
    assert '"b_roll": "what overlays (or null)"' not in prompt


# =============================================================================
# 4. LLM THAT RETURNS INVALID JSON THEN VALID: 1 RETRY, SCRIPT RETURNED, 1 CHARGE
# =============================================================================

@pytest.mark.asyncio
async def test_generate_script_retries_on_validation_error_and_charges_once(api_client, tmp_path):
    """
    LLM mockeado que primero devuelve JSON inválido y luego uno válido:
    1 reintento, guion devuelto, 1 cobro.
    """
    import os
    os.chdir(tmp_path)

    valid_dict = _create_mock_script_dict()
    valid_json = json.dumps(valid_dict)

    # First attempt: invalid JSON response
    mock_resp_1 = Mock()
    mock_resp_1.text = "NOT A JSON OBJECT {bad syntax..."

    # Second attempt: valid script JSON
    mock_resp_2 = Mock()
    mock_resp_2.text = valid_json

    idea = CatalogIdea(
        id="idea_retry_valid",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Five ways to automate B2B work",
        demand_signal="Demand signal with sufficient length for validation",
        status="approved",
    )
    catalog = Catalog(
        session_id="test_session_p48",
        niche="B2B automation",
        ideas=[idea],
        catalog_locked=True,
    )
    brain = BrandBrain(
        sections=[
            Section(
                id="diagnostico",
                label="diagnostico",
                status="confirmado",
                content={"value": "B2B operations"},
                citation_text="citations",
                citation_source="usuario",
            )
        ]
    )

    mock_model = AsyncMock()
    mock_model.generate_content_async.side_effect = [mock_resp_1, mock_resp_2]

    with patch.object(guard, "get_session", return_value={"credits": 50}), \
         patch.object(guard, "get_remaining_credits", return_value=50), \
         patch.object(guard, "deduct_credits", return_value=40) as mock_deduct, \
         patch("app.tools.brand_brain.store.get_brand_brain", return_value=brain), \
         patch("app.catalog.ideas._check_catalog_cache", return_value=catalog), \
         patch("app.scripting.scripts.get_brand_brain", return_value=brain), \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel", return_value=mock_model):

        response = api_client.post(
            "/api/script/generate?idea_id=idea_retry_valid",
            json={
                "interview_transcript": "Interview transcript about operations",
                "source_mode": "brand_brain",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["cache_status"] == "generated"

    # Exactly 2 calls to Gemini (1 initial + 1 retry)
    assert mock_model.generate_content_async.call_count == 2

    # Check retry prompt passed to the model in call 2
    retry_call_args = mock_model.generate_content_async.call_args_list[1]
    retry_prompt = retry_call_args[0][0]
    assert "your previous output was invalid:" in retry_prompt
    assert "Return valid JSON matching the schema; b_roll must be a string or null" in retry_prompt

    # Exactly 1 deduction of 10 credits
    assert mock_deduct.call_count == 1
    mock_deduct.assert_called_once_with("test_session_p48", amount=CREDITS_COST_GENERATE)

    # Returned script matches valid data
    script_data = data["script"]
    assert len(script_data["scenes"]) == 6
    assert script_data["title"] == "Scaling Operations with AI"


# =============================================================================
# 5. LLM THAT RETURNS INVALID TWICE: ERROR PROPAGATED, 0 CHARGES, NO 3RD ATTEMPT
# =============================================================================

@pytest.mark.asyncio
async def test_generate_script_fails_when_both_attempts_invalid(api_client, tmp_path):
    """
    LLM que devuelve inválido dos veces: error propagado, 0 cobros, sin tercer intento.
    """
    import os
    os.chdir(tmp_path)

    mock_resp_1 = Mock()
    mock_resp_1.text = "INVALID JSON 1"

    mock_resp_2 = Mock()
    mock_resp_2.text = "INVALID JSON 2"

    idea = CatalogIdea(
        id="idea_retry_invalid_twice",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Five ways to automate B2B work",
        demand_signal="Demand signal with sufficient length for validation",
        status="approved",
    )
    catalog = Catalog(
        session_id="test_session_p48",
        niche="B2B automation",
        ideas=[idea],
        catalog_locked=True,
    )
    brain = BrandBrain(
        sections=[
            Section(
                id="diagnostico",
                label="diagnostico",
                status="confirmado",
                content={"value": "B2B operations"},
                citation_text="citations",
                citation_source="usuario",
            )
        ]
    )

    mock_model = AsyncMock()
    mock_model.generate_content_async.side_effect = [mock_resp_1, mock_resp_2]

    with patch.object(guard, "get_session", return_value={"credits": 50}), \
         patch.object(guard, "get_remaining_credits", return_value=50), \
         patch.object(guard, "deduct_credits", return_value=40) as mock_deduct, \
         patch("app.tools.brand_brain.store.get_brand_brain", return_value=brain), \
         patch("app.catalog.ideas._check_catalog_cache", return_value=catalog), \
         patch("app.scripting.scripts.get_brand_brain", return_value=brain), \
         patch("app.scripting.scripts._get_script_client", return_value=None), \
         patch("vertexai.generative_models.GenerativeModel", return_value=mock_model):

        response = api_client.post(
            "/api/script/generate?idea_id=idea_retry_invalid_twice",
            json={
                "interview_transcript": "Interview transcript about operations",
                "source_mode": "brand_brain",
            },
        )

    # 400 with propagated validation error
    assert response.status_code == 400
    assert "Failed to parse JSON response from Gemini" in response.json()["error"]

    # Exactly 2 calls (1 initial + 1 retry) - NO 3rd attempt
    assert mock_model.generate_content_async.call_count == 2

    # Zero credits deducted
    assert mock_deduct.call_count == 0
