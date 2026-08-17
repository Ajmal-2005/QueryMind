"""The four validation gates.

Adversarial safety cases live in `test_adversarial.py`; this file covers the
syntax, schema, and cost gates, and the retryable/hard-reject distinction the
correction loop depends on.
"""

from app.models.connection import Dialect
from app.services.validation.gates import Gate, SchemaIndex, validate

INDEX = SchemaIndex(
    columns_by_table={
        "orders": {"id", "customer_id", "status", "total_amount", "created_at"},
        "customers": {"id", "email", "full_name", "region"},
        "order_items": {"id", "order_id", "product_id", "quantity", "unit_price"},
    }
)


def _v(sql: str, dialect: Dialect = Dialect.SQLITE, max_rows: int = 10_000):
    return validate(sql, dialect, INDEX, max_rows=max_rows)


# ---------------------------------------------------------------- gate 1


def test_valid_query_passes() -> None:
    assert _v("SELECT id FROM orders").ok


def test_unparseable_sql_fails_syntax() -> None:
    result = _v("SELECT FROM WHERE ORDER BY")
    assert not result.ok
    assert result.failure.gate is Gate.SYNTAX


def test_empty_sql_fails_syntax() -> None:
    assert _v("   ").failure.gate is Gate.SYNTAX


def test_syntax_failures_are_retryable() -> None:
    # A malformed query is a mistake the model can fix from the message.
    assert _v("SELECT FROM WHERE").failure.retryable


# ---------------------------------------------------------------- gate 2


def test_unknown_table_fails_schema() -> None:
    result = _v("SELECT id FROM invoices")
    assert not result.ok
    assert result.failure.gate is Gate.SCHEMA
    assert "invoices" in result.failure.message


def test_unknown_column_fails_schema() -> None:
    result = _v("SELECT nonexistent_column FROM orders")
    assert result.failure.gate is Gate.SCHEMA


def test_unknown_qualified_column_fails_schema() -> None:
    result = _v("SELECT o.nonexistent FROM orders o")
    assert result.failure.gate is Gate.SCHEMA
    assert "orders" in result.failure.message


def test_schema_failures_are_retryable() -> None:
    assert _v("SELECT id FROM invoices").failure.retryable


def test_near_miss_gets_a_did_you_mean_hint() -> None:
    # The database's own errors carry these, and they turn out to be strong
    # repair signals - the schema gate produces them in the same shape.
    result = _v("SELECT id FROM custmers")
    assert "customers" in result.failure.message.lower()


def test_near_miss_column_gets_a_hint() -> None:
    result = _v("SELECT o.custome_id FROM orders o")
    assert "customer_id" in result.failure.message


def test_table_aliases_resolve() -> None:
    assert _v(
        "SELECT o.id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id"
    ).ok


def test_unknown_alias_is_caught() -> None:
    result = _v("SELECT x.id FROM orders o")
    assert not result.ok
    assert result.failure.gate is Gate.SCHEMA


def test_cte_name_is_not_treated_as_a_missing_table() -> None:
    # A CTE looks exactly like a table reference but does not exist in the
    # database - the gate has to know the difference.
    assert _v("WITH recent AS (SELECT id FROM orders) SELECT id FROM recent").ok


def test_cte_columns_are_not_checked_against_the_real_schema() -> None:
    # A CTE's output columns are computed, so they cannot be validated.
    assert _v(
        "WITH totals AS (SELECT SUM(total_amount) AS grand FROM orders) "
        "SELECT grand FROM totals"
    ).ok


def test_star_select_is_allowed() -> None:
    assert _v("SELECT * FROM orders").ok


def test_aggregate_expressions_are_allowed() -> None:
    assert _v(
        "SELECT status, COUNT(*) AS n, AVG(total_amount) AS avg_total "
        "FROM orders GROUP BY status"
    ).ok


def test_three_table_join_is_allowed() -> None:
    assert _v(
        "SELECT c.region, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN customers c ON c.id = o.customer_id "
        "GROUP BY c.region"
    ).ok


# ---------------------------------------------------------------- gate 4


def test_missing_limit_is_added() -> None:
    result = _v("SELECT id FROM orders", max_rows=100)
    assert result.ok
    assert "LIMIT 100" in result.sql.upper()
    assert result.limit_applied == 100


def test_limit_under_the_cap_is_left_alone() -> None:
    result = _v("SELECT id FROM orders LIMIT 5", max_rows=100)
    assert result.limit_applied is None
    assert "LIMIT 5" in result.sql.upper()


def test_limit_over_the_cap_is_lowered() -> None:
    result = _v("SELECT id FROM orders LIMIT 999999", max_rows=100)
    assert result.limit_applied == 100
    assert "999999" not in result.sql


def test_applied_limit_is_reported_as_a_warning() -> None:
    # The user must know the result was capped, not silently short.
    result = _v("SELECT id FROM orders", max_rows=100)
    assert any("100" in w for w in result.warnings)


def test_referenced_tables_are_reported() -> None:
    result = _v("SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id")
    assert set(result.tables) == {"orders", "customers"}


# ------------------------------------------------------------- gate order


def test_safety_is_checked_before_schema() -> None:
    # A DROP against a nonexistent table must be rejected as unsafe, not
    # returned as a retryable schema error - otherwise the loop would retry it.
    result = _v("DROP TABLE nonexistent_table")
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


def test_dialect_specific_syntax_parses() -> None:
    # Postgres-only syntax must not be rejected when the dialect is Postgres.
    assert validate(
        "SELECT DATE_TRUNC('month', created_at) AS m FROM orders",
        Dialect.POSTGRES,
        INDEX,
    ).ok


# ------------------------------------------------------- select aliases


def test_ordering_by_a_select_alias_is_allowed() -> None:
    # `SELECT COUNT(*) AS n ... ORDER BY n` is valid SQL and the shape almost
    # every "top N by revenue" question produces. Rejecting it as a missing
    # column would fail a large fraction of legitimate queries.
    assert _v(
        "SELECT region, COUNT(*) AS n FROM customers GROUP BY region ORDER BY n DESC"
    ).ok


def test_grouping_by_a_select_alias_is_allowed() -> None:
    assert _v(
        "SELECT status AS state, COUNT(*) AS n FROM orders "
        "GROUP BY state ORDER BY n DESC"
    ).ok


def test_having_on_a_select_alias_is_allowed() -> None:
    assert _v(
        "SELECT customer_id, SUM(total_amount) AS spend FROM orders "
        "GROUP BY customer_id HAVING spend > 100"
    ).ok


def test_a_genuinely_missing_column_is_still_caught_alongside_aliases() -> None:
    # The alias allowance must not become a blanket amnesty.
    result = _v(
        "SELECT region, COUNT(*) AS n FROM customers "
        "WHERE nonexistent_col = 1 GROUP BY region ORDER BY n"
    )
    assert not result.ok
    assert result.failure.gate is Gate.SCHEMA
