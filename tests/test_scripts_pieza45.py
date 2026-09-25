"""
Tests for PIEZA 45 — Que un guion recién generado se pueda bloquear + botón "Open script".

Tests:
1. El prompt ya no contiene "3-7 seconds" y sí contiene el presupuesto de palabras (130-200 palabras,
   distribuido por fase, consistencia de idioma, y prohibición de 'not X, it's Y' ampliada).
2. Con un LLM mockeado que devuelve primero un guion de ~100 palabras y luego uno de ~160:
   se hace exactamente 1 reintento, se devuelve el de 160, y se cobra 1 sola vez.
3. Con un LLM que devuelve dos guiones cortos: no hay tercer intento; se devuelve el mejor
   y el cobro es 1 sola vez.
4. GET /api/catalog incluye script_state correcto para una idea con guion y null para una sin guion.
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
    FrameZero,
    Scene,
    Script,
    _build_generation_prompt,
    _save_script,
    get_script_states_by_session,
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
    """TestClient against app with mocked auth matching test_scripting.py pattern."""
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer fake-token-for-test"})
    with patch("app.auth.supabase_auth.supabase_auth.get_user_id", return_value="550e8400-e29b-41d4-a716-446655440000"):
        with patch.object(guard, "get_or_create_user_session", return_value="test_session_p45"):
            yield client


def _create_mock_script_json(words_per_phase: dict[str, str]) -> str:
    """Helper to generate valid script JSON with specified spoken_text per phase."""
    return json.dumps({
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
                "spoken_text": words_per_phase.get(
                    "hook",
                    "Are you still wasting hours every single day copying data manually across spreadsheets?",
                ),
                "shot": "medium close-up",
                "b_roll": None,
                "on_screen_text": "Wasting hours?",
                "acting_note": "Direct eye contact, sharp energetic opening, pause slightly on hours",
                "sound": "whoosh",
                "asset_type": "a_roll",
            },
            {
                "phase": "lock_in",
                "spoken_text": words_per_phase.get(
                    "lock_in",
                    "Manual workflow management is quietly draining thousands of dollars from your company every single month.",
                ),
                "shot": "medium",
                "b_roll": None,
                "on_screen_text": "Draining revenue",
                "acting_note": "Serious, authoritative cadence, leaning slightly forward",
                "sound": "subtle pulse",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_1",
                "spoken_text": words_per_phase.get(
                    "body_1",
                    "Our intelligent automation platform connects directly to your databases and tools. It extracts, validates, and synchronizes data in real time without human intervention. Teams report saving fifteen hours each week while completely eliminating human errors across every single department.",
                ),
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
                "spoken_text": words_per_phase.get(
                    "rehook",
                    "Stay with me, because that is only the beginning of what changes.",
                ),
                "shot": "close-up",
                "b_roll": None,
                "on_screen_text": "Stay with me",
                "acting_note": "Lower pitch, intense direct gaze, deliberate pause before changes",
                "sound": "riser sound effect",
                "asset_type": "a_roll",
            },
            {
                "phase": "body_2",
                "spoken_text": words_per_phase.get(
                    "body_2",
                    "The real power comes from predictive analytics and automated notifications. When a discrepancy occurs, your team gets alerted immediately with root cause context. You move from putting out daily fires to proactively driving high-impact strategic initiatives.",
                ),
                "shot": "medium",
                "b_roll": "notification graphic",
                "on_screen_text": "Predictive alerts",
                "acting_note": "Enthusiastic and clear, open palm gestures pointing to metrics",
                "sound": "tech shimmer",
                "asset_type": "ai_image",
                "visual_prompt": "Clean futuristic dashboard with automated alerts and glowing charts",
            },
            {
                "phase": "close_cta",
                "spoken_text": words_per_phase.get(
                    "close_cta",
                    "Start streamlining your company operations today. Visit our official website now to claim your free personalized workflow consultation with our experts.",
                ),
                "shot": "medium close-up",
                "b_roll": None,
                "on_screen_text": "Claim free audit",
                "acting_note": "Warm, confident smile, nodding encouragingly, pointing to screen text",
                "sound": "resolving chime",
                "asset_type": "a_roll",
            },
        ],
        "sources": ["Internal benchmark study 2026 showing 15 hours saved per week"],
    })


SHORT_SCRIPT_TEXTS = {
    "hook": "This is a short hook.",  # 5 words
    "lock_in": "Most teams spend way too much time on manual tasks daily.",  # 11 words
    "body_1": "First point focuses on automated data extraction and processing pipelines.",  # 11 words
    "rehook": "Stay with me because this gets better.",  # 7 words
    "body_2": "Second point shows how workflow automation eliminates bottlenecks.",  # 9 words
    "close_cta": "Visit our site to learn how automation can scale operations.",  # 10 words
    # Total = 5 + 11 + 11 + 7 + 9 + 10 = 53 words -> 53 / 2.5 = 21.2s (< 45s, fails rule_1)
}

LONG_SCRIPT_TEXTS = {
    # hook: 13 words
    "hook": "Are you still wasting hours every single day copying data manually across spreadsheets?",
    # lock_in: 16 words
    "lock_in": "Manual workflow management is quietly draining thousands of dollars from your company every single month.",
    # body_1: 40 words
    "body_1": "Our intelligent automation platform connects directly to your databases and tools. It extracts, validates, and synchronizes data in real time without human intervention. Teams report saving fifteen hours each week while completely eliminating human errors across every single department.",
    # rehook: 12 words
    "rehook": "Stay with me, because that is only the beginning of what changes.",
    # body_2: 37 words
    "body_2": "The real power comes from predictive analytics and automated notifications. When a discrepancy occurs, your team gets alerted immediately with root cause context. You move from putting out daily fires to proactively driving high-impact strategic initiatives.",
    # close_cta: 22 words
    "close_cta": "Start streamlining your company operations today. Visit our official website now to claim your free personalized workflow consultation with our experts.",
    # Total = 13 + 16 + 40 + 12 + 37 + 22 = 140 words -> 140 / 2.5 = 56.0s (passes rule_1!)
}


# =============================================================================
# TEST 1: PROMPT VERIFICATION
# =============================================================================

def test_generation_prompt_removes_3_to_7_seconds_and_includes_word_budget():
    """Verify prompt removes '3-7 seconds' and includes explicit word budget + language consistency."""
    idea = CatalogIdea(
        id="idea_test_p45",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Automating manual data pipelines in B2B",
        demand_signal="Demand signal with sufficient character count for validation requirements",
        status="approved",
    )
    prompt = _build_generation_prompt(
        brand_context="Brand context here",
        idea=idea,
        interview_transcript="Founder: We automate tedious workflows.",
        source_mode="brand_brain",
        script_kind="tutorial",
    )

    # 1. Must NOT contain "3-7 seconds"
    assert "3-7 seconds" not in prompt
    assert "Each scene: 3-7 seconds" not in prompt

    # 2. Must contain explicit word budget between 130 and 200 words
    assert "130 and 200 words" in prompt
    assert "hook: 10-15 words" in prompt
    assert "lock_in: 15-20 words" in prompt
    assert "body_1: 35-50 words" in prompt
    assert "rehook: 12-18 words" in prompt
    assert "body_2: 35-50 words" in prompt
    assert "close_cta: 20-30 words" in prompt

    # 3. Must contain forbidden contrast examples
    assert "It's not about the number of hands. It's about the speed..." in prompt
    assert "This isn't X. This is Y." in prompt
    assert "Not X — Y." in prompt

    # 4. Must contain language consistency instruction
    assert "LANGUAGE CONSISTENCY" in prompt
    assert "NEVER mix languages within a script" in prompt


# =============================================================================
# TEST 2: SINGLE RETRY ON CRITICAL FAILURE AND EXACTLY 1 CHARGE
# =============================================================================

@pytest.mark.asyncio
async def test_generate_script_retries_on_critical_failure_and_charges_once(api_client, tmp_path):
    """
    When model returns a short script (~53 words, failing rule_1) and then a valid
    script (~140 words, passing rule_1):
    - Exactly 1 retry is made (2 LLM calls total)
    - The 140-word script is kept and returned
    - The founder is charged exactly 1 time (10 credits)
    """
    import os
    os.chdir(tmp_path)

    short_json = _create_mock_script_json(SHORT_SCRIPT_TEXTS)
    long_json = _create_mock_script_json(LONG_SCRIPT_TEXTS)

    mock_resp_1 = Mock()
    mock_resp_1.text = short_json
    mock_resp_2 = Mock()
    mock_resp_2.text = long_json

    idea = CatalogIdea(
        id="idea_retry_1",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Five ways to automate B2B work",
        demand_signal="Demand signal with sufficient length for validation",
        status="approved",
    )
    catalog = Catalog(
        session_id="test_session_p45",
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
            "/api/script/generate?idea_id=idea_retry_1",
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

    # Exactly 1 deduction of 10 credits
    assert mock_deduct.call_count == 1
    mock_deduct.assert_called_once_with("test_session_p45", amount=CREDITS_COST_GENERATE)

    # Returned script is the long one (actual_seconds >= 45s)
    script_data = data["script"]
    total_words = sum(len(sc["spoken_text"].split()) for sc in script_data["scenes"])
    assert total_words >= 130
    assert script_data["scenes"][0]["phase"] == "hook"
    rule_1_finding = next(f for f in script_data["audit"] if f["rule"] == "rule_1")
    assert rule_1_finding["status"] == "pass"


# =============================================================================
# TEST 3: NO THIRD ATTEMPT WHEN BOTH ATTEMPTS ARE SHORT
# =============================================================================

@pytest.mark.asyncio
async def test_generate_script_does_not_loop_when_both_attempts_fail(api_client, tmp_path):
    """
    When model returns short scripts on both attempts:
    - Exactly 1 retry is made (2 LLM calls total, no third attempt)
    - The best script is returned
    - The founder is charged exactly 1 time (10 credits)
    """
    import os
    os.chdir(tmp_path)

    short_json_1 = _create_mock_script_json(SHORT_SCRIPT_TEXTS)
    short_json_2 = _create_mock_script_json(SHORT_SCRIPT_TEXTS)

    mock_resp_1 = Mock()
    mock_resp_1.text = short_json_1
    mock_resp_2 = Mock()
    mock_resp_2.text = short_json_2

    idea = CatalogIdea(
        id="idea_retry_2",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Five ways to automate B2B work",
        demand_signal="Demand signal with sufficient length for validation",
        status="approved",
    )
    catalog = Catalog(
        session_id="test_session_p45",
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
            "/api/script/generate?idea_id=idea_retry_2",
            json={
                "interview_transcript": "Interview transcript about operations",
                "source_mode": "brand_brain",
            },
        )

    assert response.status_code == 200, response.text

    # MUST be exactly 2 calls, NEVER a third attempt or infinite loop
    assert mock_model.generate_content_async.call_count == 2

    # Exactly 1 charge of 10 credits
    assert mock_deduct.call_count == 1
    mock_deduct.assert_called_once_with("test_session_p45", amount=CREDITS_COST_GENERATE)


# =============================================================================
# TEST 4: GET /api/catalog INCLUDES script_state
# =============================================================================

def test_get_catalog_includes_script_state_for_scripted_and_unscripted_ideas(api_client, tmp_path):
    """
    GET /api/catalog includes:
    - script_state="locked" (or draft/reviewed) for an idea with an existing script
    - script_state=null (None) for an idea without a script
    - Done with a single query/read from script store
    """
    import os
    os.chdir(tmp_path)

    idea_with_script = CatalogIdea(
        id="idea_with_script",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Idea with a script attached",
        demand_signal="Demand signal with sufficient character count for validation",
        status="approved",
    )
    idea_without_script = CatalogIdea(
        id="idea_without_script",
        master_category="autoridad_tecnica",
        subcategory="Top N/Listículo técnico",
        title="Idea without any script",
        demand_signal="Demand signal with sufficient character count for validation",
        status="approved",
    )

    catalog = Catalog(
        session_id="test_session_p45",
        niche="B2B Tech",
        ideas=[idea_with_script, idea_without_script],
        catalog_locked=True,
    )
    brain = BrandBrain(
        sections=[
            Section(
                id="diagnostico",
                label="diagnostico",
                status="confirmado",
                content={"value": "Brand content"},
                citation_text="citations",
                citation_source="usuario",
            )
        ]
    )

    # Save a script for idea_with_script in local file cache
    script = Script(
        session_id="test_session_p45",
        idea_id="idea_with_script",
        title="Test Script",
        angle="Test Angle",
        funnel_stage="tofu",
        target_seconds=60,
        frame_zero=FrameZero(
            visual="Visual text",
            on_screen_text="Screen text",
            why_it_stops_the_scroll="Hook explanation",
        ),
        scenes=[
            Scene(
                n=idx + 1,
                start_s=float(idx * 10),
                end_s=float((idx + 1) * 10),
                phase=ph,
                spoken_text=f"Spoken text for scene number {idx + 1} here.",
                shot="medium",
                b_roll=None,
                on_screen_text="Text",
                acting_note="Note",
                sound="sound",
            )
            for idx, ph in enumerate(["hook", "lock_in", "body_1", "rehook", "body_2", "close_cta"])
        ],
        state="locked",
    )

    with patch("app.scripting.scripts._get_script_client", return_value=None):
        _save_script(script)

        # Verify get_script_states_by_session returns mapping directly
        states = get_script_states_by_session("test_session_p45")
        assert states.get("idea_with_script") == "locked"
        assert states.get("idea_without_script") is None

        with patch("app.tools.brand_brain.store.get_brand_brain", return_value=brain), \
             patch("app.catalog.ideas._check_catalog_cache", return_value=catalog):

            response = api_client.get("/api/catalog")

    assert response.status_code == 200, response.text
    data = response.json()
    assert "catalog" in data
    ideas = data["catalog"]["ideas"]
    assert len(ideas) == 2

    idea_1 = next(i for i in ideas if i["id"] == "idea_with_script")
    idea_2 = next(i for i in ideas if i["id"] == "idea_without_script")

    assert idea_1["script_state"] == "locked"
    assert idea_2["script_state"] is None


def test_app_js_open_script_button_logic():
    """Verify app.js contains Open script states, updateIdeaCardScriptButton, and currentCatalog sync."""
    from pathlib import Path
    app_js_path = Path(__file__).parent.parent / "app" / "static" / "app.js"
    content = app_js_path.read_text(encoding="utf-8")

    # 1. State labels in buildIdeaCardHTML
    assert "📂 Open script · locked 🔒" in content
    assert "📂 Open script · reviewed" in content
    assert "📂 Open script · draft" in content
    assert "📝 Write script" in content

    # 2. updateIdeaCardScriptButton helper function defined
    assert "function updateIdeaCardScriptButton(ideaId, scriptState)" in content

    # 3. Synchronizing currentCatalog when script state changes
    assert "updateIdeaCardScriptButton(currentScriptIdeaId, matchedIdea.script_state)" in content
    assert "updateIdeaCardScriptButton(currentScriptData.idea_id, 'reviewed')" in content
    assert "updateIdeaCardScriptButton(currentScriptData.idea_id, 'locked')" in content

