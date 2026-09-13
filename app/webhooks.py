"""
Stripe Webhook Handler — Receipts, Idempotency, Credit Accrual

This module handles:
- Stripe webhook signature verification (security)
- Idempotency checking via webhook_events table
- Processing checkout.session.completed events (credit accrual)
- Processing payment_intent.succeeded events (auto-reload support)

CRITICAL RULES (from plan.md):
1. Always read raw body before parsing JSON (signature verification needs raw bytes)
2. Check idempotency BEFORE processing (webhook_events PK on event_id)
3. Only process checkout.session.completed with valid metadata (user_id, package, credits)
4. Never use stripe.charges.create — use checkout sessions only
"""
import os
from typing import Literal
from fastapi import APIRouter, Request, HTTPException, status
from stripe.error import SignatureVerificationError
import stripe

from app.config import settings
from app.billing import CREDIT_PACKAGES
from app.guard import guard


def _get_event_attr(event, *path):
    """
    Access nested event attributes safely (supports both Stripe objects and dicts).
    Usage: _get_event_attr(event, "data", "object") or event.data.object
    """
    current = event
    for attr in path:
        # Try attribute access first (Stripe object)
        if hasattr(current, attr):
            current = getattr(current, attr)
        # Fall back to dict access (for tests)
        elif isinstance(current, dict) and attr in current:
            current = current[attr]
        else:
            raise AttributeError(f"Event object missing attribute: {'.'.join(path)}")
    return current


# ============================================================================
# STRIPE SETUP
# ============================================================================
stripe.api_key = settings.stripe_secret_key
print(f"[WEBHOOKS] Stripe API key loaded: {'YES' if settings.stripe_secret_key else 'NO'}")
if settings.stripe_secret_key:
    print(f"[WEBHOOKS] Stripe API key prefix: {settings.stripe_secret_key[:7]}...")
print(f"[WEBHOOKS] Stripe webhook secret loaded: {'YES' if settings.stripe_webhook_secret else 'NO'}")
if settings.stripe_webhook_secret:
    print(f"[WEBHOOKS] Stripe webhook secret prefix: {settings.stripe_webhook_secret[:7]}...")


# ============================================================================
# WEBHOOK ROUTER
# ============================================================================
router = APIRouter()


# ============================================================================
# IDEMPOTENCY CHECKING
# ============================================================================
async def _check_webhook_idempotency(event_id: str) -> bool:
    """
    Check if this webhook event has already been processed.

    Query the webhook_events table for the event_id.
    If found, return True — we've already processed this event.
    If not found, return False — safe to proceed.

    After processing the webhook:
    1. Insert event_id into webhook_events table
    2. This ensures future retries are idempotent

    Args:
        event_id: Stripe event ID (e.g., "evt_1234567890")

    Returns:
        True if already processed, False if safe to process
    """
    import os
    from app.guard import guard

    # In TEST_MODE, use in-memory set for idempotency
    if os.getenv("TEST_MODE", "false").lower() == "true":
        # In test mode, we use a simple module-level set
        if not hasattr(_check_webhook_idempotency, "_processed_events"):
            _check_webhook_idempotency._processed_events = set()

        if event_id in _check_webhook_idempotency._processed_events:
            print(f"[WEBHOOKS] Event {event_id} already processed (test mode)")
            return True

        # Mark as processed
        _check_webhook_idempotency._processed_events.add(event_id)
        return False

    # Production: use Supabase webhook_events table
    if guard._use_supabase and guard._supabase is not None:
        try:
            # Check if event already exists
            result = guard._supabase.table("webhook_events").select("event_id").eq("event_id", event_id).execute()

            if result.data:
                print(f"[WEBHOOKS] Event {event_id} already processed (database)")
                return True

            # Insert new event record
            guard._supabase.table("webhook_events").insert({
                "event_id": event_id,
                "processed": True,
                "created_at": "now()"
            }).execute()

            print(f"[WEBHOOKS] Event {event_id} marked as processed")
            return False

        except Exception as e:
            print(f"[WEBHOOKS] WARNING: Failed to check idempotency: {e}")
            # Fail open: if we can't check, process cautiously (but Stripe will retry)
            return False
    else:
        # Fallback: no database configured, skip idempotency check
        # This is NOT safe for production, but acceptable for local testing
        print(f"[WEBHOOKS] WARNING: No database configured, skipping idempotency check")
        return False


