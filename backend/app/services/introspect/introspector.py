"""Schema extraction.

Reads tables, columns, types, keys, indexes, row estimates, and sample values
from a live database. Everything structural goes through SQLAlchemy's
``Inspector``, which is dialect-agnostic; only row estimates and sampling need
dialect-specific SQL.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.models.connection import Dialect

log = get_logger(__name__)

# A column is "low cardinality" if it has at most this many distinct values;
# only those get sample values attached, since listing 50k customer names
# would blow up the prompt and tell the model nothing.
MAX_DISTINCT_FOR_SAMPLES = 25
SAMPLE_SCAN_LIMIT = 1000

# Only text-ish and small-integer columns are worth sampling.
SAMPLEABLE_TYPES = ("CHAR", "TEXT", "STRING", "ENUM", "BOOL")


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    ordinal: int
    is_nullable: bool = True
    is_pk: bool = False
    is_indexed: bool = False
    fk_target: str | None = None
    sample_values: list[str] | None = None


@dataclass
class ForeignKeyInfo:
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]


@dataclass
class TableInfo:
    name: str
    schema: str | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    row_estimate: int | None = None

    @property
    def primary_key(self) -> list[str]:
        return [c.name for c in self.columns if c.is_pk]


@dataclass
class SchemaSnapshot:
    tables: list[TableInfo]
    dialect: Dialect
    duration_ms: float

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def column_count(self) -> int:
        return sum(len(t.columns) for t in self.tables)

    @property
    def foreign_key_count(self) -> int:
        return sum(len(t.foreign_keys) for t in self.tables)


def _row_estimate(conn, dialect: Dialect, table: str, schema: str | None) -> int | None:
    """Approximate row count.

    Uses the statistics catalog on Postgres and MySQL — an exact COUNT(*) on
    a large production table is exactly the kind of query this system must
    never fire during indexing.
    """
    try:
        if dialect is Dialect.POSTGRES:
            result = conn.execute(
                text(
                    "SELECT reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = :t AND n.nspname = :s"
                ),
                {"t": table, "s": schema or "public"},
            ).scalar()
        elif dialect is Dialect.MYSQL:
            result = conn.execute(
                text(
                    "SELECT TABLE_ROWS FROM information_schema.TABLES "
                    "WHERE TABLE_NAME = :t AND TABLE_SCHEMA = DATABASE()"
                ),
                {"t": table},
            ).scalar()
        else:
            # SQLite has no statistics catalog, but its targets are small.
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
    except SQLAlchemyError:
        return None

    return int(result) if result is not None else None


def _should_sample(column: ColumnInfo) -> bool:
    if column.is_pk or column.fk_target:
        return False
    upper = column.data_type.upper()
    return any(token in upper for token in SAMPLEABLE_TYPES)


def _sample_values(conn, table: str, column: str) -> list[str] | None:
    """Distinct values, but only if there are few enough to be informative."""
    try:
        rows = conn.execute(
            text(
                f'SELECT DISTINCT "{column}" FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL LIMIT :lim'
            ),
            {"lim": MAX_DISTINCT_FOR_SAMPLES + 1},
        ).fetchall()
    except SQLAlchemyError:
        # A sample is a nicety; never fail indexing over one.
        return None

    if len(rows) > MAX_DISTINCT_FOR_SAMPLES:
        return None

    return [str(r[0])[:100] for r in rows]


def introspect(
    engine: Engine, dialect: Dialect, include_samples: bool = True
) -> SchemaSnapshot:
    """Read the full schema of the connected database."""
    started = time.perf_counter()
    inspector = inspect(engine)

    default_schema = inspector.default_schema_name
    table_names = inspector.get_table_names(schema=default_schema)

    tables: list[TableInfo] = []

    with engine.connect() as conn:
        for name in table_names:
            info = TableInfo(name=name, schema=default_schema)

            pk_columns = set(
                inspector.get_pk_constraint(name, schema=default_schema).get(
                    "constrained_columns"
                )
                or []
            )

            indexed_columns: set[str] = set()
            for index in inspector.get_indexes(name, schema=default_schema):
                indexed_columns.update(c for c in index.get("column_names", []) if c)

            fk_map: dict[str, str] = {}
            for fk in inspector.get_foreign_keys(name, schema=default_schema):
                referred = fk.get("referred_table")
                if not referred:
                    continue
                constrained = fk.get("constrained_columns") or []
                referred_cols = fk.get("referred_columns") or []
                info.foreign_keys.append(
                    ForeignKeyInfo(
                        from_table=name,
                        from_columns=list(constrained),
                        to_table=referred,
                        to_columns=list(referred_cols),
                    )
                )
                for local, remote in zip(constrained, referred_cols, strict=False):
                    fk_map[local] = f"{referred}.{remote}"

            for ordinal, col in enumerate(
                inspector.get_columns(name, schema=default_schema)
            ):
                column = ColumnInfo(
                    name=col["name"],
                    data_type=str(col["type"]),
                    ordinal=ordinal,
                    is_nullable=bool(col.get("nullable", True)),
                    is_pk=col["name"] in pk_columns,
                    is_indexed=col["name"] in indexed_columns,
                    fk_target=fk_map.get(col["name"]),
                )
                if include_samples and _should_sample(column):
                    column.sample_values = _sample_values(conn, name, column.name)
                info.columns.append(column)

            info.row_estimate = _row_estimate(conn, dialect, name, default_schema)
            tables.append(info)

    duration = (time.perf_counter() - started) * 1000
    log.info(
        "introspection_complete",
        tables=len(tables),
        duration_ms=round(duration, 1),
    )

    return SchemaSnapshot(tables=tables, dialect=dialect, duration_ms=duration)
