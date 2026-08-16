"""Sandboxed execution against the real demo database.

The read-only tests here are the *first* line of defence — independent of the
validation gates, which `test_adversarial.py` covers. They answer a different
question: if a write somehow got past every gate, would the database still
refuse it?
"""

import pytest

from app.services.execution.runner import execute, explain


def test_select_returns_rows(demo_connection) -> None:
    result = execute(demo_connection, "SELECT id, email FROM customers LIMIT 5")

    assert result.ok
    assert result.columns == ["id", "email"]
    assert result.row_count == 5


def test_aggregate_returns_a_scalar(demo_connection) -> None:
    result = execute(demo_connection, "SELECT COUNT(*) AS n FROM orders")

    assert result.ok
    assert result.rows[0][0] == 2000


def test_join_executes(demo_connection) -> None:
    result = execute(
        demo_connection,
        "SELECT c.region, COUNT(*) AS n FROM orders o "
        "JOIN customers c ON c.id = o.customer_id GROUP BY c.region",
    )
    assert result.ok
    assert result.row_count == 5


def test_empty_result_is_a_success_not_a_failure(demo_connection) -> None:
    result = execute(
        demo_connection, "SELECT id FROM customers WHERE region = 'Atlantis'"
    )
    assert result.ok
    assert result.is_empty


def test_row_cap_truncates_and_says_so(demo_connection) -> None:
    # A short result must never be silently short.
    result = execute(demo_connection, "SELECT id FROM orders", max_rows=10)

    assert result.ok
    assert result.row_count == 10
    assert result.truncated


def test_result_under_the_cap_is_not_marked_truncated(demo_connection) -> None:
    result = execute(demo_connection, "SELECT id FROM orders LIMIT 3", max_rows=10)
    assert not result.truncated


def test_duration_is_recorded(demo_connection) -> None:
    assert execute(demo_connection, "SELECT 1").duration_ms > 0


# ------------------------------------------------------------ read-only

WRITES = [
    "DELETE FROM orders",
    "UPDATE orders SET status = 'hacked'",
    "INSERT INTO customers (id, email, full_name, region, signup_date) "
    "VALUES (99999, 'x@y.z', 'x', 'North', '2024-01-01')",
    "DROP TABLE orders",
    "CREATE TABLE evil (id INTEGER)",
]


@pytest.mark.parametrize("sql", WRITES)
def test_the_database_itself_refuses_writes(demo_connection, sql: str) -> None:
    """Defence in depth: bypass the gates entirely and go straight to the DB.

    This is what makes a prompt-injection attack non-fatal rather than merely
    unlikely — the connection has no write capability to abuse.
    """
    result = execute(demo_connection, sql)

    assert not result.ok, f"WRITE SUCCEEDED: {sql}"
    assert "readonly" in result.error.lower() or "read-only" in result.error.lower()


def test_data_is_unchanged_after_attempted_writes(demo_connection) -> None:
    before = execute(demo_connection, "SELECT COUNT(*) FROM orders").rows[0][0]

    for sql in WRITES:
        execute(demo_connection, sql)

    after = execute(demo_connection, "SELECT COUNT(*) FROM orders").rows[0][0]
    assert after == before == 2000


# ------------------------------------------------------------- errors


def test_unknown_table_returns_an_error_not_an_exception(demo_connection) -> None:
    result = execute(demo_connection, "SELECT * FROM nonexistent")

    assert not result.ok
    assert "nonexistent" in result.error


def test_error_message_is_the_databases_own_sentence(demo_connection) -> None:
    # The correction loop reads this. SQLAlchemy's wrapper text and the
    # echoed SQL dilute the signal, so they are stripped.
    result = execute(demo_connection, "SELECT nonexistent_col FROM orders")

    assert "no such column" in result.error.lower()
    assert "[SQL:" not in result.error
    assert "Background on this error" not in result.error


def test_syntax_error_is_reported_cleanly(demo_connection) -> None:
    result = execute(demo_connection, "SELECT FROM WHERE")
    assert not result.ok
    assert result.error


# ------------------------------------------------------------- explain


def test_explain_returns_a_plan(demo_connection) -> None:
    plan = explain(demo_connection, "SELECT * FROM orders WHERE customer_id = 1")
    assert plan
    assert "orders" in plan.lower()


def test_explain_returns_none_for_bad_sql(demo_connection) -> None:
    # Advisory only — a plan that cannot be fetched must not block a query.
    assert explain(demo_connection, "SELECT FROM WHERE") is None
