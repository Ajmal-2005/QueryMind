"""The connections API: registration, testing, indexing, schema, ownership."""

import uuid

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient) -> dict:
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def connection_id(client: TestClient, auth_headers: dict, demo_db_path: str) -> str:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Demo e-commerce",
            "dialect": "sqlite",
            "database": demo_db_path,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_creating_a_connection_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/connections",
        json={"name": "x", "dialect": "sqlite", "database": "/tmp/x.db"},
    )
    assert response.status_code == 401


def test_created_connection_never_returns_credentials(
    client: TestClient, auth_headers: dict, demo_db_path: str
) -> None:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Secret",
            "dialect": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "database": "analytics",
            "username": "analyst",
            "password": "hunter2",
        },
    )
    body = response.text

    assert response.status_code == 201
    assert "hunter2" not in body
    assert "encrypted_credentials" not in body
    assert "password" not in response.json()


def test_postgres_connection_requires_a_host(
    client: TestClient, auth_headers: dict
) -> None:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "No host",
            "dialect": "postgres",
            "database": "analytics",
            "username": "analyst",
        },
    )
    assert response.status_code == 422


def test_sqlite_connection_needs_no_host_port_or_credentials(
    client: TestClient, auth_headers: dict, demo_db_path: str
) -> None:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "File DB", "dialect": "sqlite", "database": demo_db_path},
    )
    assert response.status_code == 201, response.text
    assert response.json()["port"] == 0


def test_port_zero_is_rejected_as_not_a_real_port(
    client: TestClient, auth_headers: dict, demo_db_path: str
) -> None:
    # Clients must omit the port for file-backed databases rather than
    # sending 0; the UI relied on 0 once and got a 422 for it.
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Zero port",
            "dialect": "sqlite",
            "database": demo_db_path,
            "port": 0,
        },
    )
    assert response.status_code == 422


def test_postgres_port_defaults_when_omitted(
    client: TestClient, auth_headers: dict
) -> None:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Default port",
            "dialect": "postgres",
            "host": "db.example.com",
            "database": "analytics",
            "username": "analyst",
        },
    )
    assert response.json()["port"] == 5432


def test_listing_returns_only_your_own_connections(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    other = _register(client)
    assert client.get("/api/v1/connections", headers=other).json() == []

    mine = client.get("/api/v1/connections", headers=auth_headers).json()
    assert [c["id"] for c in mine] == [connection_id]


def test_another_user_cannot_read_your_connection(
    client: TestClient, connection_id: str
) -> None:
    other = _register(client)
    response = client.get(f"/api/v1/connections/{connection_id}", headers=other)

    # 404, not 403 - a 403 would confirm the id exists.
    assert response.status_code == 404


def test_unknown_connection_is_404(client: TestClient, auth_headers: dict) -> None:
    response = client.get(f"/api/v1/connections/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


def test_testing_a_connection_reports_the_server_version(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        f"/api/v1/connections/{connection_id}/test", headers=auth_headers
    )
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["server_version"]


def test_testing_an_unreachable_database_reports_failure(
    client: TestClient, auth_headers: dict
) -> None:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Unreachable",
            "dialect": "postgres",
            "host": "127.0.0.1",
            "port": 1,
            "database": "nope",
            "username": "u",
            "password": "p",
        },
    ).json()

    response = client.post(
        f"/api/v1/connections/{created['id']}/test", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False

    # The failure is recorded on the connection, not just returned.
    fetched = client.get(
        f"/api/v1/connections/{created['id']}", headers=auth_headers
    ).json()
    assert fetched["status"] == "failed"
    assert fetched["last_error"]


def test_indexing_reports_what_it_built(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        f"/api/v1/connections/{connection_id}/index", headers=auth_headers
    )
    body = response.json()

    assert response.status_code == 200
    assert body["tables_indexed"] == 8
    assert body["columns_indexed"] > 30
    assert body["foreign_keys"] >= 6
    assert body["embedder"] == "hashing-local"


def test_indexing_updates_the_connection_status(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(f"/api/v1/connections/{connection_id}/index", headers=auth_headers)

    fetched = client.get(
        f"/api/v1/connections/{connection_id}", headers=auth_headers
    ).json()
    assert fetched["status"] == "indexed"
    assert fetched["last_indexed_at"]


def test_indexing_a_broken_connection_returns_400_not_500(
    client: TestClient, auth_headers: dict
) -> None:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Broken",
            "dialect": "postgres",
            "host": "127.0.0.1",
            "port": 1,
            "database": "nope",
            "username": "u",
            "password": "p",
        },
    ).json()

    response = client.post(
        f"/api/v1/connections/{created['id']}/index", headers=auth_headers
    )
    assert response.status_code == 400

    fetched = client.get(
        f"/api/v1/connections/{created['id']}", headers=auth_headers
    ).json()
    assert fetched["status"] == "failed"


def test_schema_before_indexing_is_a_conflict(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.get(
        f"/api/v1/connections/{connection_id}/schema", headers=auth_headers
    )
    assert response.status_code == 409
    assert "index" in response.json()["detail"].lower()


def test_schema_returns_tables_columns_and_edges(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(f"/api/v1/connections/{connection_id}/index", headers=auth_headers)

    body = client.get(
        f"/api/v1/connections/{connection_id}/schema", headers=auth_headers
    ).json()

    assert body["table_count"] == 8
    assert {t["table_name"] for t in body["tables"]} >= {"orders", "customers"}
    assert body["isolated_tables"] == ["cust_ref_log_v2"]

    pairs = {(e["from_table"], e["to_table"]) for e in body["edges"]}
    assert ("customers", "orders") in pairs


def test_schema_edges_are_not_duplicated(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(f"/api/v1/connections/{connection_id}/index", headers=auth_headers)
    body = client.get(
        f"/api/v1/connections/{connection_id}/schema", headers=auth_headers
    ).json()

    pairs = [(e["from_table"], e["to_table"]) for e in body["edges"]]
    assert len(pairs) == len(set(pairs))


def test_schema_exposes_join_targets_and_samples(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(f"/api/v1/connections/{connection_id}/index", headers=auth_headers)
    body = client.get(
        f"/api/v1/connections/{connection_id}/schema", headers=auth_headers
    ).json()

    orders = next(t for t in body["tables"] if t["table_name"] == "orders")
    columns = {c["column_name"]: c for c in orders["columns"]}

    assert columns["customer_id"]["fk_target"] == "customers.id"
    assert "completed" in columns["status"]["sample_values"]


def test_deleting_a_connection_removes_its_index(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    client.post(f"/api/v1/connections/{connection_id}/index", headers=auth_headers)

    assert (
        client.delete(
            f"/api/v1/connections/{connection_id}", headers=auth_headers
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/connections/{connection_id}", headers=auth_headers
        ).status_code
        == 404
    )


def test_another_user_cannot_delete_your_connection(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    other = _register(client)

    assert (
        client.delete(f"/api/v1/connections/{connection_id}", headers=other).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/connections/{connection_id}", headers=auth_headers
        ).status_code
        == 200
    )
