"""Test script to simulate Stripe webhook events locally"""
import json
import httpx

# Simulate a checkout.session.completed event
webhook_event = {
    "id": "evt_test_123456",
    "type": "checkout.session.completed",
    "data": {
        "object": {
            "id": "cs_test_123456",
            "object": "checkout.session",
            "customer": "cus_test_customer",
            "metadata": {
                "user_id": "test-user-local-development",
                "package": "starter",
                "credits": "550"
            },
            "payment_intent": "pi_test_123456",
            "payment_status": "paid",
            "status": "complete"
        }
    }
}

# Send to webhook endpoint
response = httpx.post(
    "http://127.0.0.1:8010/api/stripe/webhook",
    json=webhook_event,
    headers={"Content-Type": "application/json"}
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# Check session credits after webhook
session_response = httpx.get(
    "http://127.0.0.1:8010/api/session",
    headers={"Authorization": "Bearer test-mode-bypass"}
)
print(f"\nSession after webhook: {session_response.json()}")
