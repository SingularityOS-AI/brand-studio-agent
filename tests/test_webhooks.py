"""
Webhook Tests — Stripe webhook signature verification and idempotency

Tests:
1. Invalid signature is rejected (HTTP 401)
2. Invalid payload is rejected (HTTP 401)
3. Valid signature with checkout.session.completed accrues credits
4. Re-sending the same event (same event_id) does NOT accrue credits twice (idempotency)
5. payment_intent.succeeded accrues credits
6. payment_intent.payment_failed marks account as pending
7. setup_intent.succeeded saves default payment method

PIEZA 31 (bug B8): reescrito para NO depender de `pytest-mock` (el fixture
`mocker` no está instalado y no se debe instalar) -- se usa
`unittest.mock.patch`/`patch.object` directamente, mismo comportamiento.

También se descubrió, al quitar la dependencia rota de `mocker`, que este
entorno de desarrollo carga un `SUPABASE_KEY` real desde `.env`
(`app.config` hace `load_dotenv(override=False)`) mientras
`tests/conftest.py` fija `SUPABASE_URL` a un host de prueba que no resuelve
-- el resultado neto es `guard._use_supabase=True` con un cliente que JAMÁS
puede conectar (DNS falla: "[Errno 11001] getaddrinfo failed"), no el modo
in-memory limpio que estos tests de sesión simulada necesitan. Se agregó
`_force_in_memory_guard()` para forzar ese modo de forma explícita y
determinista en los tests que lo requieren (los tests H1/H2/B8a que SÍ
quieren ejercitar el camino real de Supabase lo patchean a `True` ellos
mismos, y ese patch anidado gana mientras dura su propio `with`).

Se agregan regresiones nuevas (Pieza 31, bug B8):
  - evento duplicado concurrente/consecutivo acredita créditos una sola vez
    (vía `_claim_webhook_event`, el INSERT atómico que reemplazó el
    check-then-insert-al-final)
  - un handler que falla libera el evento reclamado (para que Stripe pueda
    reintentar de verdad)
  - `guard.add_credits` en modo Supabase usa la vía atómica (RPC
    `accrue_credits`), no lee-suma-escribe
"""

import pytest
import json
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
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
    guard._sessions and guard._webhook_events son diccionarios/sets
    globales en memoria. Sin esto, sesiones de tests anteriores comparten el
    mismo test_user_id hardcodeado y accrue_credits (que empareja por
    user_id, no por session_token) termina acreditando una sesión vieja de
    otro test en vez de la que este test acaba de crear.
    """
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


@contextmanager
def _force_in_memory_guard(guard):
    """
    Fuerza modo en memoria en `guard` para la duración del bloque -- ver la
    nota del docstring del módulo sobre por qué `_use_supabase` es `True`
    por defecto en este entorno de desarrollo pese a que `tests/conftest.py`
    intenta simular modo test.
    """
    with patch.object(guard, "_use_supabase", False):
        if hasattr(guard, "_sessions"):
            guard._sessions.clear()
            yield
        else:
            with patch.object(guard, "_sessions", {}, create=True):
                yield


def _wire_session_lookup(guard, test_session_token):
    """
    Reemplaza guard.get_session por una versión que resuelve
    test_session_token contra guard._sessions -- mismo patrón que usaban
    todos los tests originales con `mocker.patch.object(guard, "get_session", ...)`,
    ahora con unittest.mock.patch.object para no depender de pytest-mock.

    Returns:
        El objeto patcher (context manager) listo para usar en un `with`.
    """
    original_get_session = guard.get_session

    def mock_get_session(session_token):
        if session_token == test_session_token:
            return guard._sessions[session_token]
        return original_get_session(session_token)

    return patch.object(guard, "get_session", side_effect=mock_get_session)


# ============================================================================
# TESTS: Signature verification
# ============================================================================
def test_webhook_rejects_missing_signature(client, test_user_id):
    """
    Test that webhook rejects request without stripe-signature header.

    Expect HTTP 401 with "Missing stripe-signature header" detail.
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

    Expect HTTP 401 with "Invalid signature" detail.
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
def test_webhook_idempotency_prevents_duplicate_credits(client, test_user_id):
    """
    Test that sending the same event twice (consecutively) does NOT accrue
    credits twice.

    This is the critical idempotency test:
    - First event: credits should be added
    - Second event (same event_id): credits should NOT be added again
    """
    event_id = "evt_test_idempotency_once"
    initial_credits = 100

    mock_event = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_idempotency",
                # `payment_intent` es opcional en el evento real de Stripe,
                # pero `_get_event_attr` no acepta un default -- sin esta
                # clave, _handle_checkout_session_completed revienta con
                # AttributeError antes de siquiera intentar guardarlo.
                "payment_intent": None,
                "metadata": {
                    "user_id": test_user_id,
                    "package": "starter",
                    "credits": "550"
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    from app.guard import guard
    test_session_token = "session_token_test_idempotency"

    with _force_in_memory_guard(guard):
        guard._sessions[test_session_token] = {
            "user_id": test_user_id,
            "created_at": time.time(),
            "credits": initial_credits
        }

        with patch("stripe.Webhook.construct_event", return_value=mock_event), \
             _wire_session_lookup(guard, test_session_token):

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

            # Send the SAME event again (same event_id), consecutively
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
            assert response2.json().get("duplicate") is True

            # Credits should NOT be added again (still 650, not 1200)
            credits_after_second = guard._sessions[test_session_token]["credits"]
            assert credits_after_second == credits_after_first  # Same value
            assert credits_after_second == initial_credits + 550  # 650, not 1200


# ============================================================================
# TESTS: Event types
# ============================================================================
def test_checkout_session_completed_accrues_credits(client, test_user_id):
    """
    Test that checkout.session.completed accrues credits correctly.
    """
    initial_credits = 100

    mock_event = {
        "id": "evt_test_checkout_success",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_success",
                "payment_intent": None,
                "metadata": {
                    "user_id": test_user_id,
                    "package": "pro",
                    "credits": "1800"
                }
            }
        }
    }

    payload = json.dumps(mock_event).encode()

    from app.guard import guard
    test_session_token = "session_token_test_checkout"

    with _force_in_memory_guard(guard):
        guard._sessions[test_session_token] = {
            "user_id": test_user_id,
            "created_at": time.time(),
            "credits": initial_credits
        }

        with patch("stripe.Webhook.construct_event", return_value=mock_event), \
             _wire_session_lookup(guard, test_session_token):

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

        current_credits = guard._sessions[test_session_token]["credits"]
        assert current_credits == initial_credits + 1800


