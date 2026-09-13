"""
Stripe Billing Module — Customer + Checkout

This module handles:
- Stripe Customer creation and retrieval
- Stripe Checkout Session creation for credit package purchases
- Integration with Supabase for storing stripe_customer_id

CRITICAL RULES (from plan.md):
1. Never use stripe.charges.create (API legacy). Use Checkout Session.
2. Claves de Stripe solo desde os.getenv("STRIPE_SECRET_KEY") / settings
3. mode='payment' NEVER mode='subscription' - it's prepaid credits, not recurring
"""
import os
from typing import Literal
from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel
import stripe

from app.config import settings


# ============================================================================
# CREDIT PACKAGES - Stripe price IDs already created in test mode (2026-09-11)
# ============================================================================
CREDIT_PACKAGES = {
    # price_id reales, ya creados en Stripe modo test por el Capitan (2026-09-11).
    # Los equivalentes de modo LIVE se crean aparte el dia que se active cobro real -
    # nunca reusar un price_id de test en produccion.
    "starter": {"price_usd": 9, "credits": 550, "stripe_price_id": "price_1UEbb70StQbwtwVc8mTCMm4Q"},
    "pro":     {"price_usd": 29, "credits": 1800, "stripe_price_id": "price_1UEbcq0StQbwtwVcahleC7WN"},
    "studio":  {"price_usd": 59, "credits": 4000, "stripe_price_id": "price_1UEbdv0StQbwtwVc3TMmj93B"},
}


# ============================================================================
# PYDANTIC MODELS
# ============================================================================
class CheckoutRequest(BaseModel):
    package: Literal["starter", "pro", "studio"]


class CheckoutResponse(BaseModel):
    url: str


# ============================================================================
# STRIPE SETUP
# ============================================================================
stripe.api_key = settings.stripe_secret_key
print(f"[BILLING] Stripe API key loaded: {'YES' if settings.stripe_secret_key else 'NO'}")
if settings.stripe_secret_key:
    print(f"[BILLING] Stripe API key prefix: {settings.stripe_secret_key[:7]}...")
print(f"[BILLING] Stripe environment: {'Test (sk_test)' if settings.stripe_secret_key and settings.stripe_secret_key.startswith('sk_test_') else 'Unknown'}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
async def get_or_create_stripe_customer(user_id: str, email: str) -> str:
    """
    Devuelve stripe_customer_id, creándolo si no existe.

    Se guarda en la tabla de usuario (columna stripe_customer_id en `sessions`).

    Args:
        user_id: Supabase user ID (UUID)
        email: User email address

    Returns:
        stripe_customer_id: The Stripe customer ID

    Raises:
        HTTPException: If user cannot be found in Supabase
    """
    from app.guard import guard
    from app.auth.supabase_auth import supabase_auth

    # Get session from guard (it has access to Supabase)
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User session not found"
        )

    # Check if stripe_customer_id already exists
    if session.get('stripe_customer_id'):
        return session['stripe_customer_id']

    # Create new Stripe customer
    try:
        customer = stripe.Customer.create(
            email=email,
            metadata={"user_id": user_id}
        )
        stripe_customer_id = customer.id
    except stripe.error.StripeError as e:
        print(f"[BILLING] Failed to create Stripe customer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create payment customer"
        )

    # Save stripe_customer_id to session (in Supabase if configured)
    # Direct Supabase update to bypass guard's credit-focused methods
    if guard._use_supabase and guard._supabase is not None:
        try:
            guard._supabase.table("sessions").update({
                "stripe_customer_id": stripe_customer_id
            }).eq("user_id", user_id).execute()
            print(f"[BILLING] Updated sessions table with stripe_customer_id")
        except Exception as e:
            print(f"[BILLING] Warning: Failed to save stripe_customer_id to Supabase: {e}")
            # Non-fatal - we can still proceed with checkout
    else:
        # In-memory storage for tests
        session['stripe_customer_id'] = stripe_customer_id

    print(f"[BILLING] Created Stripe customer {stripe_customer_id} for user {user_id}")
    return stripe_customer_id


