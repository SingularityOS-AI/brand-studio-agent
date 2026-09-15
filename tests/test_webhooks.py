"""
Webhook Tests — Stripe webhook signature verification and idempotency

Tests:
1. Invalid signature is rejected (HTTP 400)
2. Invalid payload is rejected (HTTP 400)
3. Valid signature with checkout.session.completed accrues credits
4. Re-sending the same event (same event_id) does NOT accrue credits twice (idempotency)
5. payment_intent.succeeded accrues credits
6. payment_intent.payment_failed marks account as pending
7. setup_intent.succeeded saves default payment method
"""

import pytest
import json
from fastapi.testclient import TestClient
from app.main import app as fastapi_app

# ============================================================================
# FIXTURES
# ============================================================================
@pytest.fixture
def client():
    """
    TestClient for webhook tests.

    Webhooks don't require user authentication (they use Stripe signature verification),
    so we use TestClient directly without JWT headers.
    """
    return TestClient(fastapi_app)


@pytest.fixture
def test_user_id():
    """Mock user ID for tests."""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clean_guard_state():
    """
    guard._sessions and guard._webhook_events are module-global in-memory dicts.
    Without this, leftover sessions from earlier tests in this file share the same
    hardcoded test_user_id and _accrue_credits() (which matches by user_id, not
    session_token) ends up crediting a stale session from a previous test instead
    of the one this test just created.
    """
    # `guard._sessions` solo existe en modo in-memory (Guard.__init__ nunca
    # lo crea en modo Supabase -- ver hotfix H1); este entorno de desarrollo
    # tiene credenciales reales de Supabase, así que `.clear()` sin guardia
    # reventaba con AttributeError ANTES de que cualquier test de este
    # archivo llegara a ejecutarse.
    from app.guard import guard
    if hasattr(guard, "_sessions"):
        guard._sessions.clear()
    if hasattr(guard, "_webhook_events"):
        guard._webhook_events.clear()
    yield
    if hasattr(guard, "_sessions"):
        guard._sessions.clear()
    if hasattr(guard, "_webhook_events"):
        guard._webhook_events.clear()


# ============================================================================
# TESTS: Signature verification
# ============================================================================
def test_webhook_rejects_missing_signature(client, test_user_id):
    """
    Test that webhook rejects request without stripe-signature header.

    Expect HTTP 400 with "Missing stripe-signature header" detail.
    """
    # Create a fake checkout.session.completed event payload
    payload = json.dumps({
        "id": "evt_test_missing_signature",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "metadata": {
                    "user_id": test_user_id,
                    "credits": "550"
                }
            }
        }
    }).encode()

    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 401
    assert "Missing stripe-signature header" in response.json()["detail"]


def test_webhook_rejects_invalid_signature(client, test_user_id):
    """
    Test that webhook rejects request with invalid signature.

    Expect HTTP 400 with "Invalid signature" detail.
    """
    payload = json.dumps({
        "id": "evt_test_invalid_signature",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_456",
                "metadata": {
                    "user_id": test_user_id,
                    "credits": "550"
                }
            }
        }
    }).encode()

    # Send with invalid signature
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=invalid_signature"
        }
    )

    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


# ============================================================================
# TESTS: Idempotency
# ============================================================================
def test_webhook_idempotency_prevents_duplicate_credits(
    client,
    mocker,
    test_user_id
):
    """
    Test that sending the same event twice does NOT accrue credits twice.

    This is the critical idempotency test:
    - First event: credits should be added
    - Second event (same event_id): credits should NOT be added again

    We mock the Stripe signature verification to bypass real crypto during tests.
    """
    event_id = "evt_test_idempotency_once"
    initial_credits = 100

    # Mock signature verification to return a valid event
    mock_event = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_idempotency",
                "metadata": {
                    "user_id": test_user_id,
                    "package": "starter",
                    "credits": "550"
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock stripe.Webhook.construct_event to return our test event
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Create a test session with initial credits
    from app.guard import guard
    test_session_token = "session_token_test_idempotency"
    guard._sessions[test_session_token] = {
        "user_id": test_user_id,
        "credits": initial_credits
    }

    # Mock get_session to return our test session
    original_get_session = guard.get_session
    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)
    mocker.patch.object(guard, "get_session", side_effect=mock_get_session)

    # Send first webhook
    response1 = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response1.status_code == 200
    assert response1.json()["status"] == "success"

    # Verify credits were added (100 + 550 = 650)
    credits_after_first = guard._sessions[test_session_token]["credits"]
    assert credits_after_first == initial_credits + 550

    # Send the SAME event again (same event_id)
    response2 = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response2.status_code == 200
    assert response2.json()["status"] == "success"

    # Credits should NOT be added again (still 650, not 1200)
    credits_after_second = guard._sessions[test_session_token]["credits"]
    assert credits_after_second == credits_after_first  # Same value
    assert credits_after_second == initial_credits + 550  # 650, not 1200