def test_payment_intent_succeeded_accrues_credits(client, test_user_id):
    """
    Test that payment_intent.succeeded accrues credits (auto-reload case).
    """
    initial_credits = 50

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

    from app.guard import guard
    test_session_token = "session_token_test_pi_success"

    with _force_in_memory_guard(guard):
        guard._sessions[test_session_token] = {
            "user_id": test_user_id,
            "created_at": time.time(),
            "credits": initial_credits
        }

        with patch("stripe.Webhook.construct_event", return_value=mock_event), \
             _wire_session_lookup(guard, test_session_token):

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

        current_credits = guard._sessions[test_session_token]["credits"]
        assert current_credits == initial_credits + 4000


def test_payment_intent_failed_marks_pending(client, test_user_id):
    """
    Test that payment_intent.payment_failed marks account as payment pending.
    """
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

    from app.guard import guard
    test_session_token = "session_token_test_pi_failed"

    with _force_in_memory_guard(guard):
        guard._sessions[test_session_token] = {
            "user_id": test_user_id,
            "created_at": time.time(),
            "credits": 100,
            "payment_pending": False  # Initially not pending
        }

        with patch("stripe.Webhook.construct_event", return_value=mock_event), \
             _wire_session_lookup(guard, test_session_token):

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
        assert guard._sessions[test_session_token]["payment_pending"] is True


def test_setup_intent_succeeded_saves_payment_method(client, test_user_id):
    """
    Test that setup_intent.succeeded saves the default payment method.
    """
    stripe_customer_id = "cus_test_123"
    payment_method_id = "pm_test_456"

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

    from app.guard import guard
    test_session_token = "session_token_test_setup"

    with _force_in_memory_guard(guard):
        guard._sessions[test_session_token] = {
            "user_id": test_user_id,
            "created_at": time.time(),
            "credits": 100,
            "stripe_customer_id": stripe_customer_id,
            "default_payment_method_id": None  # Initially not saved
        }

        with patch("stripe.Webhook.construct_event", return_value=mock_event), \
             _wire_session_lookup(guard, test_session_token):

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
        assert guard._sessions[test_session_token]["default_payment_method_id"] == payment_method_id


# ============================================================================
# TESTS: Edge cases
# ============================================================================
def test_webhook_missing_metadata(client):
    """
    Test that webhook handles events with missing metadata gracefully.

    _handle_checkout_session_completed levanta HTTPException(400) por
    metadata faltante; el handler genérico de stripe_webhook() la convierte
    en 500 (para que Stripe reintente) y, con el fix de Pieza 31 (bug B8a),
    libera el reclamo del evento -- el reintento SÍ puede volver a procesar.
    """
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

    from app.guard import guard

    with _force_in_memory_guard(guard):
        with patch("stripe.Webhook.construct_event", return_value=mock_event):
            response = client.post(
                "/api/stripe/webhook",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": "t=1234567890,v1=test_sig"
                }
            )

        # El handler falla por metadata faltante -> 500 (Stripe reintentará).
        assert response.status_code == 500

        # El evento debe haber quedado LIBERADO (bug B8a), no atascado como
        # "reclamado para siempre" -- se puede volver a reclamar.
        assert "evt_test_no_metadata" not in guard._webhook_events


def test_webhook_unknown_event_type(client):
    """
    Test that webhook handles unknown event types gracefully.
    """
    mock_event = {
        "id": "evt_test_unknown",
        "type": "unknown.event.type",
        "data": {}
    }

    payload = json.dumps(mock_event).encode()

    from app.guard import guard

    with _force_in_memory_guard(guard):
        with patch("stripe.Webhook.construct_event", return_value=mock_event):
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
        # Event should be recorded (reclamado al inicio) to avoid retries
        assert hasattr(guard, "_webhook_events")
        assert "evt_test_unknown" in guard._webhook_events


