"""Caching executed query results.

What makes this safe to cache at all: every query that reaches execution has
passed the safety gate, so it is a read. Nothing in this system writes to a
target database, which means a cached result can only ever be stale - never
wrong about an operation that happened.

Staleness is the whole risk, and it is handled by being short and honest: a
five-minute TTL, and `cached: true` on every result served from the cache so
the UI can say so and no benchmark can mistake a 2 ms cache hit for query
performance.

Keyed on the *validated* SQL, not the question. Two differently-worded
questions that generate identical SQL should share an entry, and the same
question that generates different SQL must not.
"""

import hashlib
import time
from typing import Any

from sqlalchemy import Engine

from app.core.config import settings
from app.core.logging import get_logger
from app.models.connection import Connection
from app.services.cache.store import get_cache
from app.services.execution.runner import ExecutionResult, execute

log = get_logger(__name__)

# A result far larger than this costs more to serialise and ship to Redis than
# re-running the query would. The cap is on cells, not rows, because 10 columns
# of 5,000 rows is the same problem as 500 columns of 100.
MAX_CACHEABLE_CELLS = 200_000


def result_key(connection_id: str, sql: str) -> str:
    """Cache key for one query against one connection.

    Hashed rather than stored raw: SQL can be long, can contain characters
    Redis keys handle badly, and would otherwise put user data in key names
    that appear in logs and `SCAN` output.
    """
    digest = hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()[:32]
    return f"result:{connection_id}:{digest}"


def connection_prefix(connection_id: str) -> str:
    return f"result:{connection_id}:"


def _serialise(result: ExecutionResult) -> dict:
    return {
        "columns": result.columns,
        # Values are coerced to JSON-safe form by the backend's `default=str`;
        # dates and Decimals come back as strings, which is what the API would
        # have serialised them to in any case.
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
    }


def _deserialise(payload: dict) -> ExecutionResult:
    return ExecutionResult(
        ok=True,
        columns=list(payload.get("columns", [])),
        rows=[list(row) for row in payload.get("rows", [])],
        row_count=int(payload.get("row_count", 0)),
        truncated=bool(payload.get("truncated", False)),
        duration_ms=float(payload.get("duration_ms", 0.0)),
        cached=True,
    )


def _cacheable(result: ExecutionResult) -> bool:
    if not result.ok:
        # A failure is not cached: the correction loop must see the database's
        # live answer, and an error is usually cheap to reproduce anyway.
        return False
    cells = result.row_count * max(len(result.columns), 1)
    return cells <= MAX_CACHEABLE_CELLS


def run_cached(
    connection: Connection,
    sql: str,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
    engine: Engine | None = None,
    use_cache: bool = True,
) -> ExecutionResult:
    """Execute a validated query, serving a recent identical run if there is one."""
    if not use_cache or not settings.CACHE_ENABLED:
        return execute(connection, sql, max_rows, timeout_seconds, engine)

    cache = get_cache()
    key = result_key(connection.id, sql)
    started = time.perf_counter()

    if (payload := cache.get(key)) is not None:
        result = _deserialise(payload)
        result.duration_ms = (time.perf_counter() - started) * 1000
        log.info("result_cache_hit", backend=cache.name, rows=result.row_count)
        return result

    result = execute(connection, sql, max_rows, timeout_seconds, engine)
    if _cacheable(result):
        cache.set(key, _serialise(result), settings.CACHE_TTL_SECONDS)

    return result


def invalidate_connection(connection_id: str) -> int:
    """Drop every cached result for a connection.

    Called when a connection is re-indexed or deleted. Re-indexing means the
    schema moved underneath, and results from the old shape should not
    outlive it.
    """
    removed = get_cache().delete_prefix(connection_prefix(connection_id))
    if removed:
        log.info("result_cache_invalidated", connection_id=connection_id, keys=removed)
    return removed


def cache_status() -> dict[str, Any]:
    cache = get_cache()
    stats = cache.stats
    return {
        "backend": cache.name,
        "hits": stats.hits,
        "misses": stats.misses,
        "writes": stats.writes,
        "errors": stats.errors,
        "hit_rate": round(stats.hit_rate, 3),
        "ttl_seconds": settings.CACHE_TTL_SECONDS,
    }


__all__ = [
    "cache_status",
    "connection_prefix",
    "invalidate_connection",
    "result_key",
    "run_cached",
]
