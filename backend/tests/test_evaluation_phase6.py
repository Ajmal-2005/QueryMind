"""The Phase 6 evaluation machinery: gold parsing, taxonomy, ablations."""

import pytest

from evaluation import ablations, taxonomy
from evaluation.datasets import BenchmarkExample
from evaluation.gold import gold_tables, parse_gold
from evaluation.metrics import EvalRecord

# ------------------------------------------------------------------- gold


def test_joined_tables_are_all_found() -> None:
    """A regex over FROM would find one table and inflate recall."""
    sql = """
    SELECT c.region, SUM(o.total_amount)
    FROM orders o
    JOIN customers c ON c.id = o.customer_id
    JOIN order_items i ON i.order_id = o.id
    GROUP BY c.region
    """
    assert sorted(gold_tables(sql)) == ["customers", "order_items", "orders"]


def test_cte_names_are_not_counted_as_tables() -> None:
    """A CTE is a name bound by the query, not a table it reads."""
    sql = """
    WITH recent AS (SELECT * FROM orders)
    SELECT COUNT(*) FROM recent
    """
    assert gold_tables(sql) == ["orders"]


def test_subquery_tables_are_found() -> None:
    sql = "SELECT id FROM customers WHERE id IN (SELECT customer_id FROM orders)"
    assert sorted(gold_tables(sql)) == ["customers", "orders"]


def test_aliases_do_not_become_tables() -> None:
    sql = "SELECT o.id FROM orders o"
    assert gold_tables(sql) == ["orders"]


def test_order_by_makes_row_order_part_of_the_answer() -> None:
    assert parse_gold("SELECT id FROM orders ORDER BY id").order_matters
    assert not parse_gold("SELECT id FROM orders").order_matters


def test_unparseable_gold_yields_no_tables_rather_than_raising() -> None:
    gold = parse_gold("not sql at all ((((")
    assert gold.parsed is False
    assert gold.tables == []


# --------------------------------------------------------------- taxonomy


def _record(**kwargs) -> EvalRecord:
    base = {
        "question_id": "q",
        "question": "a question",
        "db_id": "ecommerce",
        "gold_sql": "SELECT region, SUM(total_amount) FROM orders GROUP BY region",
        "predicted_sql": (
            "SELECT region, SUM(total_amount) FROM orders GROUP BY region"
        ),
        "correct": False,
        "executed": True,
    }
    return EvalRecord(**{**base, **kwargs})


def test_a_correct_answer_has_nothing_to_classify() -> None:
    assert taxonomy.classify(_record(correct=True)) is None


def test_no_sql_at_all_is_not_generated() -> None:
    assert taxonomy.classify(_record(predicted_sql=None)) == "not_generated"


def test_a_safety_rejection_is_named_as_one() -> None:
    record = _record(
        predicted_sql="DROP TABLE orders",
        error="Blocked by the safety gate: writes are forbidden",
        executed=False,
    )
    assert taxonomy.classify(record) == "rejected_unsafe"


def test_wrong_table_outranks_wrong_column() -> None:
    """A query on the wrong table also has the wrong columns.

    Reporting that as a column error sends you looking in the wrong place.
    """
    record = _record(
        predicted_sql="SELECT region, SUM(total_amount) FROM customers GROUP BY region"
    )
    assert taxonomy.classify(record) == "wrong_table"


def test_a_different_aggregate_is_caught() -> None:
    record = _record(
        predicted_sql="SELECT region, AVG(total_amount) FROM orders GROUP BY region"
    )
    assert taxonomy.classify(record) == "wrong_aggregation"


def test_a_missing_filter_is_caught() -> None:
    record = _record(
        gold_sql=(
            "SELECT region, SUM(total_amount) FROM orders "
            "WHERE status = 'paid' GROUP BY region"
        )
    )
    assert taxonomy.classify(record) == "wrong_filter"


def test_a_different_limit_is_an_ordering_error() -> None:
    record = _record(
        gold_sql="SELECT id FROM orders ORDER BY id LIMIT 5",
        predicted_sql="SELECT id FROM orders ORDER BY id LIMIT 10",
    )
    assert taxonomy.classify(record) == "wrong_ordering"


