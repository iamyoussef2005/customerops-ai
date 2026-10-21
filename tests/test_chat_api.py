"""Authentication and safe API failures without a database or provider connection."""

import hashlib
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_chat_requires_authentication_before_database_access(client: TestClient) -> None:
    response = client.post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


def test_untrusted_customer_header_is_not_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat", json={"message": "hello"}, headers={"X-Customer-ID": str(uuid4())}
    )
    assert response.status_code == 401


def test_invalid_bearer_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "hello"},
        headers={"Authorization": "Bearer " + "bad-token" * 10},
    )
    assert response.status_code == 401


def test_valid_server_mapped_bearer_gets_safe_unavailable_without_database(
    client: TestClient,
) -> None:
    token = "fictional-offline-test-token-with-32-characters"
    cast(FastAPI, client.app).state.settings.auth_token_customers = {
        hashlib.sha256(token.encode()).hexdigest(): uuid4()
    }
    response = client.post(
        "/api/v1/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "service_unavailable", "message": "Customer support is unavailable."}
    }
