#!/usr/bin/env python3
"""
Webhook local test script
Simula eventos de Stripe para validar los manejadores sin requerir Testing Banks
"""

import json
import uuid
import sys
from datetime import datetime

# Mock data structure similar to Stripe events
TEST_USER_ID = "test-user-123"
TEST_CREDITS = 1800
TEST_PACKAGE = "pro"


def create_checkout_session_completed_event():
    """Crea un evento simulado de checkout.session.completed"""
    return {
        "id": f"evt_test_{uuid.uuid4()}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_test_{uuid.uuid4()}",
                "payment_status": "paid",
                "metadata": {
                    "user_id": TEST_USER_ID,
                    "credits": str(TEST_CREDITS),
                    "package": TEST_PACKAGE
                },
                "customer_details": {
                    "email": "test@example.com"
                },
                "amount_total": 2900,
                "currency": "usd"
            }
        },
        "created": int(datetime.now().timestamp())
    }


def create_payment_intent_succeeded_event():
    """Crea un evento simulado de payment_intent.succeeded"""
    return {
        "id": f"evt_test_{uuid.uuid4()}",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_test_{uuid.uuid4()}",
                "status": "succeeded",
                "amount": 2900,
                "currency": "usd",
                "metadata": {
                    "user_id": TEST_USER_ID,
                    "credits": str(TEST_CREDITS),
                    "package": TEST_PACKAGE
                },
                # Critical: off_session field exists
                "off_session": True,
                "checkout_session": f"cs_test_{uuid.uuid4()}"
            }
        },
        "created": int(datetime.now().timestamp())
    }


def test_webhook_endpoint():
    """
    Prueba los webhook endpoints localmente
    """
    import httpx
    import asyncio

    print("="*60)
    print("LOCAL WEBHOOK TEST")
    print("="*60)

    base_url = "http://127.0.0.1:8000"

    async def run_tests():
        async with httpx.AsyncClient(timeout=30.0) as client:

            # Test 1: checkout.session.completed
            print("\n[TEST 1] Testing checkout.session.completed handler...")
            event1 = create_checkout_session_completed_event()
            print(f"  Event ID: {event1['id']}")
            print(f"  User ID: {TEST_USER_ID}")
            print(f"  Credits: {TEST_CREDITS}")

            try:
                response = await client.post(
                    f"{base_url}/api/stripe/webhook",
                    json=event1,
                    headers={"Content-Type": "application/json"}
                )
                print(f"  Response: {response.status_code}")
                if response.status_code == 200:
                    print(f"  ✓ SUCCESS: checkout.session.completed handler returned 200 OK")
                else:
                    print(f"  ✗ FAILED: Expected 200, got {response.status_code}")
                    print(f"  Response body: {response.text}")
            except Exception as e:
                print(f"  ✗ FAILED: Exception occurred: {e}")

            # Test 2: payment_intent.succeeded
            print("\n[TEST 2] Testing payment_intent.succeeded handler...")
            event2 = create_payment_intent_succeeded_event()
            print(f"  Event ID: {event2['id']}")
            print(f"  Payment ID: {event2['data']['object']['id']}")
            print(f"  off_session: {event2['data']['object']['off_session']}")

            try:
                response = await client.post(
                    f"{base_url}/api/stripe/webhook",
                    json=event2,
                    headers={"Content-Type": "application/json"}
                )
                print(f"  Response: {response.status_code}")
                if response.status_code == 200:
                    print(f"  ✓ SUCCESS: payment_intent.succeeded handler returned 200 OK")
                else:
                    print(f"  ✗ FAILED: Expected 200, got {response.status_code}")
                    print(f"  Response body: {response.text}")
            except Exception as e:
                print(f"  ✗ FAILED: Exception occurred: {e}")

            # Test 3: Verify credits were added
            print("\n[TEST 3] Verifying credit balance...")
            try:
                # Check /api/session endpoint
                response = await client.get(
                    f"{base_url}/api/session"
                )
                print(f"  Session endpoint response: {response.status_code}")
                if response.status_code == 200:
                    session_data = response.json()
                    credits = session_data.get("credits", 0)
                    print(f"  Credits in session: {credits}")
                    if credits >= TEST_CREDITS:
                        print(f"  ✓ SUCCESS: Credits were added correctly")
                    else:
                        print(f"  ✗ WARNING: Expected {TEST_CREDITS} credits, got {credits}")
                else:
                    print(f"  ✗ FAILED: Could not verify credits")
            except Exception as e:
                print(f"  ✗ FAILED: Exception occurred: {e}")

    asyncio.run(run_tests())


if __name__ == "__main__":
    print("Starting webhook local tests...")
    print("Make sure your FastAPI server is running on http://127.0.0.1:8000")
    print("Press Enter to continue or Ctrl+C to cancel...")
    try:
        input()
    except KeyboardInterrupt:
        print("\nTest cancelled.")
        sys.exit(0)

    test_webhook_endpoint()
