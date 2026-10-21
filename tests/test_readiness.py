"""Readiness is explicit about unavailable configuration; liveness remains independent."""

from fastapi.testclient import TestClient


def test_readiness_without_database_is_unavailable(client: TestClient) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not configured"}
    assert client.get("/api/v1/health").status_code == 200
