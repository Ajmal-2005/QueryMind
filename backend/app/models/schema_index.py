"""The indexed schema of a connected database.

One row per table and per column, plus a natural-language description and an
embedding for each table. This is what schema linking searches at query time
instead of stuffing a 400-table schema into a prompt.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Matches text-embedding-3-small. The local development embedder produces the
# same width so switching providers never changes the stored schema.
EMBEDDING_DIM = 1536


def _embedding_column():
    """Portable embedding storage.

    On Postgres this is a real ``vector`` column that pgvector can index and
    search with ``<=>``. Everywhere else it degrades to JSON and similarity
    is computed in Python - fine for the hundreds of tables a schema has,
    and it keeps local development free of a Postgres dependency.
    """
    try:
        from pgvector.sqlalchemy import Vector

        return JSON().with_variant(Vector(EMBEDDING_DIM), "postgresql")
    except ImportError:  # pragma: no cover - pgvector is a declared dependency
        return JSON()


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchemaTable(Base):
    __tablename__ = "schema_tables"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "schema_name", "table_name", name="uq_schema_table"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), index=True)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The text that gets embedded: what the table holds and how it joins.
    description: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list | None] = mapped_column(_embedding_column(), nullable=True)

    row_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    columns: Mapped[list["SchemaColumn"]] = relationship(
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="SchemaColumn.ordinal",
    )

    @property
    def qualified_name(self) -> str:
        return (
            f"{self.schema_name}.{self.table_name}"
            if self.schema_name
            else self.table_name
        )


class SchemaColumn(Base):
    __tablename__ = "schema_columns"
    __table_args__ = (
        UniqueConstraint("table_id", "column_name", name="uq_schema_column"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    table_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schema_tables.id", ondelete="CASCADE"), index=True
    )
    column_name: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    is_nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_pk: Mapped[bool] = mapped_column(Boolean, default=False)
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False)

    # "other_table.other_column" when this column is a foreign key.
    fk_target: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # A handful of distinct values, for low-cardinality columns only. Lets the
    # model see that status is 'completed'/'pending' rather than guessing.
    sample_values: Mapped[list | None] = mapped_column(JSON, nullable=True)

    table: Mapped[SchemaTable] = relationship(back_populates="columns")