def test_structurally_identical_but_wrong_rows_is_its_own_category() -> None:
    record = _record()
    assert taxonomy.classify(record) == "wrong_result"


def test_unparseable_prediction_is_invalid_sql() -> None:
    assert taxonomy.classify(_record(predicted_sql="SELECT FROM (((")) == "invalid_sql"


def test_every_category_has_a_description() -> None:
    for category in taxonomy.CATEGORIES:
        assert taxonomy.DESCRIPTIONS.get(category)


def test_tally_orders_by_frequency() -> None:
    records = [
        _record(error_category="wrong_table"),
        _record(error_category="wrong_table"),
        _record(error_category="wrong_join"),
    ]
    assert list(taxonomy.tally(records)) == ["wrong_table", "wrong_join"]


# -------------------------------------------------------------- ablations


@pytest.fixture
def indexed_bench(db, demo_connection):
    """A Bench-shaped object over the shared test fixtures.

    Cheaper than `evaluation.harness.bench`, which builds its own database.
    """
    from app.services.linking.indexer import index_connection
    from evaluation.harness import Bench

    result = index_connection(db, demo_connection)
    return Bench(
        db=db,
        connection=demo_connection,
        user_id=demo_connection.user_id,
        tables_indexed=result.tables_indexed,
        embedder=result.embedder,
    )


EXAMPLES = [
    BenchmarkExample(
        question_id="e1",
        question="How many customers do we have?",
        db_id="ecommerce",
        gold_sql="SELECT COUNT(*) FROM customers",
    ),
    BenchmarkExample(
        question_id="e2",
        question="Revenue by region",
        db_id="ecommerce",
        gold_sql=(
            "SELECT c.region, SUM(o.total_amount) FROM orders o "
            "JOIN customers c ON c.id = o.customer_id GROUP BY c.region"
        ),
    ),
]


def test_an_arm_reports_recall_and_what_it_cost(indexed_bench) -> None:
    result = ablations.run_arm(indexed_bench, ablations.Arm("default", "d"), EXAMPLES)

    assert result.questions == 2
    assert 0.0 <= result.recall <= 1.0
    assert result.mean_tables_retrieved > 0
    # Coverage is what stops recall being read as a triumph on a small schema.
    assert 0.0 < result.coverage <= 1.0


def test_a_tiny_candidate_set_loses_recall(indexed_bench) -> None:
    """The arm that actually discriminates on a small schema."""
    wide = ablations.run_arm(indexed_bench, ablations.Arm("k6", "d"), EXAMPLES)
    narrow = ablations.run_arm(
        indexed_bench, ablations.Arm("k1", "d", top_k=1, hops=0), EXAMPLES
    )
    assert narrow.recall <= wide.recall
    assert narrow.mean_tables_retrieved < wide.mean_tables_retrieved


def test_expansion_never_reduces_recall(indexed_bench) -> None:
    """Adding foreign-key neighbours can only add tables."""
    with_fk = ablations.run_arm(indexed_bench, ablations.Arm("fk", "d"), EXAMPLES)
    without = ablations.run_arm(
        indexed_bench, ablations.Arm("no fk", "d", hops=0), EXAMPLES
    )
    assert with_fk.recall >= without.recall


def test_a_saturated_schema_is_reported_as_not_discriminative(indexed_bench) -> None:
    """The guard that stops the whole study being over-read.

    On an 8-table schema the default configuration retrieves nearly all of it,
    every arm scores near 100%, and the table looks like a triumph while
    measuring almost nothing.
    """
    results = ablations.run(indexed_bench, EXAMPLES)
    ok, why = ablations.discriminates(results, indexed_bench.tables_indexed)

    assert ok is False
    assert "small" in why or "close" in why


def test_arms_are_reported_against_the_shipping_configuration(indexed_bench) -> None:
    results = ablations.run(indexed_bench, EXAMPLES)
    assert results[0].name == "hybrid+fk"
    assert ablations.as_table(results).splitlines()[0].strip().startswith("arm")
