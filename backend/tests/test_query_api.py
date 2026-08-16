"""The /query endpoint.

Runs against the stub provider (no API key in the test environment), so these
assert the contract and the plumbing rather than translation quality.
"""

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def connection_id(client: TestClient, auth_headers: dict, demo_db_path: str) -> str:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Demo", "dialect": "sqlite", "database": demo_db_path},
    ).json()
    client.post(f"/api/v1/connections/{created['id']}/index", headers=auth_headers)
    return created["id"]


def test_query_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query", json={"connection_id": "x", "question": "How many?"}
    )
    assert response.status_code == 401


def test_query_returns_sql(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["generation"]["sql"]
    assert body["question_type"] == "aggregation"


def test_response_exposes_the_retrieved_tables(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    # The SQL transparency panel needs to show what the model was shown.
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    ).json()

    names = [t["table_name"] for t in body["retrieved_tables"]]
    assert "customers" in names
    assert body["embedder"] == "hashing-local"


def test_response_reports_stage_timings(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    ).json()

    assert set(body["timings_ms"]) == {
        "intent",
        "retrieval",
        "generation",
        "execution",
        "learning",
        "analysis",
        "total",
    }


def test_query_returns_executed_rows(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    # The stub asks for the first ten rows of the top-ranked table, so the
    # pipeline runs all the way through execution.
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    ).json()

    assert body["result"] is not None
    assert body["result"]["columns"]
    assert body["result"]["row_count"] > 0
    assert body["validation"]["ok"] is True


def test_ambiguous_question_returns_a_clarification(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "show me something"},
    ).json()

    assert body["needs_clarification"] is True
    assert body["clarification"]
    assert body["generation"] is None


def test_query_against_an_unindexed_connection_is_a_conflict(
    client: TestClient, auth_headers: dict, demo_db_path: str
) -> None:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Unindexed", "dialect": "sqlite", "database": demo_db_path},
    ).json()

    response = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": created["id"], "question": "How many customers?"},
    )
    assert response.status_code == 409
    assert "index" in response.json()["detail"].lower()


def test_query_against_another_users_connection_is_404(
    client: TestClient, connection_id: str
) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct-horse-battery",
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    response = client.post(
        "/api/v1/query",
        headers=headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )
    assert response.status_code == 404


def test_empty_question_is_rejected(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": ""},
    )
    assert response.status_code == 422


def test_history_lists_recent_questions(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )

    body = client.get("/api/v1/query/history", headers=auth_headers).json()
    assert any(row["question"] == "How many customers?" for row in body)


def test_history_is_scoped_to_the_user(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    )

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct-horse-battery",
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.get("/api/v1/query/history", headers=headers).json() == []


# ----------------------------------------------------------- manual SQL


def test_manual_sql_executes(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/query/execute",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "sql": "SELECT COUNT(*) AS n FROM orders",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["result"]["rows"][0][0] == 2000


def test_manual_sql_goes_through_the_same_gates(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    # Hand-written SQL is not more trusted than generated SQL — if anything
    # less, since it never passed through a prompt that forbade writes.
    body = client.post(
        "/api/v1/query/execute",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": "DROP TABLE orders"},
    ).json()

    assert body["rejected"] is True
    assert body["validation"]["gate"] == "safety"
    assert body["result"] is None


def test_manual_sql_with_a_bad_column_is_reported(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query/execute",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": "SELECT nope FROM orders"},
    ).json()

    assert body["validation"]["ok"] is False
    assert body["validation"]["gate"] == "schema"
    assert body["validation"]["retryable"] is True


def test_manual_sql_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query/execute", json={"connection_id": "x", "sql": "SELECT 1"}
    )
    assert response.status_code == 401


def test_manual_sql_against_another_users_connection_is_404(
    client: TestClient, connection_id: str
) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct-horse-battery",
        },
    ).json()

    response = client.post(
        "/api/v1/query/execute",
        headers={"Authorization": f"Bearer {other['access_token']}"},
        json={"connection_id": connection_id, "sql": "SELECT 1"},
    )
    assert response.status_code == 404