# ============================================================================
# HOTFIX FACTURACIÓN — H1 (guard.add_credits AttributeError en modo Supabase)
# y H2 (webhook_events con columnas inventadas + marca-antes-de-procesar)
# ============================================================================
def test_add_credits_supabase_mode_without_sessions_attr_does_not_raise():
    """
    Bug H1 regression: en modo Supabase, `Guard` NUNCA crea `self._sessions`
    (ver guard.py __init__) -- este es el estado REAL de este entorno de
    desarrollo (credenciales reales presentes). add_credits() debe sumar los
    créditos exactamente una vez y no reventar con AttributeError.

    PIEZA 31 (bug B8b): add_credits() en modo Supabase ya NO hace
    lee-suma-escribe -- usa la función SQL atómica `accrue_credits` vía RPC
    (migración 004). El mock ahora cubre `.rpc(...)` en vez de
    `.table(...).update(...)`.
    """
    from app.guard import guard

    assert not hasattr(guard, "_sessions")  # documenta la condición real de producción

    mock_client = MagicMock()

    # RPC atómica: accrue_credits(p_user_id, p_credits) -> True si actualizó una fila
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=True)

    # Re-lectura post-RPC (solo para logging/sync de cache en memoria)
    select_chain = mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
    select_chain.execute.return_value = MagicMock(data=[{"token": "tok_1", "credits": 650, "user_id": "user_1"}])

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            result = guard.add_credits("user_1", 550, source="checkout:starter")

    assert result is True
    # La suma la hace la función SQL atómica -- NUNCA lee-suma-escribe en Python.
    mock_client.rpc.assert_called_once_with(
        "accrue_credits",
        params={"p_user_id": "user_1", "p_credits": 550},
    )
    mock_client.table.return_value.update.assert_not_called()


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


# ============================================================================
# PIEZA 31 (bug B8a) — reclamo atómico del evento (_claim_webhook_event)
# ============================================================================
@pytest.mark.asyncio
async def test_claim_webhook_event_concurrent_or_consecutive_only_claims_once():
    """
    Regresión B8a: dos intentos de reclamar el MISMO event_id -- ya sea que
    lleguen consecutivos (reintento normal de Stripe) o simulando la carrera
    concurrente (segunda entrega llega antes de que la primera termine de
    procesar) -- solo el primero debe ganar el INSERT. El segundo debe ver
    `False` (duplicado) sin volver a acreditar nada.

    Usa el fallback en memoria (`guard._webhook_events`, el mismo camino que
    ejercitan los tests end-to-end de arriba) para no depender de una tabla
    Postgres real ni de mockear una violación de PK exacta.
    """
    from app.webhooks import _claim_webhook_event
    from app.guard import guard

    with _force_in_memory_guard(guard):
        event_id = "evt_claim_race"

        first = await _claim_webhook_event(event_id, "checkout.session.completed")
        second = await _claim_webhook_event(event_id, "checkout.session.completed")

        assert first is True
        assert second is False
        assert event_id in guard._webhook_events


@pytest.mark.asyncio
async def test_claim_webhook_event_supabase_duplicate_key_is_treated_as_duplicate():
    """
    Regresión B8a (modo Supabase): si el INSERT falla por violación de PK
    (23505 / duplicate key -- el caso real cuando dos entregas concurrentes
    llegan casi al mismo tiempo y ambas intentan el INSERT), `_claim_webhook_event`
    debe interpretarlo como "ya reclamado" (False), no como un error de
    infraestructura que deba re-procesarse.
    """
    from app.webhooks import _claim_webhook_event
    from app.guard import guard

    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.side_effect = Exception(
        'duplicate key value violates unique constraint "webhook_events_pkey" (23505)'
    )

    with patch.object(guard, "_use_supabase", True):
        with patch.object(guard, "_supabase", mock_client):
            claimed = await _claim_webhook_event("evt_pk_conflict", "checkout.session.completed")

    assert claimed is False


@pytest.mark.asyncio
async def test_release_webhook_event_allows_reclaim_after_handler_failure():
    """
    Regresión B8a: si el handler falla después de reclamar el evento,
    `_release_webhook_event` debe liberar el reclamo -- el reintento de
    Stripe debe poder reclamar y procesar exitosamente.
    """
    from app.webhooks import _claim_webhook_event, _release_webhook_event
    from app.guard import guard

    with _force_in_memory_guard(guard):
        event_id = "evt_release_retry"

        claimed = await _claim_webhook_event(event_id, "checkout.session.completed")
        assert claimed is True

        # Handler falló -- se libera el reclamo.
        await _release_webhook_event(event_id)
        assert event_id not in guard._webhook_events

        # El reintento de Stripe ahora puede reclamar de nuevo y procesar.
        reclaimed = await _claim_webhook_event(event_id, "checkout.session.completed")
        assert reclaimed is True
