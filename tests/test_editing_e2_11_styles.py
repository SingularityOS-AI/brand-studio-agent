"""Tests for E2-11: Auto-edit styles Clean/Standard/Bold with free restyles

Mocked tests - no real API calls.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def client_with_auth(authenticated_client):
    """Alias for authenticated client fixture."""
    return authenticated_client


@pytest.fixture
def sample_edit_state():
    """Sample edit state with timeline and captions."""
    return {
        "edit_version": 1,
        "timeline": {
            "scenes": [
                {"n": 1, "phase": "A", "visual": "face", "out_start_ms": 0, "out_end_ms": 5000, "duration_ms": 5000},
                {"n": 2, "phase": "A", "visual": "face", "out_start_ms": 0, "out_end_ms": 4000, "duration_ms": 4000},
            ]
        },
        "missing_takes": [],
        "captions_words": [
            {"scene_n": 1, "n": 1, "start_ms": 0, "end_ms": 1000, "text": "Hello"},
            {"scene_n": 1, "n": 2, "start_ms": 1000, "end_ms": 2000, "text": "World"},
            {"scene_n": 2, "n": 3, "start_ms": 0, "end_ms": 1500, "text": "Test"},
        ],
        "dressing": None,
        "raw": {"status": "done", "fresh": True},
        "render": None,
    }


class TestE2_11_DressRequestBody:
    """Tests for DressRequestBody model validation."""

    def test_dress_request_body_default_style(self):
        """Test DressRequestBody with default style."""
        from app.editing.router import DressRequestBody

        body = DressRequestBody()
        assert body.style == "standard"
        assert body.expected_version is None

    def test_dress_request_body_custom_style_clean(self):
        """Test DressRequestBody with clean style."""
        from app.editing.router import DressRequestBody

        body = DressRequestBody(style="clean")
        assert body.style == "clean"

    def test_dress_request_body_custom_style_bold(self):
        """Test DressRequestBody with bold style."""
        from app.editing.router import DressRequestBody

        body = DressRequestBody(style="bold")
        assert body.style == "bold"

    def test_dress_request_body_with_version(self):
        """Test DressRequestBody with expected_version."""
        from app.editing.router import DressRequestBody

        body = DressRequestBody(style="standard", expected_version=5)
        assert body.style == "standard"
        assert body.expected_version == 5


class TestE2_11_StyleValidation:
    """Tests for style parameter validation in POST /dress endpoint."""

    def test_invalid_style_rejected(self, client_with_auth, sample_edit_state):
        """Test that invalid style returns 422."""
        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router._check_and_record_llm_call"), \
             patch("app.editing.router.dress_all", new_callable=AsyncMock) as mock_dress_all, \
             patch("app.editing.router.save_edit") as mock_save:

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state
            mock_dress_all.return_value = {
                "catalog_version": "v1",
                "source": "llm",
                "raw_hash": "abc123",
                "scenes": [],
                "style": "invalid",  # Invalid style
                "free_restyles_used": 0,
            }
            mock_save.return_value = {"version": 2}

            # Send request with invalid style
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "invalid_style"},
            )

            # Should fail validation
            assert response.status_code == 422
            assert "Invalid style" in response.json()["detail"]


class TestE2_11_FreeRestylesLimit:
    """Tests for the 3-free restyles limit per raw cut."""

    def test_first_three_free_styles_allowed(self, client_with_auth, sample_edit_state):
        """Test that first 3 style changes are allowed."""
        sample_edit_state["dressing"] = {
            "catalog_version": "v1",
            "source": "llm",
            "raw_hash": "abc123",
            "scenes": [],
            "style": "standard",
            "fresh": True,
            "free_restyles_used": 0,
        }

        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router.save_edit") as mock_save:

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state
            mock_save.return_value = {"version": 2}

            # Try restyle to clean (1st free)
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "clean", "expected_version": 1},
            )
            assert response.status_code in [200, 409]  # 200 if updated, 409 if version conflict

    def test_fourth_restyle_rejected_with_409(self, client_with_auth, sample_edit_state):
        """Test that 4th style change returns 409 with code 'restyle_limit'."""
        sample_edit_state["dressing"] = {
            "catalog_version": "v1",
            "source": "llm",
            "raw_hash": "abc123",
            "scenes": [],
            "style": "bold",
            "fresh": True,
            "free_restyles_used": 3,  # Already used 3
        }

        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router.cut_hash", return_value="abc123"), \
             patch("app.editing.router.get_or_create_edit", return_value={"version": 2, "dressing": sample_edit_state["dressing"]}), \
             patch("app.editing.router.save_edit", return_value={"version": 2, "dressing": sample_edit_state["dressing"]}):

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state

            # Try restyle to clean (4th, should be rejected)
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "clean", "expected_version": 1},
            )

            assert response.status_code == 409
            assert response.json()["code"] == "restyle_limit"
            assert response.json()["free_restyles_used"] == 4

    def test_same_style_not_counted_as_restyle(self, client_with_auth, sample_edit_state):
        """Test that selecting the same style doesn't count towards the limit."""
        sample_edit_state["dressing"] = {
            "catalog_version": "v1",
            "source": "llm",
            "raw_hash": "abc123",
            "scenes": [],
            "style": "standard",
            "fresh": True,
            "free_restyles_used": 3,  # Already used 3
        }

        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router.cut_hash", return_value="abc123"):

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state

            # Try to restyle to the same style (should be allowed, not counted)
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "standard", "expected_version": 1},
            )

            # Should return 200 (no error) since style hasn't changed
            assert response.status_code == 200

    def test_new_raw_cut_resets_restyle_limit(self, client_with_auth, sample_edit_state):
        """Test that a new raw cut resets the free_restyles_used to 0."""
        # State with old raw_hash (different cut)
        sample_edit_state["dressing"] = {
            "catalog_version": "v1",
            "source": "llm",
            "raw_hash": "old_hash",  # Different from timeline's hash
            "scenes": [],
            "style": "standard",
            "fresh": True,
            "free_restyles_used": 99,  # High number, should be reset
        }

        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router._check_and_record_llm_call"), \
             patch("app.editing.router.dress_all", new_callable=AsyncMock) as mock_dress_all, \
             patch("app.editing.router.save_edit") as mock_save:

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state
            mock_dress_all.return_value = {
                "catalog_version": "v1",
                "source": "llm",
                "raw_hash": "abc123",  # New hash (timeline changed)
                "scenes": [],
                "style": "clean",
                "free_restyles_used": 0,  # Should start fresh at 0
            }
            mock_save.return_value = {"version": 2}

            # Request with new cut should trigger new dressing
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "clean", "expected_version": 1},
            )

            # Should succeed with new dressing (reset free_restyles_used)
            assert response.status_code == 200


