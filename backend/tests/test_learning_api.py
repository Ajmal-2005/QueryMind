"""The Phase 5 endpoints: explanation, suggestions, corrections, glossary."""

import pytest
from fastapi.testclient import TestClient

SQL = "SELECT region, COUNT(*) AS n FROM customers GROUP BY region"


@pytest.fixture
def connection_id(client: TestClient, auth_headers: dict, demo_db_path: str) -> str:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Demo", "dialect": "sqlite", "database": demo_db_path},
    ).json()
    client.post(f"/api/v1/connections/{created['id']}/index", headers=auth_headers)
    return created["id"]


# --------------------------------------------------------------- explanation


def test_executed_sql_comes_back_with_a_walkthrough(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query/execute",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": SQL},
    ).json()

    explanation = body["explanation"]
    assert explanation["parsed"] is True
    assert [s["clause"] for s in explanation["steps"]][:2] == ["FROM", "GROUP BY"]
    assert explanation["is_aggregate"] is True


def test_a_generated_query_is_explained_too(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    ).json()
    assert body["explanation"]["parsed"] is True
    assert body["explanation"]["summary"]


# --------------------------------------------------------------- suggestions


def test_suggestions_are_schema_aware(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.get(
        f"/api/v1/query/suggestions?connection_id={connection_id}",
        headers=auth_headers,
    ).json()

    assert body
    assert all(s["question"] and s["reason"] for s in body)
    text = " ".join(s["question"].lower() for s in body)
    assert any(t in text for t in ("order", "customer", "product"))


def test_suggestions_require_an_indexed_connection(
    client: TestClient, auth_headers: dict, demo_db_path: str
) -> None:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Unindexed", "dialect": "sqlite", "database": demo_db_path},
    ).json()
    response = client.get(
        f"/api/v1/query/suggestions?connection_id={created['id']}",
        headers=auth_headers,
    )
    assert response.status_code == 409


# --------------------------------------------------------------- corrections


def test_a_correction_is_saved_after_it_runs(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/learning/corrections",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "customers per region",
            "corrected_sql": SQL,
            "original_sql": "SELECT * FROM customers",
        },
    )
    assert response.status_code == 201
    assert response.json()["verified"] is True

    listed = client.get(
        f"/api/v1/learning/corrections?connection_id={connection_id}",
        headers=auth_headers,
    ).json()
    assert len(listed) == 1


def test_a_correction_that_does_not_run_is_refused(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    """An unverified correction taught as an example propagates the mistake."""
    response = client.post(
        "/api/v1/learning/corrections",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "customers per region",
            "corrected_sql": "SELECT nope FROM customers",
        },
    )
    assert response.status_code == 400


def test_a_correction_runs_the_safety_gates(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/learning/corrections",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "clean up",
            "corrected_sql": "DROP TABLE customers",
        },
    )
    assert response.status_code == 400
    assert "safety gate" in response.json()["detail"]


def test_a_saved_correction_shows_up_as_an_example(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    """The whole point of F22 - the next similar question is influenced by it."""
    client.post(
        "/api/v1/learning/corrections",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "customers per region",
            "corrected_sql": SQL,
        },
    )

    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "customers per region"},
    ).json()

    sources = [e["source"] for e in body["examples_used"]]
    assert "correction" in sources


# ------------------------------------------------------------------ glossary


def test_a_term_is_defined_and_applied_to_a_question(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(
        "/api/v1/learning/glossary",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "term": "active customer",
            "definition": "a customer who has placed an order",
            "sql_expression": (
                "EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"
            ),
        },
    )

    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "how many active customers per region",
        },
    ).json()

    assert [t["term"] for t in body["glossary_terms"]] == ["active customer"]


def test_redefining_a_term_updates_it_rather_than_duplicating(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    payload = {
        "connection_id": connection_id,
        "term": "churn",
        "definition": "first definition",
    }
    first = client.post("/api/v1/learning/glossary", headers=auth_headers, json=payload)
    second = client.post(
        "/api/v1/learning/glossary",
        headers=auth_headers,
        json={**payload, "definition": "revised definition"},
    )

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["definition"] == "revised definition"

    listed = client.get(
        f"/api/v1/learning/glossary?connection_id={connection_id}",
        headers=auth_headers,
    ).json()
    assert len(listed) == 1


def test_a_glossary_expression_cannot_smuggle_a_statement(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    """The expression is spliced into a prompt and may reach a query."""
    response = client.post(
        "/api/v1/learning/glossary",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "term": "evil",
            "definition": "nope",
            "sql_expression": "1=1; DROP TABLE customers",
        },
    )
    assert response.status_code == 400


def test_learning_data_is_private_to_its_owner(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    other = client.post(
        "/api/v1/auth/register",
        json={"email": "nosy@example.com", "password": "correct-horse-battery"},
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert (
        client.get(
            f"/api/v1/learning/corrections?connection_id={connection_id}",
            headers=headers,
        ).status_code
        == 404
    )


# ------------------------------------------------------------ multi-turn F19


def test_a_follow_up_is_resolved_against_the_previous_turn(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    session = "session-multiturn-1"
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "total revenue last quarter",
            "session_id": session,
        },
    )

    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "break that down by region",
            "session_id": session,
        },
    ).json()

    assert body["is_follow_up"] is True
    assert "total revenue last quarter" in body["resolved_question"]
    assert "grouped additionally by" in body["resolved_question"]


def test_a_follow_up_does_not_cross_sessions(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "total revenue last quarter",
            "session_id": "session-a",
        },
    )
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "question": "break that down by region",
            "session_id": "session-b",
        },
    ).json()

    assert body["is_follow_up"] is False


def test_a_vague_question_gets_concrete_options_not_a_lecture(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "show me something"},
    ).json()

    assert body["needs_clarification"] is True
    assert len(body["clarification_options"]) >= 2
    assert body["clarification"]
