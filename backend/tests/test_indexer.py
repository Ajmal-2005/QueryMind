"""End-to-end schema indexing against the demo database."""

from sqlalchemy import select

from app.models.connection import ConnectionStatus
from app.models.schema_index import EMBEDDING_DIM, SchemaColumn, SchemaTable
from app.services.linking.indexer import index_connection, load_graph


def test_indexing_persists_every_table(db, demo_connection) -> None:
    result = index_connection(db, demo_connection)

    stored = db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == demo_connection.id)
    ).all()

    assert result.tables_indexed == 8
    assert len(stored) == 8


def test_indexing_persists_columns(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    orders = db.scalar(
        select(SchemaTable).where(
            SchemaTable.connection_id == demo_connection.id,
            SchemaTable.table_name == "orders",
        )
    )
    assert {c.column_name for c in orders.columns} == {
        "id",
        "customer_id",
        "status",
        "total_amount",
        "created_at",
    }


def test_columns_are_stored_in_ordinal_order(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    orders = db.scalar(
        select(SchemaTable).where(
            SchemaTable.connection_id == demo_connection.id,
            SchemaTable.table_name == "orders",
        )
    )
    assert [c.ordinal for c in orders.columns] == sorted(
        c.ordinal for c in orders.columns
    )


def test_embeddings_are_stored_with_the_right_width(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    for table in db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == demo_connection.id)
    ):
        assert table.embedding is not None
        assert len(table.embedding) == EMBEDDING_DIM


def test_descriptions_are_stored(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    for table in db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == demo_connection.id)
    ):
        assert table.table_name in table.description


def test_foreign_key_targets_are_persisted(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    customer_id = db.scalar(
        select(SchemaColumn)
        .join(SchemaTable)
        .where(
            SchemaTable.connection_id == demo_connection.id,
            SchemaTable.table_name == "orders",
            SchemaColumn.column_name == "customer_id",
        )
    )
    assert customer_id.fk_target == "customers.id"


def test_sample_values_are_persisted(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    status = db.scalar(
        select(SchemaColumn)
        .join(SchemaTable)
        .where(
            SchemaTable.connection_id == demo_connection.id,
            SchemaTable.table_name == "orders",
            SchemaColumn.column_name == "status",
        )
    )
    assert "completed" in status.sample_values


def test_connection_status_becomes_indexed(db, demo_connection) -> None:
    index_connection(db, demo_connection)

    assert demo_connection.status is ConnectionStatus.INDEXED
    assert demo_connection.last_indexed_at is not None
    assert demo_connection.last_error is None


def test_result_reports_graph_statistics(db, demo_connection) -> None:
    result = index_connection(db, demo_connection)

    assert result.foreign_keys >= 6
    assert result.isolated_tables == 1  # cust_ref_log_v2
    assert result.embedder == "hashing-local"
    assert result.total_ms > 0


def test_reindexing_replaces_rather_than_duplicates(db, demo_connection) -> None:
    index_connection(db, demo_connection)
    first_pass_ids = [
        t.id
        for t in db.scalars(
            select(SchemaTable).where(SchemaTable.connection_id == demo_connection.id)
        )
    ]

    index_connection(db, demo_connection)
    tables = db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == demo_connection.id)
    ).all()

    assert len(tables) == 8
    # Rebuilt wholesale, so a dropped column cannot survive a re-index.
    assert {t.id for t in tables}.isdisjoint(first_pass_ids)

    stale_columns = db.scalars(
        select(SchemaColumn).where(SchemaColumn.table_id.in_(first_pass_ids))
    ).all()
    assert stale_columns == []


def test_graph_rebuilds_from_the_stored_index(db, demo_connection) -> None:
    # Phase 2 retrieval needs the graph without touching the target database.
    index_connection(db, demo_connection)
    graph = load_graph(db, demo_connection.id)

    assert "customers" in graph.neighbors("orders")
    assert "product_suppliers" in graph.expand({"products", "suppliers"})
    assert "cust_ref_log_v2" in graph.isolated_tables


def test_indexing_completes_well_inside_the_milestone_budget(
    db, demo_connection
) -> None:
    # The week-4 gate is a 200-table schema in under 30 s; 8 tables should be
    # a small fraction of that.
    result = index_connection(db, demo_connection)
    assert result.total_ms < 5000
