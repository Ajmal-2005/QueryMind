"""Milestone-1 gate: the service reports itself healthy."""

from fastapi.testclient import TestClient


def test_root_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["docs"] == "/docs"
    assert body["health"] == "/api/v1/health"


def test_liveness_is_cheap_and_green(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_reports_database_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["services"]["database"]["status"] == "ok"


def test_health_marks_unconfigured_redis_without_degrading(client: TestClient) -> None:
    # Redis is optional in phase 0; absent config must not fail the gate.
    body = client.get("/api/v1/health").json()
    assert body["services"]["redis"]["status"] == "not_configured"
    assert body["status"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
