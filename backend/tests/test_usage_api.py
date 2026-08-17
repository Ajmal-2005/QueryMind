"""Token/cost tracking and the audit trail (F29), plus the first RBAC gate."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.usage import RATES, estimate_cost


@pytest.fixture
def connection_id(client: TestClient, auth_headers: dict, demo_db_path: str) -> str:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Demo", "dialect": "sqlite", "database": demo_db_path},
    ).json()
    client.post(f"/api/v1/connections/{created['id']}/index", headers=auth_headers)
    return created["id"]


def _headers_with_role(client: TestClient, engine, role) -> dict:
    """Register a user and set its role explicitly.

    Roles cannot be assumed here: the *first* account registered against a
    database becomes admin, so whether the shared `auth_headers` fixture is
    privileged depends on test ordering. Every role-sensitive test says what
    it wants.

    The role is set through its own short-lived session rather than the `db`
    fixture, which holds an open transaction for the whole test - committing
    on it while the TestClient also writes deadlocks SQLite.
    """
    import uuid

    from sqlalchemy.orm import sessionmaker

    from app.models.user import User

    email = f"{role.value}-{uuid.uuid4().hex[:8]}@example.com"
    token = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    ).json()["access_token"]

    session = sessionmaker(bind=engine)()
    try:
        user = session.query(User).filter(User.email == email).one()
        user.role = role
        session.commit()
    finally:
        session.close()

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client: TestClient, engine) -> dict:
    from app.models.user import UserRole

    return _headers_with_role(client, engine, UserRole.ADMIN)


@pytest.fixture
def analyst_headers(client: TestClient, engine) -> dict:
    from app.models.user import UserRole

    return _headers_with_role(client, engine, UserRole.ANALYST)


# -------------------------------------------------------------------- cost


def test_cost_is_zero_for_the_offline_providers() -> None:
    assert estimate_cost(100_000, "stub") == 0.0
    assert estimate_cost(100_000, "template") == 0.0


def test_cost_scales_with_tokens() -> None:
    assert estimate_cost(2_000_000) == pytest.approx(2 * estimate_cost(1_000_000))


def test_an_unknown_model_falls_back_rather_than_reporting_zero() -> None:
    """Silently costing an unknown model at zero would hide real spend."""
    assert estimate_cost(1_000_000, "some-future-model") > 0


# ------------------------------------------------------------------- usage


def test_usage_reports_this_users_own_activity(
    client: TestClient, analyst_headers: dict, demo_db_path: str
) -> None:
    # Its own connection: the shared `connection_id` fixture belongs to a
    # different user, and a query against it would 404 rather than be counted.
    own = client.post(
        "/api/v1/connections",
        headers=analyst_headers,
        json={"name": "Analyst demo", "dialect": "sqlite", "database": demo_db_path},
    ).json()["id"]
    client.post(f"/api/v1/connections/{own}/index", headers=analyst_headers)

    client.post(
        "/api/v1/query",
        headers=analyst_headers,
        json={"connection_id": own, "question": "How many customers?"},
    )

    body = client.get("/api/v1/usage", headers=analyst_headers).json()
    assert body["scope"] == "you"
    assert body["totals"]["queries"] >= 1
    # A non-admin never sees anyone else's rows.
    assert body["by_user"] == []


def test_the_rates_used_travel_with_the_figures(
    client: TestClient, analyst_headers: dict
) -> None:
    """A cost with no rate beside it silently becomes wrong when prices move."""
    body = client.get("/api/v1/usage", headers=analyst_headers).json()
    assert {r["model"] for r in body["rates"]} == set(RATES)
    assert "Estimated" in body["cost_note"]


def test_usage_is_scoped_per_user(
    client: TestClient, auth_headers: dict, connection_id: str, analyst_headers: dict
) -> None:
    """One user's question volume is not another user's business."""
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )

    body = client.get("/api/v1/usage", headers=analyst_headers).json()
    assert body["totals"]["queries"] == 0


def test_an_admin_sees_a_per_user_breakdown(
    client: TestClient, auth_headers: dict, connection_id: str, admin_headers: dict
) -> None:
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )

    body = client.get("/api/v1/usage", headers=admin_headers).json()
    assert body["scope"] == "all users"
    assert len(body["by_user"]) >= 1
    assert all("email" in row for row in body["by_user"])


def test_usage_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/usage").status_code == 401


# ------------------------------------------------------------ audit / RBAC


def test_the_audit_trail_is_admin_only(
    client: TestClient, analyst_headers: dict
) -> None:
    """`require_roles` has existed since Phase 0 and was never wired up."""
    response = client.get("/api/v1/usage/audit", headers=analyst_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


def test_an_admin_can_read_the_audit_trail(
    client: TestClient, auth_headers: dict, connection_id: str, admin_headers: dict
) -> None:
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )

    entries = client.get("/api/v1/usage/audit", headers=admin_headers).json()
    assert entries
    assert any(e["action"] == "query.answer" for e in entries)


def test_the_audit_trail_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/usage/audit").status_code == 401
