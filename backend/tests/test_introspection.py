"""Schema extraction against the real demo database.

These run against an actual seeded SQLite file rather than mocks, so they
exercise the same SQLAlchemy Inspector path that Postgres and MySQL use.
"""

from app.models.connection import Dialect
from app.services.introspect.introspector import introspect

EXPECTED_TABLES = {
    "categories",
    "products",
    "customers",
    "orders",
    "order_items",
    "suppliers",
    "product_suppliers",
    "cust_ref_log_v2",
}


def test_every_table_is_discovered(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    assert {t.name for t in snapshot.tables} == EXPECTED_TABLES


def test_columns_are_extracted_with_types(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    orders = next(t for t in snapshot.tables if t.name == "orders")

    names = {c.name for c in orders.columns}
    assert names == {"id", "customer_id", "status", "total_amount", "created_at"}
    assert all(c.data_type for c in orders.columns)


def test_primary_keys_are_identified(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    products = next(t for t in snapshot.tables if t.name == "products")

    assert products.primary_key == ["id"]


def test_composite_primary_key_is_captured(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    junction = next(t for t in snapshot.tables if t.name == "product_suppliers")

    assert set(junction.primary_key) == {"product_id", "supplier_id"}


def test_foreign_keys_are_reconstructed(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    order_items = next(t for t in snapshot.tables if t.name == "order_items")

    targets = {fk.to_table for fk in order_items.foreign_keys}
    assert targets == {"orders", "products"}


def test_fk_target_is_recorded_on_the_column(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    orders = next(t for t in snapshot.tables if t.name == "orders")
    customer_id = next(c for c in orders.columns if c.name == "customer_id")

    assert customer_id.fk_target == "customers.id"


def test_self_referencing_foreign_key_is_handled(demo_engine) -> None:
    # categories.parent_id points back at categories.
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    categories = next(t for t in snapshot.tables if t.name == "categories")
    parent = next(c for c in categories.columns if c.name == "parent_id")

    assert parent.fk_target == "categories.id"


def test_indexes_are_detected(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    orders = next(t for t in snapshot.tables if t.name == "orders")
    customer_id = next(c for c in orders.columns if c.name == "customer_id")

    assert customer_id.is_indexed


def test_nullability_is_recorded(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    categories = next(t for t in snapshot.tables if t.name == "categories")

    assert next(c for c in categories.columns if c.name == "name").is_nullable is False
    assert next(c for c in categories.columns if c.name == "parent_id").is_nullable


def test_row_estimates_are_populated(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    orders = next(t for t in snapshot.tables if t.name == "orders")

    assert orders.row_estimate == 2000


def test_low_cardinality_column_gets_sample_values(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    orders = next(t for t in snapshot.tables if t.name == "orders")
    status = next(c for c in orders.columns if c.name == "status")

    assert status.sample_values is not None
    assert set(status.sample_values) == {
        "completed",
        "pending",
        "cancelled",
        "refunded",
    }


def test_high_cardinality_column_is_not_sampled(demo_engine) -> None:
    # 500 distinct emails would bloat the prompt and teach the model nothing.
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    customers = next(t for t in snapshot.tables if t.name == "customers")
    email = next(c for c in customers.columns if c.name == "email")

    assert email.sample_values is None


def test_primary_keys_are_never_sampled(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)
    for table in snapshot.tables:
        for column in table.columns:
            if column.is_pk:
                assert column.sample_values is None


def test_samples_can_be_disabled(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE, include_samples=False)

    assert all(c.sample_values is None for t in snapshot.tables for c in t.columns)


def test_snapshot_counts_are_consistent(demo_engine) -> None:
    snapshot = introspect(demo_engine, Dialect.SQLITE)

    assert snapshot.table_count == len(EXPECTED_TABLES)
    assert snapshot.column_count == sum(len(t.columns) for t in snapshot.tables)
    assert snapshot.foreign_key_count >= 6
    assert snapshot.duration_ms > 0