# ============================================================================
# CHECKOUT ROUTER
# ============================================================================
router = APIRouter()


@router.post("/api/billing/checkout", response_model=CheckoutResponse)
async def create_checkout_session(request: Request, body: CheckoutRequest):
    """
    Creates a Stripe Checkout Session for credit package purchase.

    Request body:
        {"package": "starter" | "pro" | "studio"}

    Returns:
        {"url": "https://checkout.stripe.com/..."}

    The checkout session:
    - mode='payment' (NUNCA 'subscription')
    - line_items=[{price, quantity: 1}]
    - customer=<stripe_customer_id del usuario> (creado si no existe)
    - success_url/cancel_url apuntan a la app
    - metadata contiene user_id, package, credits (para webhook de Pieza 3)

    Requires JWT authentication.
    """
    # 1. Validate JWT and get user info
    authorization = request.headers.get("authorization")
    print(f"[BILLING] Received checkout request, auth header present: {bool(authorization)}")

    if not authorization:
        print("[BILLING] ERROR: Missing authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )

    from app.auth.supabase_auth import supabase_auth

    try:
        user_id = supabase_auth.get_user_id(authorization)
        user_email = supabase_auth.get_user_email(authorization)
        print(f"[BILLING] Validated user: {user_id} ({user_email})")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[BILLING] Failed to get user info: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization token"
        )

    # 2. Validate package
    package = body.package
    if package not in CREDIT_PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid package '{package}'. Must be one of: starter, pro, studio"
        )

    package_info = CREDIT_PACKAGES[package]

    # 3. Get or create Stripe customer
    try:
        stripe_customer_id = await get_or_create_stripe_customer(user_id, user_email)
    except HTTPException:
        raise

    # 4. Build success/cancel URLs (use current request URL base)
    # Get the base URL from the request (e.g., http://localhost:8000 or https://brand-studio-agent.xxx)
    scheme = request.url.scheme
    host = request.url.netloc
    base_url = f"{scheme}://{host}"

    success_url = f"{base_url}/?checkout=success"
    cancel_url = f"{base_url}/?checkout=cancelled"

    # 5. Create Stripe Checkout Session
    try:
        print(f"[BILLING] Creating Stripe checkout session for package '{package}' (price_id: {package_info['stripe_price_id']})")
        print(f"[BILLING] Success URL: {success_url}, Cancel URL: {cancel_url}")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",  # NUNCA 'subscription' - compra de créditos, no suscripción
            line_items=[
                {
                    "price": package_info["stripe_price_id"],
                    "quantity": 1,
                }
            ],
            customer=stripe_customer_id,
            success_url=success_url,
            cancel_url=cancel_url,
            # Save payment method for future auto-reload (Piece 3)
            # This allows off-session charging when credits reach 0
            payment_intent_data={
                "setup_future_usage": "off_session"
            },
            metadata={
                "user_id": user_id,
                "package": package,
                "credits": str(package_info["credits"]),
            }
        )
        print(f"[BILLING] Successfully created Stripe checkout session: {session.id}")
        print(f"[BILLING] Checkout URL: {session.url}")
    except stripe.error.StripeError as e:
        print(f"[BILLING] Stripe error creating checkout session: {type(e).__name__}: {e}")
        if hasattr(e, 'user_message'):
            print(f"[BILLING] Stripe user message: {e.user_message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create checkout session: {str(e)}"
        )

    print(f"[BILLING] Created checkout session {session.id} for user {user_id}, package {package}")

    # 6. Return checkout URL
    return CheckoutResponse(url=session.url)


