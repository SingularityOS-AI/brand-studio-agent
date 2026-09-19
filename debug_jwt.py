import os
os.environ["TEST_MODE"] = "true"

from tests.jwt_helpers import create_test_jwt
from app.main import app
from fastapi.testclient import TestClient

token = create_test_jwt("550e8400-e29b-41d4-a716-446655440000")
print(f"Token: {token[:50]}...")

client = TestClient(app)
client.headers.update({"Authorization": f"Bearer {token}"})
response = client.get("/api/token")

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