# ============================================================================
# TESTS: Event types
# ============================================================================
def test_checkout_session_completed_accrues_credits(
    client,
    mocker,
    test_user_id
):
    """
    Test that checkout.session.completed accrues credits correctly.
    """
    initial_credits = 100

    # Mock event
    mock_event = {
        "id": "evt_test_checkout_success",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_success",
                "metadata": {
                    "user_id": test_user_id,
                    "package": "pro",
                    "credits": "1800"
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Create test session
    from app.guard import guard
    test_session_token = "session_token_test_checkout"
    guard._sessions[test_session_token] = {
        "user_id": test_user_id,
        "credits": initial_credits
    }

    # Mock get_session
    original_get_session = guard.get_session
    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)
    mocker.patch.object(guard, "get_session", side_effect=mock_get_session)

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify credits added (100 + 1800 = 1900)
    current_credits = guard._sessions[test_session_token]["credits"]
    assert current_credits == initial_credits + 1800


def test_payment_intent_succeeded_accrues_credits(
    client,
    mocker,
    test_user_id
):
    """
    Test that payment_intent.succeeded accrues credits (auto-reload case).
    """
    initial_credits = 50

    # Mock event
    mock_event = {
        "id": "evt_test_pi_success",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_test_success",
                "off_session": True,  # Auto-reload
                "metadata": {
                    "user_id": test_user_id,
                    "package": "studio",
                    "credits": "4000"
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Create test session
    from app.guard import guard
    test_session_token = "session_token_test_pi_success"
    guard._sessions[test_session_token] = {
        "user_id": test_user_id,
        "credits": initial_credits
    }

    # Mock get_session
    original_get_session = guard.get_session
    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)
    mocker.patch.object(guard, "get_session", side_effect=mock_get_session)

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify credits added (50 + 4000 = 4050)
    current_credits = guard._sessions[test_session_token]["credits"]
    assert current_credits == initial_credits + 4000


def test_payment_intent_failed_marks_pending(
    client,
    mocker,
    test_user_id
):
    """
    Test that payment_intent.payment_failed marks account as payment pending.
    """
    # Mock event
    mock_event = {
        "id": "evt_test_pi_failed",
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": "pi_test_failed",
                "metadata": {
                    "user_id": test_user_id
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Create test session
    from app.guard import guard
    test_session_token = "session_token_test_pi_failed"
    guard._sessions[test_session_token] = {
        "user_id": test_user_id,
        "credits": 100,
        "payment_pending": False  # Initially not pending
    }

    # Mock get_session
    original_get_session = guard.get_session
    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)
    mocker.patch.object(guard, "get_session", side_effect=mock_get_session)

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify payment_pending flag set
    assert guard._sessions[test_session_token]["payment_pending"] is True


def test_setup_intent_succeeded_saves_payment_method(
    client,
    mocker,
    test_user_id
):
    """
    Test that setup_intent.succeeded saves the default payment method.
    """
    stripe_customer_id = "cus_test_123"
    payment_method_id = "pm_test_456"

    # Mock event
    mock_event = {
        "id": "evt_test_setup_success",
        "type": "setup_intent.succeeded",
        "data": {
            "object": {
                "id": "seti_test_success",
                "customer": stripe_customer_id,
                "payment_method": payment_method_id
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Create test session
    from app.guard import guard
    test_session_token = "session_token_test_setup"
    guard._sessions[test_session_token] = {
        "user_id": test_user_id,
        "credits": 100,
        "stripe_customer_id": stripe_customer_id,
        "default_payment_method_id": None  # Initially not saved
    }

    # Mock get_session
    original_get_session = guard.get_session
    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)
    mocker.patch.object(guard, "get_session", side_effect=mock_get_session)

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify default_payment_method_id saved
    assert guard._sessions[test_session_token]["default_payment_method_id"] == payment_method_id


# ============================================================================
# TESTS: Edge cases
# ============================================================================
def test_webhook_missing_metadata(client, mocker):
    """
    Test that webhook handles events with missing metadata gracefully.
    """
    # Mock event without metadata
    mock_event = {
        "id": "evt_test_no_metadata",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_no_metadata",
                "metadata": {}  # Empty metadata
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    # Should still return 200 (we acknowledge receipt even if processing fails)
    # The event gets recorded to prevent infinite retries
    # Note: In production, this would be logged for investigation
    assert response.status_code == 200


def test_webhook_unknown_event_type(client, mocker):
    """
    Test that webhook handles unknown event types gracefully.
    """
    # Mock unknown event type
    mock_event = {
        "id": "evt_test_unknown",
        "type": "unknown.event.type",
        "data": {}
    }

    payload = json.dumps(mock_event).encode()

    # Mock signature verification
    mocker.patch(
        "stripe.Webhook.construct_event",
        return_value=mock_event
    )

    # Send webhook
    response = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=1234567890,v1=test_sig"
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    # Event should be recorded to avoid retries
    from app.guard import guard
    assert hasattr(guard, "_webhook_events")
    assert "evt_test_unknown" in guard._webhook_events


# ============================================================================
# HOTFIX FACTURACIÓN — H1 (guard.add_credits AttributeError en modo Supabase)
# y H2 (webhook_events con columnas inventadas + marca-antes-de-procesar)
# ============================================================================
from unittest.mock import MagicMock, patch


def test_add_credits_supabase_mode_without_sessions_attr_does_not_raise():
    """
    Bug H1 regression: en modo Supabase, `Guard` NUNCA crea `self._sessions`
    (ver guard.py __init__) -- este es el estado REAL de este entorno de
    desarrollo (credenciales reales presentes). add_credits() debe sumar los
    créditos exactamente una vez y no reventar con AttributeError.

    Cliente Supabase mockeado con la forma REAL que usa guard.py:
    table("sessions").select("*").eq("user_id", ...).order(...).limit(1).execute()
    """
    from app.guard import guard

    assert not hasattr(guard, "_sessions")  # documenta la condición real de producción

    mock_client = MagicMock()
    select_chain = mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
    select_chain.execute.return_value = MagicMock(data=[{"token": "tok_1", "credits": 100, "user_id": "user_1"}])
    update_chain = mock_client.table.return_value.update.return_value.eq.return_value
    update_chain.execute.return_value = MagicMock(data=[{"token": "tok_1"}])

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            result = guard.add_credits("user_1", 550, source="checkout:starter")

    assert result is True
    # Se sumó UNA sola vez: 100 + 550 = 650, nunca 1100/1200 por reintento.
    mock_client.table.return_value.update.assert_called_once_with({"credits": 650})


@pytest.mark.asyncio
async def test_check_webhook_idempotency_is_read_only_no_insert():
    """
    Bug H2 regression: _check_webhook_idempotency() ya NO inserta -- antes
    marcaba el evento como procesado ANTES de correr el handler, así que un
    handler que fallaba dejaba el evento "fantasma" como completado y Stripe
    nunca podía reintentarlo con éxito.
    """
    from app.webhooks import _check_webhook_idempotency
    from app.guard import guard

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            result = await _check_webhook_idempotency("evt_123")

    assert result is False
    mock_client.table.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_mark_webhook_processed_uses_real_table_columns():
    """
    Bug H2 regression: la tabla real (migración 003) tiene columnas
    `event_id, event_type, processed_at` -- el insert viejo mandaba
    `{"processed": True, "created_at": "now()"}`, columnas inexistentes que
    garantizaban que el insert fallara siempre.
    """
    from app.webhooks import _mark_webhook_processed
    from app.guard import guard

    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"event_id": "evt_123", "event_type": "checkout.session.completed"}]
    )

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            await _mark_webhook_processed("evt_123", "checkout.session.completed")

    mock_client.table.return_value.insert.assert_called_once_with({
        "event_id": "evt_123",
        "event_type": "checkout.session.completed",
    })


@pytest.mark.asyncio
async def test_webhook_idempotency_duplicate_event_id_only_recorded_once():
    """
    Bug H2 regression end-to-end (sin red real): el mismo event_id llega dos
    veces -- la 2da vez _check_webhook_idempotency() debe verlo como ya
    procesado, y el insert real (simulado con una tabla en memoria con PK)
    solo debe haber ocurrido una vez.
    """
    from app.webhooks import _check_webhook_idempotency, _mark_webhook_processed
    from app.guard import guard

    events_table = []  # simula la tabla real con PK en event_id

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
        lambda: MagicMock(data=list(events_table))
    )

    def fake_insert(payload):
        events_table.append(payload)
        insert_mock = MagicMock()
        insert_mock.execute.return_value = MagicMock(data=[payload])
        return insert_mock

    mock_client.table.return_value.insert.side_effect = fake_insert

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            assert await _check_webhook_idempotency("evt_dup_1") is False
            await _mark_webhook_processed("evt_dup_1", "checkout.session.completed")

            # Reintento de Stripe con el MISMO event_id
            assert await _check_webhook_idempotency("evt_dup_1") is True

    assert len(events_table) == 1
    assert events_table[0] == {"event_id": "evt_dup_1", "event_type": "checkout.session.completed"}