# ============================================================================
# AUTO-RELOAD WITH SAVED CARD
# ============================================================================
async def charge_saved_card(user_id: str, package: str) -> bool:
    """
    Auto-reload: charges off-session to the saved payment method when user reaches 0 credits.

    This function:
    1. Retrieves the user's session including default_payment_method_id and stripe_customer_id
    2. Validates that a saved payment method exists (from a previous checkout)
    3. Creates a Stripe PaymentIntent with off_session=True to charge the saved card
    4. Handles card errors (rejection, SCA requiring manual confirmation)

    If the payment fails (card reject or SCA requires auth):
    - Marks the account as "payment pending"
    - Does NOT retry automatically (Q2 = A: mas vale que falle una vez que cobre doble)
    - The user must manually resolve the failed payment

    Args:
        user_id: Supabase user ID (UUID)
        package: Package key ("starter" | "pro" | "studio")

    Returns:
        True if PaymentIntent created successfully (payment will be processed asynchronously)
        False if no saved card exists or if the card was rejected

    Raises:
        HTTPException: If the user session cannot be found

    Design notes (from spec.md, Q1 = A, Q2 = A):
    - Trigger: when user reaches EXACTLY 0 credits (not a floor threshold)
    - Off-session: card charged without user present
    - On failure: mark as pending, don't retry blindly
    - Stripe Smart Retries will handle transient failures naturally
    """
    from app.guard import guard

    # 1. Get user session
    session_token = guard.get_or_create_user_session(user_id)
    session = guard.get_session(session_token)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User session not found"
        )

    # 2. Check if user has a saved payment method
    default_payment_method_id = session.get("default_payment_method_id")
    stripe_customer_id = session.get("stripe_customer_id")

    if not default_payment_method_id or not stripe_customer_id:
        print(f"[BILLING] Auto-reload skipped for user {user_id}: no saved payment method")
        return False

    # 3. Validate package
    if package not in CREDIT_PACKAGES:
        print(f"[BILLING] Invalid package '{package}' for auto-reload")
        return False

    package_info = CREDIT_PACKAGES[package]
    amount_cents = package_info["price_usd"] * 100  # Convert USD to cents

    # 4. Create off-session PaymentIntent
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            customer=stripe_customer_id,
            payment_method=default_payment_method_id,
            off_session=True,  # Critical: off-session for automatic charging
            confirm=True,  # Confirm immediately (no client action needed)
            metadata={
                "user_id": user_id,
                "package": package,
                "credits": str(package_info["credits"]),
                "auto_reload": "true"  # Flag for webhook to distinguish auto-reload
            },
            # Error on requires_action: if SCA requires confirmation, don't charge automatically
            error_on_requires_action=True
        )

        print(f"[BILLING] Auto-reload PaymentIntent created for user {user_id}, package {package}: {payment_intent.id}")

        # Payment created successfully — stripe webhook will handle credit accrual
        return True

    except stripe.error.CardError as e:
        # Card was rejected or requires SCA authentication
        # Q2 = A: mark as pending, don't retry blindly
        error_code = e.error.get('code')
        error_message = e.error.get('message')

        print(f"[BILLING] Auto-reload CardError for user {user_id}: [{error_code}] {error_message}")

        # Mark as payment pending (user must manually resolve)
        # In TEST_MODE, update in-memory session
        import os
        if os.getenv("TEST_MODE", "false").lower() == "true":
            session["payment_pending"] = True
        elif guard._use_supabase and guard._supabase is not None:
            try:
                guard._supabase.table("sessions").update({"payment_pending": True}).eq("user_id", user_id).execute()
                print(f"[BILLING] Marked user {user_id} as payment pending")
            except Exception as db_error:
                print(f"[BILLING] Warning: Failed to mark payment pending: {db_error}")

        # Common SCA codes that require manual confirmation:
        # authentication_required, approve_with_id, card_not_supported, etc.
        # In all cases, we don't retry automatically (Q2 = A)
        return False

    except stripe.error.StripeError as e:
        # Other Stripe errors (network, API error, etc.)
        print(f"[BILLING] Auto-reload StripeError for user {user_id}: {e}")
        return False

    except Exception as e:
        # Unexpected error
        print(f"[BILLING] Unexpected auto-reload error for user {user_id}: {e}")
        return False
