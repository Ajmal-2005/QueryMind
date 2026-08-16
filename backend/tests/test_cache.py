"""Result caching, deferred from Phase 3.

Redis has never run against this codebase. These exercise the caching logic
through the in-process backend, which is the same code path minus the
transport.
"""

import time

import pytest

from app.services.cache.results import result_key, run_cached
from app.services.cache.store import MemoryCache, NullCache, get_cache, reset_cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_cache()
    yield
    reset_cache()


def test_memory_cache_returns_what_was_stored() -> None:
    cache = MemoryCache()
    cache.set("k", {"rows": [[1]]}, ttl=60)
    assert cache.get("k") == {"rows": [[1]]}
    assert cache.stats.hits == 1


def test_expired_entries_are_misses() -> None:
    cache = MemoryCache()
    cache.set("k", {"a": 1}, ttl=0)
    time.sleep(0.01)
    assert cache.get("k") is None
    assert cache.stats.misses == 1


def test_oldest_entry_is_evicted_at_the_cap() -> None:
    cache = MemoryCache(max_entries=2)
    cache.set("a", {}, 60)
    cache.set("b", {}, 60)
    cache.set("c", {}, 60)

    assert cache.get("a") is None
    assert cache.get("c") is not None


def test_delete_prefix_scopes_to_one_connection() -> None:
    cache = MemoryCache()
    cache.set("result:conn-1:aaa", {}, 60)
    cache.set("result:conn-1:bbb", {}, 60)
    cache.set("result:conn-2:ccc", {}, 60)

    assert cache.delete_prefix("result:conn-1:") == 2
    assert cache.get("result:conn-2:ccc") is not None


def test_null_cache_never_stores() -> None:
    cache = NullCache()
    cache.set("k", {"a": 1}, 60)
    assert cache.get("k") is None


def test_key_depends_on_sql_and_connection() -> None:
    assert result_key("c1", "SELECT 1") == result_key("c1", "  SELECT 1  ")
    assert result_key("c1", "SELECT 1") != result_key("c2", "SELECT 1")
    assert result_key("c1", "SELECT 1") != result_key("c1", "SELECT 2")


def test_sql_does_not_appear_in_the_key() -> None:
    """Keys reach logs and SCAN output; user data must not ride along."""
    assert "customers" not in result_key("c1", "SELECT * FROM customers")


def test_second_identical_run_is_served_from_cache(demo_connection) -> None:
    sql = "SELECT COUNT(*) AS n FROM customers"

    first = run_cached(demo_connection, sql)
    second = run_cached(demo_connection, sql)

    assert first.ok and second.ok
    assert first.cached is False
    assert second.cached is True
    assert second.rows == first.rows


def test_different_sql_is_not_served_from_cache(demo_connection) -> None:
    run_cached(demo_connection, "SELECT COUNT(*) AS n FROM customers")
    other = run_cached(demo_connection, "SELECT COUNT(*) AS n FROM products")
    assert other.cached is False


def test_failures_are_not_cached(demo_connection) -> None:
    """The correction loop must see the database's live answer."""
    sql = "SELECT * FROM does_not_exist"
    assert run_cached(demo_connection, sql).ok is False
    assert run_cached(demo_connection, sql).cached is False


def test_invalidation_drops_a_connections_results(demo_connection) -> None:
    from app.services.cache.results import invalidate_connection

    sql = "SELECT COUNT(*) AS n FROM customers"
    run_cached(demo_connection, sql)
    invalidate_connection(demo_connection.id)

    assert run_cached(demo_connection, sql).cached is False


def test_cache_can_be_bypassed(demo_connection) -> None:
    sql = "SELECT COUNT(*) AS n FROM customers"
    run_cached(demo_connection, sql)
    assert run_cached(demo_connection, sql, use_cache=False).cached is False


def test_backend_defaults_to_memory_without_redis() -> None:
    assert get_cache().name == "memory"
