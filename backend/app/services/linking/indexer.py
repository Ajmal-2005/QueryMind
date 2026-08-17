"""Schema indexing.

Introspect a connected database, describe each table, embed the descriptions,
and persist the result. This is what turns a 400-table schema into something
retrievable.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.connection import Connection, ConnectionStatus
from app.models.schema_index import SchemaColumn, SchemaTable
from app.services.connection.manager import create_target_engine
from app.services.introspect.describe import describe_table
from app.services.introspect.introspector import SchemaSnapshot, introspect
from app.services.linking.embeddings import Embedder, get_embedder
from app.services.linking.graph import ForeignKeyGraph

log = get_logger(__name__)


@dataclass
class IndexResult:
    connection_id: str
    tables_indexed: int
    columns_indexed: int
    foreign_keys: int
    isolated_tables: int
    embedder: str
    introspection_ms: float
    embedding_ms: float
    total_ms: float


def index_connection(
    db: Session,
    connection: Connection,
    embedder: Embedder | None = None,
) -> IndexResult:
    """Build the searchable schema index for one connection.

    Re-indexing replaces the previous index wholesale rather than merging -
    a dropped column must disappear, and reconciling is more code and more
    ways to be subtly wrong than rebuilding.
    """
    started = time.perf_counter()
    embedder = embedder or get_embedder()

    connection.status = ConnectionStatus.INDEXING
    db.commit()

    engine = create_target_engine(connection)
    try:
        snapshot = introspect(engine, connection.dialect)
    finally:
        engine.dispose()

    descriptions = [describe_table(t) for t in snapshot.tables]

    embed_started = time.perf_counter()
    vectors = embedder.embed(descriptions) if descriptions else []
    embedding_ms = (time.perf_counter() - embed_started) * 1000

    _replace_index(db, connection, snapshot, descriptions, vectors)

    graph = ForeignKeyGraph.from_tables(snapshot.tables)

    connection.status = ConnectionStatus.INDEXED
    connection.last_indexed_at = datetime.now(timezone.utc)
    connection.last_error = None
    db.commit()

    total_ms = (time.perf_counter() - started) * 1000
    result = IndexResult(
        connection_id=connection.id,
        tables_indexed=snapshot.table_count,
        columns_indexed=snapshot.column_count,
        foreign_keys=snapshot.foreign_key_count,
        isolated_tables=len(graph.isolated_tables),
        embedder=embedder.name,
        introspection_ms=round(snapshot.duration_ms, 1),
        embedding_ms=round(embedding_ms, 1),
        total_ms=round(total_ms, 1),
    )

    log.info("schema_indexed", **result.__dict__)
    return result


def _replace_index(
    db: Session,
    connection: Connection,
    snapshot: SchemaSnapshot,
    descriptions: list[str],
    vectors: list[list[float]],
) -> None:
    # Columns go via the table cascade, but SQLite in older versions does not
    # always enforce it, so delete explicitly and in dependency order.
    existing_ids = list(
        db.scalars(
            select(SchemaTable.id).where(SchemaTable.connection_id == connection.id)
        )
    )
    if existing_ids:
        db.execute(delete(SchemaColumn).where(SchemaColumn.table_id.in_(existing_ids)))
        db.execute(delete(SchemaTable).where(SchemaTable.id.in_(existing_ids)))
        db.flush()

    for table, description, vector in zip(
        snapshot.tables,
        descriptions,
        vectors or [None] * len(snapshot.tables),
        strict=True,
    ):
        row = SchemaTable(
            connection_id=connection.id,
            table_name=table.name,
            schema_name=table.schema,
            description=description,
            embedding=vector,
            row_estimate=table.row_estimate,
        )
        db.add(row)
        db.flush()

        for column in table.columns:
            db.add(
                SchemaColumn(
                    table_id=row.id,
                    column_name=column.name,
                    data_type=column.data_type,
                    ordinal=column.ordinal,
                    is_nullable=column.is_nullable,
                    is_pk=column.is_pk,
                    is_indexed=column.is_indexed,
                    fk_target=column.fk_target,
                    sample_values=column.sample_values,
                )
            )

    db.flush()


def mark_index_failed(db: Session, connection: Connection, error: str) -> None:
    connection.status = ConnectionStatus.FAILED
    connection.last_error = error[:1000]
    db.commit()


def load_graph(db: Session, connection_id: str) -> ForeignKeyGraph:
    """Rebuild the FK graph from the stored index.

    Phase 2's retrieval needs this without re-introspecting the database.
    """
    tables = list(
        db.scalars(
            select(SchemaTable).where(SchemaTable.connection_id == connection_id)
        )
    )

    graph = ForeignKeyGraph()
    for table in tables:
        graph.adjacency.setdefault(table.table_name, set())

    known = set(graph.adjacency)
    for table in tables:
        for column in table.columns:
            if not column.fk_target:
                continue
            target_table = column.fk_target.split(".")[0]
            if target_table not in known:
                continue
            graph.adjacency[table.table_name].add(target_table)
            graph.adjacency[target_table].add(table.table_name)

    return graph