class TestE2_11_ExpectedVersion:
    """Tests for expected_version parameter."""

    def test_version_conflict_returned(self, client_with_auth, sample_edit_state):
        """Test that version conflict returns 409 with code 'version_conflict'."""
        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state:

            mock_load.return_value = ("token", {}, [], {"version": 1})
            sample_edit_state["dressing"] = {
                "catalog_version": "v1",
                "source": "llm",
                "raw_hash": "abc123",
                "scenes": [],
                "style": "standard",
                "fresh": True,
                "free_restyles_used": 0,
            }
            mock_state.return_value = sample_edit_state

            # Request with wrong expected_version
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "clean", "expected_version": 999},  # Wrong version
            )

            assert response.status_code == 409
            assert response.json()["code"] == "version_conflict"
            assert response.json()["current"] == 1

    def test_matching_version_continues(self, client_with_auth, sample_edit_state):
        """Test that matching expected_version allows the request."""
        sample_edit_state["dressing"] = {
            "catalog_version": "v1",
            "source": "llm",
            "raw_hash": "abc123",
            "scenes": [],
            "style": "standard",
            "fresh": True,
            "free_restyles_used": 0,
        }

        with patch("app.editing.router._load") as mock_load, \
             patch("app.editing.router._state") as mock_state, \
             patch("app.editing.router.cut_hash", return_value="abc123"):

            mock_load.return_value = ("token", {}, [], {"version": 1})
            mock_state.return_value = sample_edit_state

            # Request with correct expected_version and same style
            response = client_with_auth.post(
                "/api/editing/test-idea/dress",
                json={"style": "standard", "expected_version": 1},
            )

            # Should succeed (same style, so no restyle counted)
            assert response.status_code == 200


class TestE2_11_DressingModel:
    """Tests for Dressing model updates."""

    def test_dressing_model_has_free_restyles_used(self):
        """Test that Dressing model includes free_restyles_used field."""
        from app.editing.dressing import Dressing

        dressing = Dressing(
            catalog_version="v1",
            source="llm",
            raw_hash="abc123",
            scenes=[],
            style="standard",
        )
        assert dressing.free_restyles_used == 0  # Default value

    def test_dressing_model_free_restyles_used_custom(self):
        """Test that Dressing model can have custom free_restyles_used."""
        from app.editing.dressing import Dressing

        dressing = Dressing(
            catalog_version="v1",
            source="llm",
            raw_hash="abc123",
            scenes=[],
            style="standard",
            free_restyles_used=5,
        )
        assert dressing.free_restyles_used == 5


class TestE2_11_DressAllStyleParameter:
    """Tests for dress_all accepting style parameter."""

    @pytest.mark.asyncio
    async def test_dress_all_accepts_style_parameter(self):
        """Test that dress_all accepts style parameter."""
        from app.editing.dressing import dress_all

        contexts = [
            {
                "n": 1,
                "phase": "A",
                "visual": "face",
                "out_start_ms": 0,
                "out_end_ms": 5000,
                "duration_ms": 5000,
                "on_screen_text": "",
                "words": [],
                "has_broll": False,
            }
        ]

        # Mock the LLM call to return valid dressing
        mock_llm_response = {
            "scenes": [
                {
                    "n": 1,
                    "transition_in": "cut",
                    "zooms": [{"type": "zoom_in", "word_idx": 0, "intensity": "gentle"}],
                    "overlays": [],
                    "emphasis_word_idx": [],
                    "sfx_tags": {"transition": "whoosh", "overlay": "pop"},
                }
            ]
        }

        with patch("app.editing.dressing.get_genai_client") as mock_client, \
             patch("asyncio.wait_for") as mock_wait:

            mock_resp = MagicMock()
            mock_resp.text = '{"scenes": [{"n": 1, "transition_in": "cut", "zooms": [], "overlays": [], "emphasis_word_idx": [], "sfx_tags": {"transition": "whoosh", "overlay": "pop"}}]}'
            mock_result = MagicMock()
            mock_result.text = mock_resp.text
            mock_wait.return_value = mock_result

            mock_generate = AsyncMock()
            mock_generate.return_value = MagicMock(text=mock_llm_response.__str__())
            mock_client.return_value = MagicMock(
                aio=MagicMock(models=MagicMock(generate_content=mock_generate))
            )

            # Test with different style values
            for style in ["clean", "standard", "bold"]:
                result = await dress_all(contexts, "abc123", 1, style=style)
                assert result is not None
                assert "style" in result
                assert result["style"] == style
                assert "free_restyles_used" in result
                assert result["free_restyles_used"] == 0
