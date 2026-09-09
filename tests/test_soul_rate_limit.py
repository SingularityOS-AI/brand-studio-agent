"""
Rate Limit Tests for Brand Soul Generate Endpoint (Pieza 6)

Tests for rate limiting on the expensive /api/soul/generate endpoint.
This endpoint calls Vertex AI (real money per token), so it needs a stricter
rate limit (5 requests/min per IP) than the general rate limit (30 requests/min).

Test coverage:
1. 5 requests in under a minute from same IP → all succeed
2. 6th request in the same minute from same IP → returns 429
3. Rate limit is per-IP (different IPs have independent limits)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.guard import guard


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def complete_brain_for_tests():
    """A complete brand brain with all 9 confirmed sections for tests."""
    from app.tools.brand_brain.models import BrandBrain, Section

    brain = BrandBrain()

    sections_data = [
        {"id": "brand_journey", "label": "Viaje del Cliente", "content": {
            "stage_1_unaware": "No sabe que tiene un problema",
            "stage_2_problem_aware": "Siente el dolor",
            "stage_3_solution_aware": "Busca soluciones",
            "stage_4_product_aware": "Conoce tu marca",
            "stage_5_most_aware": "Listo para comprar"
        }, "citation_text": "Elvia explicó que el cliente viaja del 'no saber' al 'sí quiero'", "citation_source": "usuario", "status": "confirmado"},
        {"id": "etapa", "label": "Etapa del Negocio", "content": {"stage": "Momentum"}, "citation_text": "Elvia dice que estás en Momentum, ya tienes tracción", "citation_source": "usuario", "status": "confirmado"},
        {"id": "charco", "label": "El Charco", "content": {"pain_point": "Las personas perdidas en su propósito"}, "citation_text": "Elvia identificó que tu servicio es para personas perdidas en su propósito", "citation_source": "usuario", "status": "confirmado"},
        {"id": "credibilidad", "label": "Credibilidad", "content": {"evidence": "10 años de experiencia"}, "citation_text": "Elvia validó que tienes 10 años de experiencia que respaldan tu propuesta", "citation_source": "usuario", "status": "confirmado"},
        {"id": "contrarian", "label": "Postura Contraria", "content": {
            "common_belief": "Necesitas más redes sociales",
            "contrarian_position": "Necesitas menos redes, más profundidad"
        }, "citation_text": "Elvia desafió la creencia de que necesitas más redes sociales", "citation_source": "usuario", "status": "confirmado"},
        {"id": "asociaciones", "label": "Asociaciones", "content": {"associations": {"desired": ["auténtico", "profundo"], "prohibited": ["superficial", "spam"]}}, "citation_text": "Elvia clarificó cómo quieres ser percibido", "citation_source": "usuario", "status": "confirmado"},
        {"id": "identidad", "label": "Identidad", "content": {"values": ["autenticidad", "profundidad"], "associations": {"desired": ["auténtico", "profundo"], "prohibited": ["superficial", "spam"]}}, "citation_text": "Elvia dijo que tu marca es auténtica y profunda, nunca superficial", "citation_source": "usuario", "status": "confirmado"},
        {"id": "oferta", "label": "Oferta", "content": {"offer_components": ["Consultoría", "Mentoria"], "guarantee": "Satisfacción garantizada"}, "citation_text": "Elvia definió tu oferta como consultoría + mentoría con garantía", "citation_source": "usuario", "status": "confirmado"},
        {"id": "lead_magnet", "label": "Lead Magnet", "content": {"what_they_get": "Ebook gratuito sobre propósito"}, "citation_text": "Elvia propuso un ebook gratuito como regalo inicial", "citation_source": "usuario", "status": "confirmado"},
    ]

    for section_data in sections_data:
        section = Section(**section_data)
        brain.sections.append(section)

    return brain


@pytest.fixture
def client_with_brain(authenticated_client, complete_brain_for_tests):
    """
    Create a test client with a complete brand brain already stored.
    This allows testing the soul generate endpoint without going through
    the brain extraction process.

    Also ensures the session has fresh credits to avoid test interference.
    """
    from app.tools.brand_brain.store import save_brand_brain
    from tests.conftest import get_session_token_for_user

    # Get or create a fresh session token with sufficient credits
    test_user_id = "550e8400-e29b-41d4-a716-446655440000"
    session_token = get_session_token_for_user(test_user_id)

    # Refresh session credits to ensure we don't run out during rate limit testing
    from app.guard import guard
    if session_token and session_token in guard._sessions:
        # Give plenty of credits for rate limit testing (20 per request, 6 requests = 130 needed)
        guard._sessions[session_token]["credits"] = 250
    else:
        # Create new session if none exists
        session_token = guard.create_user_session(test_user_id, initial_credits=250)

    # Update the client's session token
    authenticated_client._test_session_token = session_token

    # Save the brain to the store
    save_brand_brain(session_token, complete_brain_for_tests)

    return authenticated_client


# =============================================================================
# TEST: 5 Requests Succeed, 6th Returns 429
# =============================================================================

@patch("app.tools.brand_soul.generator.generate_brand_soul")
def test_soul_generate_rate_limit_6th_request_returns_429(
    mock_generate_brand_soul,
    client_with_brain
):
    """
    Given the /api/soul/generate endpoint has a 5 requests/minute rate limit,
    When 5 requests are made from the same IP in under a minute,
    Then all 5 should succeed (return 200),
    And the 6th request should return 429 (Too Many Requests).
    """
    # Clear any existing rate limit state for the test client's IP
    from app.guard import guard
    test_ip = "testclient"  # Default TestClient IP
    if test_ip in guard._rate_limits:
        del guard._rate_limits[test_ip]
    if test_ip in guard._blocked_ips:
        del guard._blocked_ips[test_ip]

    # Mock the generate function to avoid actually calling Vertex AI in tests
    mock_html = "<html><body>Mocked Brand Soul Document</body></html>"
    mock_generate_brand_soul.return_value = (mock_html, "generated")

    # Make 5 requests - all should succeed
    for i in range(1, 6):
        response = client_with_brain.post(
            "/api/soul/generate",
            json={"regenerate": True}
        )

        # Each request should succeed
        assert response.status_code == 200, f"Request {i} failed with status {response.status_code}: {response.text}"
        assert "html" in response.json()
        assert response.json()["cache_status"] == "generated"

    # The 6th request should be rate limited
    response = client_with_brain.post(
        "/api/soul/generate",
        json={"regenerate": True}
    )

    # Should return 429 Too Many Requests
    assert response.status_code == 429, f"Expected 429, got {response.status_code}: {response.text}"
    response_json = response.json()
    # FastAPI wraps errors in "detail"
    error_detail = response_json.get("detail") if "detail" in response_json else response_json
    assert "error" in error_detail
    assert "Rate limit exceeded" in error_detail["error"] or "rate limit" in error_detail["error"].lower()

    # Verify generate_brand_soul was called exactly 5 times (not 6)
    assert mock_generate_brand_soul.call_count == 5, f"generate_brand_soul was called {mock_generate_brand_soul.call_count} times, expected 5"


# =============================================================================
# TEST: Rate Limit is Per-IP
# =============================================================================

def test_soul_generate_rate_limit_per_ip():
    """
    Given the rate limit is per IP,
    When track requests from multiple IPs,
    Then each IP should have its own independent rate limit counters.

    NOTE: FastAPI TestClient always reports "testclient" as the IP regardless of base_url.
    This test directly verifies the guard's per-IP storage by manipulating the internal state.
    """
    from app.guard import guard
    from app.config import settings
    import time

    # Clear existing state
    test_ip1 = "192.168.1.100"
    test_ip2 = "192.168.1.101"
    for ip in [test_ip1, test_ip2]:
        if ip in guard._rate_limits:
            del guard._rate_limits[ip]
        if ip in guard._blocked_ips:
            del guard._blocked_ips[ip]

    limit = settings.soul_generate_rate_limit_per_minute

    # Simulate requests from IP1
    for _ in range(limit):
        guard.check_rate_limit(test_ip1, limit)

    # IP1 should now be rate limited
    try:
        guard.check_rate_limit(test_ip1, limit)
        assert False, f"IP1 should be rate limited after {limit} requests"
    except Exception as e:
        assert "rate limit" in str(e).lower()

    # IP2 should still have quota (even though IP1 is exhausted)
    for _ in range(limit):
        try:
            guard.check_rate_limit(test_ip2, limit)
        except Exception:
            assert False, f"IP2 should have full quota (independent from IP1)"
    print("✓ Per-IP rate limiting: each IP has independent quota")


# =============================================================================
# TEST: Rate Limit Value Applies Correctly
# =============================================================================

def test_soul_generate_rate_limit_setting_used_in_test_mode():
    """
    Given the test mode uses in-memory guard,
    When checking the rate limit configuration,
    Then it should use the soul_generate_rate_limit_per_minute setting (5),
    Not the general rate limit (30).
    """
    from app.config import settings

    # Verify the stricter setting exists and is 5
    assert hasattr(settings, 'soul_generate_rate_limit_per_minute')
    assert settings.soul_generate_rate_limit_per_minute == 5

    # Verify it's different from the general rate limit
    assert settings.soul_generate_rate_limit_per_minute < settings.rate_limit_requests_per_minute