# ============================================================================
# WEBHOOK ENDPOINT
# ============================================================================
@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint — handles all Stripe event types.

    Security:
    - Verifies Stripe webhook signature using raw request body
    - Reads raw body BEFORE parsing JSON (critical for signature verification)

    Idempotency:
    - Checks webhook_events table before processing
    - Ignores duplicate events to prevent double-credit accrual

    Supported events:
    - checkout.session.completed: Manually-activated credit purchases
    - payment_intent.succeeded: Auto-reload purchases (off-session)

    Flow:
    1. Read raw body from request
    2. Verify Stripe signature
    3. Parse Stripe event
    4. Check idempotency (abort if already processed)
    5. Route to appropriate handler based on event type
    6. Handler accrues credits and updates database
    7. Return 200 OK
    """
    # 1. Read raw body BEFORE parsing JSON (critical for signature verification)
    # We need to use request._body directly because Python/Starlette might have already consumed it
    raw_body = await request.body()

    # 2. Verify Stripe webhook signature
    # The signature is in the 'stripe-signature' header
    signature_header = request.headers.get("stripe-signature")

    if not signature_header:
        print("[WEBHOOKS] ERROR: Missing stripe-signature header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing stripe-signature header"
        )

    if not settings.stripe_webhook_secret:
        print("[WEBHOOKS] ERROR: STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe webhook secret not configured"
        )

    try:
        # Verify signature using raw body (not parsed JSON)
        event = stripe.Webhook.construct_event(
            payload=raw_body,
            sig_header=signature_header,
            secret=settings.stripe_webhook_secret
        )
    except (ValueError, SignatureVerificationError) as e:
        print(f"[WEBHOOKS] Signature verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )

    # 3. Extract event metadata for logging
    event_id = _get_event_attr(event, "id")
    event_type = _get_event_attr(event, "type")
    print(f"[WEBHOOKS] Received event: {event_id}, type: {event_type}")

    # Initialize webhook_events set for test compatibility
    if not hasattr(guard, "_webhook_events"):
        guard._webhook_events = set()

    # 4. Check idempotency (abort if already processed)
    already_processed = await _check_webhook_idempotency(event_id)
    if already_processed:
        print(f"[WEBHOOKS] Duplicate event {event_id}, ignoring (idempotency)")
        return {"status": "success", "duplicate": True}

    # 5. Route to appropriate handler based on event type
    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_session_completed(event)
        elif event_type == "payment_intent.succeeded":
            await _handle_payment_intent_succeeded(event)
        elif event_type == "payment_intent.payment_failed":
            await _handle_payment_intent_failed(event)
        elif event_type == "setup_intent.succeeded":
            await _handle_setup_intent_succeeded(event)
        else:
            print(f"[WEBHOOKS] Unhandled event type: {event_type}")
            # Still record the event to avoid retries
            guard._webhook_events.add(event_id)
            # Still return 200 OK because event type might be for future features
            return {"status": "success", "message": f"Event type {event_type} not handled"}
    except Exception as e:
        print(f"[WEBHOOKS] ERROR processing event {event_id}: {e}")
        # Return 500 to trigger Stripe retry (up to 3 days)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}"
        )

    # 6. Record event and return success response
    guard._webhook_events.add(event_id)
    print(f"[WEBHOOKS] Successfully processed event {event_id}")
    return {"status": "success"}


# ============================================================================
# EVENT HANDLERS
# ============================================================================
async def _handle_checkout_session_completed(event):
    """
    Handle checkout.session.completed — manual credit purchase.

    This event fires when a user successfully completes a Stripe Checkout Session.
    We must:
    1. Extract user_id, package, credits from metadata
    2. Validate the package exists and credits match our package definitions
    3. Accrue credits to the user's session
    4. Save payment method ID for future auto-reload
    5. Record the purchase in last_package field

    Args:
        event: Stripe Event object containing checkout.session data

    Raises:
        HTTPException: If metadata is missing or invalid
    """
    session = _get_event_attr(event, "data", "object")
    metadata = _get_event_attr(session, "metadata")
    session_id = _get_event_attr(session, "id")

    print(f"[WEBHOOKS] Processing checkout.session.completed: {session_id}")
    print(f"[WEBHOOKS] Metadata: {metadata}")

    # 1. Extract and validate metadata
    user_id = metadata.get("user_id")
    package = metadata.get("package")
    credits_str = metadata.get("credits")

    if not user_id or not package or not credits_str:
        print(f"[WEBHOOKS] ERROR: Missing required metadata in session {session_id}")
        return

    # 2. Validate package and credits
    if package not in CREDIT_PACKAGES:
        print(f"[WEBHOOKS] ERROR: Invalid package '{package}' in session {session_id}")
        return

    expected_credits = CREDIT_PACKAGES[package]["credits"]
    actual_credits = int(credits_str)

    if actual_credits != expected_credits:
        print(f"[WEBHOOKS] ERROR: Credits mismatch for package '{package}': expected {expected_credits}, got {actual_credits}")
        return

    # 3. Get or create user session and accrue credits
    from app.guard import guard

    try:
        # Use the accrue_credits SQL function created in migration 004
        # This handles comparing 0 checks and ensures safety
        if guard._use_supabase and guard._supabase is not None:
            print(f"[WEBHOOKS] Accruing {actual_credits} credits to user {user_id}")

            # Call the accrue_credits function
            result = guard._supabase.rpc("accrue_credits", {
                "p_user_id": user_id,
                "p_credits": actual_credits,
                "p_source": f"checkout:{package}"
            }).execute()

            print(f"[WEBHOOKS] Accrue result: {result}")
        else:
            # In-memory for testing
            session_token = guard.get_or_create_user_session(user_id)
            user_session = guard.get_session(session_token)
            user_session["credits"] = user_session.get("credits", 0) + actual_credits
            print(f"[WEBHOOKS] [MEM] Accrued {actual_credits} credits to user {user_id}, new total: {user_session['credits']}")

    except Exception as e:
        print(f"[WEBHOOKS] ERROR: Failed to accrue credits: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to accrue credits: {str(e)}"
        )

    # 4. Save payment method ID for future auto-reload
    # The SetupIntent attached to the session creates a payment method
    payment_intent_id = session.get("payment_intent")
    if payment_intent_id:
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            payment_method_id = payment_intent.get("payment_method")

            if payment_method_id:
                print(f"[WEBHOOKS] Saving default_payment_method_id {payment_method_id} for user {user_id}")

                # Update sessions table with payment method ID
                if guard._use_supabase and guard._supabase is not None:
                    guard._supabase.table("sessions").update({
                        "default_payment_method_id": payment_method_id
                    }).eq("user_id", user_id).execute()
                else:
                    # In-memory for testing
                    session_token = guard.get_or_create_user_session(user_id)
                    user_session = guard.get_session(session_token)
                    user_session["default_payment_method_id"] = payment_method_id

            # Also mark this customer as having valid payment (important for auto-reload)
        except Exception as e:
            print(f"[WEBHOOKS] WARNING: Failed to save payment method ID: {e}")
            # Non-fatal - credit accrual succeeded

    # 5. Record package in last_package field
    try:
        if guard._use_supabase and guard._supabase is not None:
            guard._supabase.table("sessions").update({
                "last_package": package
            }).eq("user_id", user_id).execute()
            print(f"[WEBHOOKS] Updated last_package = {package} for user {user_id}")
        else:
            session_token = guard.get_or_create_user_session(user_id)
            user_session = guard.get_session(session_token)
            user_session["last_package"] = package
    except Exception as e:
        print(f"[WEBHOOKS] WARNING: Failed to update last_package: {e}")
        # Non-fatal - credit accrual succeeded

    print(f"[WEBHOOKS] Successfully processed checkout.session.completed for user {user_id}, package {package}")


async def _handle_payment_intent_succeeded(event):
    """
    Handle payment_intent.succeeded — auto-reload (off-session) purchases.

    This event fires when an off-session payment intent succeeds (auto-reload).
    The auto-reload is triggered by guard.charge_saved_card() when credits reach 0.

    The flow:
    1. Extract user_id, package, credits from PaymentIntent metadata
    2. Validate the package exists and credits match definitions
    3. Accrue credits to the user's session (same logic as manual checkout)
    4. Clear payment_pending flag (if it was set)

    Critical difference from checkout.session.handler:
    - This is for off-session payments (saved card, no user present)
    - Metadata includes "auto_reload": "true" flag
    - Payment created programmatically, not via Checkout UI

    Args:
        event: Stripe Event object containing payment_intent data

    Raises:
        HTTPException: If metadata is missing or invalid
    """
    # Get payment_intent from the event data
    payment_intent = _get_event_attr(event, "data", "object")
    payment_intent_id = _get_event_attr(payment_intent, "id")
    metadata = _get_event_attr(payment_intent, "metadata")

    # For test compatibility, also handle direct dict access
    metadata = _get_event_attr(payment_intent, "metadata")

    print(f"[WEBHOOKS] Processing payment_intent.succeeded: {payment_intent_id}")
    print(f"[WEBHOOKS] Metadata: {metadata}")

    # 1. Check if this is an auto-reload payment
    # Accept both "auto_reload": "true" in metadata, or off_session=True in payment intent
    is_auto_reload = metadata.get("auto_reload") == "true"
    off_session = _get_event_attr(payment_intent, "off_session")

    if not is_auto_reload and not off_session:
        # This is a manual payment (checkout.session will handle it)
        print(f"[WEBHOOKS] Skipping non-auto-reload payment_intent")
        return

    # 2. Extract and validate metadata
    user_id = metadata.get("user_id")
    package = metadata.get("package")
    credits_str = metadata.get("credits")

    if not user_id or not package or not credits_str:
        print(f"[WEBHOOKS] ERROR: Missing required metadata in payment_intent {payment_intent_id}")
        return

    # 3. Validate package and credits
    if package not in CREDIT_PACKAGES:
        print(f"[WEBHOOKS] ERROR: Invalid package '{package}' in payment_intent {payment_intent_id}")
        return

    expected_credits = CREDIT_PACKAGES[package]["credits"]
    actual_credits = int(credits_str)

    if actual_credits != expected_credits:
        print(f"[WEBHOOKS] ERROR: Credits mismatch for package '{package}': expected {expected_credits}, got {actual_credits}")
        return

    # 4. Accrue credits (same logic as manual checkout)
    from app.guard import guard

    try:
        if guard._use_supabase and guard._supabase is not None:
            print(f"[WEBHOOKS] Accruing {actual_credits} credits to user {user_id} (auto-reload)")

            result = guard._supabase.rpc("accrue_credits", {
                "p_user_id": user_id,
                "p_credits": actual_credits,
                "p_source": f"auto_reload:{package}"
            }).execute()

            print(f"[WEBHOOKS] Accrue result: {result}")
        else:
            # In-memory for testing
            session_token = guard.get_or_create_user_session(user_id)
            user_session = guard.get_session(session_token)
            user_session["credits"] = user_session.get("credits", 0) + actual_credits
            print(f"[WEBHOOKS] [MEM] Accrued {actual_credits} credits to user {user_id} (auto-reload), new total: {user_session['credits']}")

    except Exception as e:
        print(f"[WEBHOOKS] ERROR: Failed to accrue credits: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to accrue credits: {str(e)}"
        )

    # 5. Clear payment_pending flag (if it was set)
    # This flag is set when auto-reload fails due to card errors
    try:
        if guard._use_supabase and guard._supabase is not None:
            guard._supabase.table("sessions").update({
                "payment_pending": False
            }).eq("user_id", user_id).execute()
            print(f"[WEBHOOKS] Cleared payment_pending flag for user {user_id}")
        else:
            session_token = guard.get_or_create_user_session(user_id)
            user_session = guard.get_session(session_token)
            user_session["payment_pending"] = False
    except Exception as e:
        print(f"[WEBHOOKS] WARNING: Failed to clear payment_pending: {e}")
        # Non-fatal - credit accrual succeeded

    print(f"[WEBHOOKS] Successfully processed payment_intent.succeeded (auto-reload) for user {user_id}, package {package}")


async def _handle_payment_intent_failed(event):
    """
    Handle payment_intent.payment_failed — mark account as payment pending.

    This event fires when an auto-reload payment fails (card declined, expired, etc.).
    We mark the user's account as payment_pending so they can't make calls until they
    update their payment method.

    Args:
        event: Stripe Event object containing payment_intent data
    """
    payment_intent = _get_event_attr(event, "data", "object")
    payment_intent_id = _get_event_attr(payment_intent, "id")
    metadata = _get_event_attr(payment_intent, "metadata")

    user_id = metadata.get("user_id")

    if not user_id:
        print(f"[WEBHOOKS] ERROR: Missing user_id in payment_intent {payment_intent_id}")
        return

    print(f"[WEBHOOKS] Processing payment_intent.payment_failed: {payment_intent_id}")

    from app.guard import guard

    try:
        if guard._use_supabase and guard._supabase is not None:
            guard._supabase.table("sessions").update({
                "payment_pending": True
            }).eq("user_id", user_id).execute()
            print(f"[WEBHOOKS] Marked user {user_id} as payment_pending")
        else:
            session_token = guard.get_or_create_user_session(user_id)
            user_session = guard.get_session(session_token)
            user_session["payment_pending"] = True
            print(f"[WEBHOOKS] Marked user {user_id} as payment_pending (in-memory)")

    except Exception as e:
        print(f"[WEBHOOKS] WARNING: Failed to mark payment_pending: {e}")
        # Non-fatal - webhook acknowledged


async def _handle_setup_intent_succeeded(event):
    """
    Handle setup_intent.succeeded — save payment method for auto-reload.

    This event fires when a SetupIntent completes successfully, typically after
    the user enters their card details in the checkout session. We save the
    payment_method_id for future auto-reload charges.

    Args:
        event: Stripe Event object containing setup_intent data
    """
    setup_intent = _get_event_attr(event, "data", "object")
    stripe_customer_id = _get_event_attr(setup_intent, "customer")
    payment_method_id = _get_event_attr(setup_intent, "payment_method")

    print(f"[WEBHOOKS] Processing setup_intent.succeeded: pm={payment_method_id}, customer={stripe_customer_id}")

    if not stripe_customer_id or not payment_method_id:
        print(f"[WEBHOOKS] ERROR: Missing customer or payment_method in setup_intent")
        return

    from app.guard import guard

    try:
        if guard._use_supabase and guard._supabase is not None:
            # Update sessions table with payment method ID
            guard._supabase.table("sessions").update({
                "default_payment_method_id": payment_method_id
            }).eq("stripe_customer_id", stripe_customer_id).execute()
            print(f"[WEBHOOKS] Saved payment_method {payment_method_id} for customer {stripe_customer_id}")
        else:
            # In-memory for testing - find session by stripe_customer_id
            for token, session in guard._sessions.items():
                if session.get("stripe_customer_id") == stripe_customer_id:
                    session["default_payment_method_id"] = payment_method_id
                    print(f"[WEBHOOKS] Saved payment_method {payment_method_id} for customer {stripe_customer_id} (in-memory)")
                    break

    except Exception as e:
        print(f"[WEBHOOKS] WARNING: Failed to save payment method: {e}")
        # Non-fatal - webhook acknowledged
