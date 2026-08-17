"""Query explanation (F21).

The value of this feature is that it reads the *parsed statement*, so it
cannot drift from what will actually run - unlike the model's own prose
explanation, which describes what the model meant.
"""

from app.models.connection import Dialect
from app.services.generation.explain import explain

FULL = """
SELECT c.region, SUM(o.total_amount) AS revenue
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'paid'
GROUP BY c.region
HAVING SUM(o.total_amount) > 100
ORDER BY revenue DESC
LIMIT 5
"""


def _clauses(sql: str) -> list[str]:
    return [s.clause for s in explain(sql).steps]


def test_steps_are_in_evaluation_order_not_written_order() -> None:
    """FROM before SELECT - the order that makes a query make sense."""
    assert _clauses(FULL) == [
        "FROM",
        "JOIN",
        "WHERE",
        "GROUP BY",
        "HAVING",
        "SELECT",
        "ORDER BY",
        "LIMIT",
    ]


def test_aggregates_are_named_in_english() -> None:
    step = next(s for s in explain(FULL).steps if s.clause == "SELECT")
    assert "adds up" in step.detail
    assert "as revenue" in step.detail


def test_having_is_distinguished_from_where() -> None:
    step = next(s for s in explain(FULL).steps if s.clause == "HAVING")
    assert "before grouping" in step.detail


def test_join_condition_is_stated() -> None:
    step = next(s for s in explain(FULL).steps if s.clause == "JOIN")
    assert "customers" in step.title
    assert "c.id = o.customer_id" in step.detail


def test_outer_join_says_rows_are_kept() -> None:
    sql = "SELECT c.id FROM customers c LEFT JOIN orders o ON o.customer_id = c.id"
    step = next(s for s in explain(sql).steps if s.clause == "JOIN")
    assert "no match" in step.detail


def test_limit_is_extracted_and_warned_about() -> None:
    explanation = explain(FULL)
    assert explanation.row_limit == 5
    step = next(s for s in explanation.steps if s.clause == "LIMIT")
    assert "different sort order" in step.detail


def test_sort_direction_is_described() -> None:
    step = next(s for s in explain(FULL).steps if s.clause == "ORDER BY")
    assert "highest first" in step.detail


def test_aggregate_query_is_flagged_as_a_summary() -> None:
    explanation = explain(FULL)
    assert explanation.is_aggregate
    assert explanation.aggregates == ["SUM"]
    assert "Summarises" in explanation.summary


def test_plain_select_is_flagged_as_a_listing() -> None:
    explanation = explain("SELECT id, name FROM products LIMIT 10")
    assert not explanation.is_aggregate
    assert "Lists rows" in explanation.summary
    assert explanation.tables == ["products"]


def test_select_star_is_described_as_every_column() -> None:
    step = next(
        s for s in explain("SELECT * FROM products").steps if s.clause == "SELECT"
    )
    assert "every column" in step.detail


def test_unparseable_sql_degrades_instead_of_raising() -> None:
    """An explanation is a reading aid on an answer the user already has."""
    explanation = explain("this is not sql at all ((((")
    assert explanation.parsed is False
    assert explanation.steps == []
    assert "could not be parsed" in explanation.summary


def test_every_dialect_parses() -> None:
    for dialect in (Dialect.SQLITE, Dialect.POSTGRES, Dialect.MYSQL):
        assert explain("SELECT id FROM products LIMIT 1", dialect).parsed


def test_every_step_carries_its_sql_fragment() -> None:
    """The UI highlights the clause each step describes."""
    assert all(s.sql for s in explain(FULL).steps)
