"""Table description generation.

The description is the retrieval surface, so what it does and does not
contain determines whether schema linking can work at all.
"""

from app.models.connection import Dialect
from app.services.introspect.describe import describe_table, humanize
from app.services.introspect.introspector import introspect


def test_humanize_splits_snake_case() -> None:
    assert humanize("customer_name") == "customer name"


def test_humanize_splits_camel_case() -> None:
    assert humanize("customerName") == "customer name"


def test_humanize_expands_known_abbreviations() -> None:
    # The whole point: 'cust_ref_id_v2' must reach the words a user types.
    assert humanize("cust_ref_id_v2") == "customer reference identifier v2"


def test_humanize_handles_a_plain_word() -> None:
    assert humanize("orders") == "orders"


def _table(engine, name: str):
    snapshot = introspect(engine, Dialect.SQLITE)
    return next(t for t in snapshot.tables if t.name == name)


def test_description_names_the_table(demo_engine) -> None:
    description = describe_table(_table(demo_engine, "orders"))
    assert "`orders`" in description


def test_description_states_the_primary_key(demo_engine) -> None:
    description = describe_table(_table(demo_engine, "orders"))
    assert "Primary key: id" in description


def test_description_lists_join_paths(demo_engine) -> None:
    # Without this the model has to guess how tables connect.
    description = describe_table(_table(demo_engine, "order_items"))

    assert "Joins to `orders`" in description
    assert "Joins to `products`" in description


def test_description_includes_low_cardinality_values(demo_engine) -> None:
    description = describe_table(_table(demo_engine, "orders"))

    assert "Known values" in description
    assert "completed" in description


def test_description_includes_row_estimate(demo_engine) -> None:
    description = describe_table(_table(demo_engine, "orders"))
    assert "2,000 rows" in description


def test_cryptic_table_name_is_expanded_into_words(demo_engine) -> None:
    description = describe_table(_table(demo_engine, "cust_ref_log_v2"))

    assert "customer" in description.lower()
    assert "reference" in description.lower()


def test_description_does_not_leak_high_cardinality_data(demo_engine) -> None:
    # Customer emails are real data; they must not end up in a prompt.
    description = describe_table(_table(demo_engine, "customers"))
    assert "customer0001@example.com" not in description


def test_every_demo_table_produces_a_substantial_description(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)

    for table in snapshot.tables:
        description = describe_table(table)
        assert len(description) > 50, table.name
        assert table.name in description
