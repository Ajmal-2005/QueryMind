"""The Phase 4 endpoints: analysis on /query, insight, export, dashboards."""

import pytest
from fastapi.testclient import TestClient

SQL = "SELECT name, price FROM products ORDER BY price DESC LIMIT 10"


@pytest.fixture
def connection_id(client: TestClient, auth_headers: dict, demo_db_path: str) -> str:
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Demo", "dialect": "sqlite", "database": demo_db_path},
    ).json()
    client.post(f"/api/v1/connections/{created['id']}/index", headers=auth_headers)
    return created["id"]


# ------------------------------------------------------------------ analysis


def test_query_response_carries_an_analysis(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query",
        headers=auth_headers,
        json={"connection_id": connection_id, "question": "How many customers?"},
    ).json()

    analysis = body["analysis"]
    assert analysis is not None
    assert analysis["profile"]["row_count"] >= 0
    assert analysis["chart"]["type"] in {
        "line",
        "bar",
        "pie",
        "scatter",
        "kpi",
        "table",
    }
    assert analysis["chart"]["reason"]
    assert "numeric" in analysis["options"]


def test_manual_sql_also_gets_an_analysis(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query/execute",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": SQL},
    ).json()

    assert body["analysis"]["profile"]["column_count"] == 2
    assert body["analysis"]["chart"]["type"] == "bar"


def test_analyze_endpoint_profiles_without_generating(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/query/analyze",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": SQL, "question": "top products"},
    )
    assert response.status_code == 200
    assert response.json()["profile"]["row_count"] == 10


def test_analytics_endpoints_run_the_safety_gates(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    """An export must not be a way around the validation layer."""
    for path in ("/api/v1/query/analyze", "/api/v1/query/insight"):
        response = client.post(
            path,
            headers=auth_headers,
            json={"connection_id": connection_id, "sql": "DROP TABLE customers"},
        )
        assert response.status_code == 400
        assert "safety gate" in response.json()["detail"]

    response = client.post(
        "/api/v1/query/export",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "sql": "DELETE FROM customers",
            "format": "csv",
        },
    )
    assert response.status_code == 400


# ------------------------------------------------------------------- insight


def test_insight_returns_a_written_summary(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    body = client.post(
        "/api/v1/query/insight",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": SQL, "question": "top products"},
    ).json()

    assert body["headline"]
    assert body["summary"]
    # No API key in tests, so the template narrator answers — and says so.
    assert body["model"] == "template"


def test_offline_narration_reports_no_masking_because_nothing_left_the_box(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    """Masking is a property of the outbound path, not of the columns.

    With no API key the template narrator answers, no data is sent anywhere,
    and so nothing is masked. Reporting masked columns here would claim a
    protection that was never exercised. The masked-in-transit case is covered
    against a scripted provider in test_narrative.py.
    """
    body = client.post(
        "/api/v1/query/insight",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "sql": "SELECT email, full_name FROM customers LIMIT 5",
            "question": "who are our customers",
        },
    ).json()

    assert body["model"] == "template"
    assert body["masked_columns"] == []


# -------------------------------------------------------------------- export


@pytest.mark.parametrize(
    "fmt,signature",
    [
        ("csv", b"\xef\xbb\xbf"),
        ("json", b"["),
        ("xlsx", b"PK"),
        ("pdf", b"%PDF"),
    ],
)
def test_export_returns_a_file_of_the_right_type(
    client: TestClient,
    auth_headers: dict,
    connection_id: str,
    fmt: str,
    signature: bytes,
) -> None:
    response = client.post(
        "/api/v1/query/export",
        headers=auth_headers,
        json={
            "connection_id": connection_id,
            "sql": SQL,
            "format": fmt,
            "title": "Top products",
        },
    )

    assert response.status_code == 200
    assert response.content.startswith(signature)
    assert "attachment" in response.headers["content-disposition"]
    assert "Top-products" in response.headers["content-disposition"]


def test_csv_export_contains_the_rows(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    response = client.post(
        "/api/v1/query/export",
        headers=auth_headers,
        json={"connection_id": connection_id, "sql": SQL, "format": "csv"},
    )
    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "name,price"
    assert len(text.strip().splitlines()) == 11


# ---------------------------------------------------------------- dashboards


def test_dashboard_lifecycle(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Sales"}
    )
    assert created.status_code == 201
    dashboard_id = created.json()["id"]

    tile = client.post(
        f"/api/v1/dashboards/{dashboard_id}/tiles",
        headers=auth_headers,
        json={
            "title": "Top products",
            "connection_id": connection_id,
            "sql": SQL,
            "question": "top products",
        },
    )
    assert tile.status_code == 201
    tile_id = tile.json()["id"]

    detail = client.get(
        f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers
    ).json()
    assert detail["tile_count"] == 1
    assert detail["tiles"][0]["connection_name"] == "Demo"

    refreshed = client.post(
        f"/api/v1/dashboards/{dashboard_id}/refresh", headers=auth_headers
    ).json()
    assert len(refreshed["tiles"]) == 1
    assert refreshed["tiles"][0]["ok"] is True
    assert refreshed["tiles"][0]["result"]["row_count"] == 10
    assert refreshed["tiles"][0]["analysis"]["chart"]["type"] == "bar"

    assert (
        client.delete(
            f"/api/v1/dashboards/{dashboard_id}/tiles/{tile_id}", headers=auth_headers
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers
        ).status_code
        == 404
    )


def test_pinning_unsafe_sql_is_refused(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    dashboard_id = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "D"}
    ).json()["id"]

    response = client.post(
        f"/api/v1/dashboards/{dashboard_id}/tiles",
        headers=auth_headers,
        json={
            "title": "bad",
            "connection_id": connection_id,
            "sql": "DROP TABLE customers",
        },
    )
    assert response.status_code == 400
    assert "safety gate" in response.json()["detail"]


def test_a_dashboard_is_private_to_its_owner(
    client: TestClient, auth_headers: dict, connection_id: str
) -> None:
    dashboard_id = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Private"}
    ).json()["id"]

    other = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "correct-horse-battery"},
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert (
        client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).status_code
        == 404
    )
    assert client.get("/api/v1/dashboards", headers=headers).json() == []


def test_one_broken_tile_does_not_fail_the_whole_refresh(
    client: TestClient, auth_headers: dict, connection_id: str, demo_db_path: str
) -> None:
    """A dashboard with one dead tile still shows the working ones."""
    doomed = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={"name": "Doomed", "dialect": "sqlite", "database": demo_db_path},
    ).json()["id"]
    client.post(f"/api/v1/connections/{doomed}/index", headers=auth_headers)

    dashboard_id = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Mixed"}
    ).json()["id"]

    for title, conn in (("Good", connection_id), ("Orphan", doomed)):
        client.post(
            f"/api/v1/dashboards/{dashboard_id}/tiles",
            headers=auth_headers,
            json={"title": title, "connection_id": conn, "sql": SQL},
        )

    # The database a tile was built against goes away underneath it.
    client.delete(f"/api/v1/connections/{doomed}", headers=auth_headers)

    tiles = client.post(
        f"/api/v1/dashboards/{dashboard_id}/refresh", headers=auth_headers
    ).json()["tiles"]

    assert len(tiles) == 2
    assert sum(1 for t in tiles if t["ok"]) == 1
    assert next(t for t in tiles if not t["ok"])["error"]


def test_cache_status_is_reported(client: TestClient, auth_headers: dict) -> None:
    body = client.get("/api/v1/query/cache", headers=auth_headers).json()
    assert body["backend"] in {"memory", "redis", "disabled"}
    assert body["ttl_seconds"] > 0
