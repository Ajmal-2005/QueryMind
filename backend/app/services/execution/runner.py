"""Sandboxed query execution.

The last line of defence, and deliberately independent of everything above
it. The validation gates can be bypassed by a bug; the controls here are
enforced by the database itself:

- Postgres and MySQL sessions are opened read-only and given a statement
  timeout the server enforces.
- SQLite files are opened through a `mode=ro` URI, so the driver refuses
  writes outright.
- Rows are capped by reading one more than the limit and stopping.

Nothing in this module trusts the SQL it is handed.
"""

import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.connection import Connection, Dialect
from app.services.connection.manager import create_target_engine

log = get_logger(__name__)


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)

    row_count: int = 0
    truncated: bool = False
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.ok and self.row_count == 0


def _apply_session_guards(conn, dialect: Dialect, timeout_seconds: int) -> None:
    """Ask the server to enforce read-only and a statement timeout.

    Best effort by design: if a guard cannot be set the query still runs
    under the other controls, and a failure here must not look like a query
    failure to the user.
    """
    try:
        if dialect is Dialect.POSTGRES:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(
                text(f"SET LOCAL statement_timeout = {timeout_seconds * 1000}")
            )
        elif dialect is Dialect.MYSQL:
            conn.execute(
                text(f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}")
            )
    except SQLAlchemyError as exc:
        log.warning("session_guard_failed", dialect=dialect.value, error=str(exc)[:120])


def _install_sqlite_timeout(conn, deadline: float) -> None:
    """Interrupt a long-running SQLite query.

    SQLite has no server-side statement timeout, so the driver's progress
    handler is the only place to enforce one. It fires every N VM steps;
    returning non-zero aborts the statement.
    """
    raw = getattr(conn.connection, "dbapi_connection", None) or conn.connection

    def _abort_if_expired() -> int:
        return 1 if time.monotonic() > deadline else 0

    try:
        raw.set_progress_handler(_abort_if_expired, 10_000)
    except AttributeError:
        log.warning("sqlite_timeout_unavailable")


def _clear_sqlite_timeout(conn) -> None:
    raw = getattr(conn.connection, "dbapi_connection", None) or conn.connection
    # Nothing to clear if the driver never accepted a handler in the first
    # place — the install path already logged that.
    with contextlib.suppress(AttributeError):
        raw.set_progress_handler(None, 0)


def execute(
    connection: Connection,
    sql: str,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
    engine: Engine | None = None,
) -> ExecutionResult:
    """Run a validated query against the target database.

    Never raises: a failed query is an expected outcome that the correction
    loop reads, not an exception for the API to turn into a 500.
    """
    max_rows = max_rows or settings.MAX_RESULT_ROWS
    timeout_seconds = timeout_seconds or settings.QUERY_TIMEOUT_SECONDS

    owns_engine = engine is None
    engine = engine or create_target_engine(connection)
    started = time.perf_counter()

    try:
        with engine.connect() as conn:
            _apply_session_guards(conn, connection.dialect, timeout_seconds)

            if connection.dialect is Dialect.SQLITE:
                _install_sqlite_timeout(conn, time.monotonic() + timeout_seconds)

            try:
                cursor = conn.execute(text(sql))
                columns = list(cursor.keys())
                # Read one extra row so truncation can be reported honestly
                # rather than silently returning a short result.
                fetched = cursor.fetchmany(max_rows + 1)
            finally:
                if connection.dialect is Dialect.SQLITE:
                    _clear_sqlite_timeout(conn)

        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        elapsed = (time.perf_counter() - started) * 1000

        log.info(
            "query_executed",
            rows=len(rows),
            truncated=truncated,
            duration_ms=round(elapsed, 1),
        )
        return ExecutionResult(
            ok=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=elapsed,
        )

    except SQLAlchemyError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        message = _clean_error(exc)
        log.warning("query_failed", error=message[:200])
        return ExecutionResult(ok=False, error=message, duration_ms=elapsed)

    finally:
        if owns_engine:
            engine.dispose()


def _clean_error(exc: SQLAlchemyError) -> str:
    """Reduce a driver exception to the message worth feeding back.

    SQLAlchemy wraps the driver error in its own text plus the offending SQL
    and a docs link. The database's own sentence — "no such column: foo" — is
    the part the correction loop needs; the rest is noise that dilutes it.
    """
    original = getattr(exc, "orig", None)
    message = str(original) if original else str(exc)

    for marker in ("\n[SQL:", "[SQL:", "\n(Background on this error"):
        index = message.find(marker)
        if index != -1:
            message = message[:index]

    return message.strip() or "The query failed."


def explain(
    connection: Connection, sql: str, engine: Engine | None = None
) -> str | None:
    """Return the query plan, or None when it cannot be obtained.

    Used by the cost gate for reporting. It is advisory: a plan that cannot
    be fetched must not block a query that passed every other gate.
    """
    prefix = "EXPLAIN QUERY PLAN" if connection.dialect is Dialect.SQLITE else "EXPLAIN"

    owns_engine = engine is None
    engine = engine or create_target_engine(connection)

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"{prefix} {sql}")).fetchall()
        return "\n".join(" ".join(str(v) for v in row) for row in rows)
    except SQLAlchemyError:
        return None
    finally:
        if owns_engine:
            engine.dispose()
