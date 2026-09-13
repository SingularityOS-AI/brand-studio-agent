"""
Tests for billing module (Piece 2 - Stripe Customer + Checkout)

These tests focus on critical validations that can be tested without complex mocking:
1. CREDIT_PACKAGES structure
2. Required authentication
3. Mode='payment' enforcement in the billing code itself
"""
import pytest
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.billing import CREDIT_PACKAGES
from app.main import app as fastapi_app
from fastapi.testclient import TestClient

# Check for Stripe dependency
try:
    import stripe
except ImportError:
    pytest.skip("Stripe not installed - install with: pip install stripe>=11.0.0", allow_module_level=True)


# Create test client
client = TestClient(fastapi_app)


class TestCreditPackages:
    """Test CREDIT_PACKAGES structure and values"""

    def test_credit_packages_keys(self):
        """Verify all expected packages exist"""
        assert "starter" in CREDIT_PACKAGES
        assert "pro" in CREDIT_PACKAGES
        assert "studio" in CREDIT_PACKAGES

    def test_credit_package_fields(self):
        """Verify each package has required fields"""
        for package_key, package_data in CREDIT_PACKAGES.items():
            assert "stripe_price_id" in package_data, f"{package_key} missing stripe_price_id"
            assert "credits" in package_data, f"{package_key} missing credits"
            assert "price_usd" in package_data, f"{package_key} missing price_usd"

    def test_stripe_price_id_format(self):
        """Verify Stripe price IDs are in correct format"""
        for package_key, package_data in CREDIT_PACKAGES.items():
            price_id = package_data["stripe_price_id"]
            # Stripe price IDs typically start with "price_"
            assert price_id.startswith("price_"), f"{package_key} price_id '{price_id}' should start with 'price_'"


class TestCheckoutEndpoint:
    """Test POST /api/billing/checkout endpoint"""

    def test_checkout_without_auth(self):
        """Test that checkout requires authentication"""
        response = client.post(
            "/api/billing/checkout",
            json={"package": "starter"}
        )
        assert response.status_code == 401
        assert "authorization" in str(response.json()).lower()

    def test_checkout_missing_package(self):
        """Test that package parameter is required"""
        import jwt

        payload = {
            "sub": "user_123",
            "email": "user@test.com",
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": 9999999999,
        }
        token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")

        # Missing package field
        response = client.post(
            "/api/billing/checkout",
            json={},
            headers={"Authorization": f"Bearer {token}"}
        )
        # Should fail validation (422) or auth (401) depending on order
        assert response.status_code in [422, 401]

    def test_checkout_invalid_package_format(self):
        """Test that invalid package format is rejected (validation error)"""
        response = client.post(
            "/api/billing/checkout",
            json={"package": "invalid_package"}
        )
        # Pydantic validation should reject this before auth check
        assert response.status_code == 422


class TestBillingCodeModeValidation:
    """Test that the billing code enforces mode='payment'"""

    def test_billing_code_uses_payment_mode(self):
        """
        CRITICAL: Verify the billing.py source code uses mode='payment'.
        This is a code inspection test, not an integration test.
        """
        import inspect
        from app.billing import create_checkout_session

        # Get the source code of the function
        source = inspect.getsource(create_checkout_session)

        # Verify mode='payment' is present
        assert 'mode="payment"' in source, "Source code must contain mode='payment'"

        # Verify mode='subscription' is NOT present
        assert 'mode="subscription"' not in source, "CRITICAL: mode='subscription' must NOT be in source code"
        assert "'subscription'" not in source.split('mode=')[0], "CRITICAL: 'subscription' must not be used"

        # Verify the comment about payment mode exists
        assert 'NUNCA' in source or 'NEVER' in source, "Code should have comment about payment-only mode"

    def test_stripe_checkout_create_is_not_charges_create(self):
        """
        Verify the billing code uses stripe.checkout.Session.create
        NOT stripe.charges.create (legacy API)
        """
        import inspect
        from app.billing import create_checkout_session

        source = inspect.getsource(create_checkout_session)

        # Verify we use correct API
        assert 'stripe.checkout.Session.create' in source, "Must use stripe.checkout.Session.create"

        # Verify we don't use legacy API
        assert 'stripe.charges.create' not in source, "CRITICAL: Must NOT use stripe.charges.create (legacy)"

    def test_credit_packages_integration(self):
        """Verify all package configs have proper data for Stripe"""
        for package_key, package_data in CREDIT_PACKAGES.items():
            # Each package needs a valid Stripe price ID
            price_id = package_data["stripe_price_id"]
            assert price_id, f"{package_key} price_id cannot be empty"

            # Each package needs credit count
            credits = package_data["credits"]
            assert isinstance(credits, int), f"{package_key} credits must be integer"
            assert credits > 0, f"{package_key} credits must be positive"

            # Each package needs price info
            price_usd = package_data["price_usd"]
            assert isinstance(price_usd, int), f"{package_key} price_usd must be integer"
            assert price_usd > 0, f"{package_key} price_usd must be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
