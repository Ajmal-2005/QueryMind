"""Adversarial suite — the proposal's hard requirement.

*Zero successful write operations across the adversarial test suite.*

Every case here is SQL the validation engine must refuse. They are grouped by
attack shape, and each asserts two things: the query was blocked, and it was
blocked as a **hard rejection** rather than a retryable mistake, so the
correction loop never asks the model to produce it again.

The safety gate is only the second line of defence. The first is the
read-only connection, which `test_execution.py` exercises directly.
"""

import pytest

from app.models.connection import Dialect
from app.services.validation.gates import Gate, SchemaIndex, validate

INDEX = SchemaIndex(
    columns_by_table={
        "orders": {"id", "customer_id", "status", "total_amount", "created_at"},
        "customers": {"id", "email", "full_name", "region", "signup_date"},
        "products": {"id", "name", "price", "category_id"},
    }
)


def _reject(sql: str, dialect: Dialect = Dialect.SQLITE):
    return validate(sql, dialect, INDEX)


# --------------------------------------------------------------- writes

WRITE_STATEMENTS = [
    "DELETE FROM orders",
    "DELETE FROM orders WHERE id = 1",
    "DROP TABLE orders",
    "DROP TABLE IF EXISTS customers",
    "TRUNCATE TABLE orders",
    "UPDATE orders SET status = 'completed'",
    "INSERT INTO orders (id, status) VALUES (1, 'x')",
    "ALTER TABLE orders ADD COLUMN hacked TEXT",
    "CREATE TABLE evil (id INTEGER)",
    "CREATE VIEW leak AS SELECT * FROM customers",
    "GRANT ALL ON orders TO PUBLIC",
]


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_write_statements_are_hard_rejected(sql: str) -> None:
    result = _reject(sql)

    assert not result.ok, f"NOT BLOCKED: {sql}"
    assert result.failure.gate is Gate.SAFETY
    # Non-retryable: regenerating a DROP is not a repair.
    assert not result.failure.retryable


# ------------------------------------------------------- piggy-backed writes

PIGGYBACKED = [
    "SELECT * FROM orders; DROP TABLE orders",
    "SELECT 1; DELETE FROM customers",
    "SELECT * FROM orders;DROP TABLE orders;",
    "SELECT * FROM orders;\nUPDATE orders SET status = 'x'",
]


@pytest.mark.parametrize("sql", PIGGYBACKED)
def test_multi_statement_is_hard_rejected(sql: str) -> None:
    # The classic shape: a legitimate SELECT with a write appended.
    result = _reject(sql)

    assert not result.ok, f"NOT BLOCKED: {sql}"
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


# ------------------------------------------------------------ comments

COMMENTED = [
    "SELECT * FROM orders -- DROP TABLE orders",
    "SELECT * FROM orders /* hidden */ WHERE id = 1",
    "SELECT * FROM orders WHERE id = 1 --",
    "SELECT /*! MYSQL_SPECIFIC */ * FROM orders",
]


@pytest.mark.parametrize("sql", COMMENTED)
def test_comments_are_hard_rejected(sql: str) -> None:
    # Comments are how an injected statement terminates the rest of a query.
    result = _reject(sql)

    assert not result.ok, f"NOT BLOCKED: {sql}"
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


# ------------------------------------------------------- dangerous functions

DANGEROUS_FUNCTIONS = [
    "SELECT pg_sleep(10)",
    "SELECT * FROM orders WHERE id = 1 AND pg_sleep(5) IS NOT NULL",
    "SELECT sleep(10)",
    "SELECT benchmark(1000000, md5('x'))",
    "SELECT load_file('/etc/passwd')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT dblink('host=evil.com', 'SELECT 1')",
]


@pytest.mark.parametrize("sql", DANGEROUS_FUNCTIONS)
def test_dangerous_functions_are_hard_rejected(sql: str) -> None:
    result = _reject(sql, Dialect.POSTGRES)

    assert not result.ok, f"NOT BLOCKED: {sql}"
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


# --------------------------------------------------------- system catalogs

SYSTEM_CATALOGS = [
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM information_schema.columns",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM mysql.user",
    "SELECT * FROM performance_schema.threads",
]


@pytest.mark.parametrize("sql", SYSTEM_CATALOGS)
def test_system_catalogs_are_hard_rejected(sql: str) -> None:
    # Catalogs expose credentials and other tenants' object names, and
    # answer no business question.
    result = _reject(sql, Dialect.POSTGRES)

    assert not result.ok, f"NOT BLOCKED: {sql}"
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


# ---------------------------------------------------------------- exfiltration


def test_select_into_is_hard_rejected() -> None:
    result = _reject("SELECT * INTO evil FROM customers", Dialect.POSTGRES)

    assert not result.ok
    assert result.failure.gate is Gate.SAFETY
    assert not result.failure.retryable


def test_write_nested_in_a_cte_is_hard_rejected() -> None:
    # A write hidden inside a WITH clause still parses as a SELECT at the
    # top level, so the check has to look at the whole tree.
    result = _reject(
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        Dialect.POSTGRES,
    )
    assert not result.ok
    assert not result.failure.retryable


def test_write_nested_in_a_subquery_is_hard_rejected() -> None:
    result = _reject(
        "SELECT * FROM (SELECT * FROM orders) t; DROP TABLE orders",
    )
    assert not result.ok
    assert not result.failure.retryable


# ------------------------------------------------------- legitimate queries


LEGITIMATE = [
    "SELECT COUNT(*) FROM orders",
    "SELECT id, email FROM customers WHERE region = 'North'",
    "SELECT c.region, SUM(o.total_amount) FROM orders o "
    "JOIN customers c ON c.id = o.customer_id GROUP BY c.region",
    "WITH monthly AS (SELECT id, total_amount FROM orders) "
    "SELECT COUNT(*) FROM monthly",
    "SELECT * FROM orders ORDER BY created_at DESC LIMIT 10",
    "SELECT status, COUNT(*) FROM orders GROUP BY status HAVING COUNT(*) > 5",
]


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_legitimate_queries_are_not_blocked(sql: str) -> None:
    # A safety layer that rejects real questions is useless. This half of the
    # suite matters as much as the half above.
    result = validate(sql, Dialect.SQLITE, INDEX)
    assert result.ok, (
        f"FALSE POSITIVE: {sql} — {result.failure and result.failure.message}"
    )


def test_no_write_statement_is_ever_retryable() -> None:
    """The loop invariant, asserted over the whole corpus.

    If any of these came back retryable, the correction loop would feed it
    to the model again — turning one blocked write into three attempts.
    """
    for sql in WRITE_STATEMENTS + PIGGYBACKED + SYSTEM_CATALOGS + DANGEROUS_FUNCTIONS:
        result = validate(sql, Dialect.POSTGRES, INDEX)
        assert not result.ok, f"NOT BLOCKED: {sql}"
        assert not result.failure.retryable, f"RETRYABLE: {sql}"
