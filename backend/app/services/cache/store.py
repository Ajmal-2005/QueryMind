"""Cache backends.

Deferred from Phase 3 rather than half-built, because a cache with no way to
run it is a liability: it would have gone into the report as working when
nothing had ever exercised it. This version has two backends and the
in-process one runs everywhere, so the caching *logic* is testable even where
Redis is not.

Redis is still the deployment target and is still unexercised - no Docker, no
Redis, ever run here. The interface is small enough that swapping backends is
a configuration change, and `backend_name` travels into the health endpoint
and the API response so no measurement can misattribute a cache hit.
"""

import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Bounded so a long-running process cannot grow without limit. Well past the
# working set of an interactive session.
MAX_MEMORY_ENTRIES = 256


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    errors: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@runtime_checkable
class CacheBackend(Protocol):
    name: str
    stats: CacheStats

    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict, ttl: int) -> None: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def clear(self) -> None: ...


@dataclass
class _Entry:
    value: dict
    expires_at: float


class MemoryCache:
    """Process-local TTL cache.

    Correct for a single-process deployment and for tests; wrong for more than
    one worker, which is exactly why Redis is the deployment target. Entries
    are evicted oldest-first once the cap is reached.
    """

    name = "memory"

    def __init__(self, max_entries: int = MAX_MEMORY_ENTRIES) -> None:
        self.max_entries = max_entries
        self.stats = CacheStats()
        self._entries: dict[str, _Entry] = {}
        # Uvicorn runs sync endpoints in a thread pool, so two requests really
        # can touch this at once.
        self._lock = Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            if entry.expires_at <= time.monotonic():
                del self._entries[key]
                self.stats.misses += 1
                return None
            self.stats.hits += 1
            return entry.value

    def set(self, key: str, value: dict, ttl: int) -> None:
        with self._lock:
            if key not in self._entries and len(self._entries) >= self.max_entries:
                # dicts preserve insertion order, so the first key is the oldest.
                del self._entries[next(iter(self._entries))]
            self._entries[key] = _Entry(value, time.monotonic() + ttl)
            self.stats.writes += 1

    def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            doomed = [k for k in self._entries if k.startswith(prefix)]
            for key in doomed:
                del self._entries[key]
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class RedisCache:
    """Shared cache for multi-worker deployments.

    **Never exercised** - no Redis has run against this codebase. Every method
    degrades to a miss on failure rather than raising: a cache that is down
    must slow the system, not break it.
    """

    name = "redis"

    def __init__(self, url: str, prefix: str = "nlq:") -> None:
        import redis

        self.prefix = prefix
        self.stats = CacheStats()
        self._client = redis.Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
        )

    def get(self, key: str) -> dict | None:
        try:
            raw = self._client.get(self.prefix + key)
        except Exception as exc:  # noqa: BLE001 - any redis failure is a miss
            self.stats.errors += 1
            log.warning("cache_get_failed", error=str(exc)[:120])
            return None

        if raw is None:
            self.stats.misses += 1
            return None

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            # A poisoned entry, from a deploy that changed the payload shape.
            self.stats.misses += 1
            return None

        self.stats.hits += 1
        return value

    def set(self, key: str, value: dict, ttl: int) -> None:
        try:
            self._client.setex(self.prefix + key, ttl, json.dumps(value, default=str))
            self.stats.writes += 1
        except Exception as exc:  # noqa: BLE001
            self.stats.errors += 1
            log.warning("cache_set_failed", error=str(exc)[:120])

    def delete_prefix(self, prefix: str) -> int:
        try:
            # SCAN, not KEYS: KEYS blocks the whole server on a large keyspace.
            deleted = 0
            for key in self._client.scan_iter(
                match=f"{self.prefix}{prefix}*", count=500
            ):
                deleted += self._client.delete(key)
            return deleted
        except Exception as exc:  # noqa: BLE001
            self.stats.errors += 1
            log.warning("cache_delete_failed", error=str(exc)[:120])
            return 0

    def clear(self) -> None:
        self.delete_prefix("")


class NullCache:
    """Caching disabled. Every read misses, every write is discarded."""

    name = "disabled"

    def __init__(self) -> None:
        self.stats = CacheStats()

    def get(self, key: str) -> dict | None:
        self.stats.misses += 1
        return None

    def set(self, key: str, value: dict, ttl: int) -> None:
        return None

    def delete_prefix(self, prefix: str) -> int:
        return 0

    def clear(self) -> None:
        return None


_backend: CacheBackend | None = None
_backend_lock = Lock()


def get_cache() -> CacheBackend:
    """The process's cache backend, chosen once from configuration."""
    global _backend
    if _backend is not None:
        return _backend

    with _backend_lock:
        if _backend is not None:
            return _backend

        if not settings.CACHE_ENABLED:
            _backend = NullCache()
        elif settings.REDIS_URL:
            try:
                _backend = RedisCache(settings.REDIS_URL)
            except Exception as exc:  # noqa: BLE001 - fall back, do not crash
                log.warning("redis_cache_unavailable", error=str(exc)[:120])
                _backend = MemoryCache()
        else:
            _backend = MemoryCache()

        log.info("cache_backend_selected", backend=_backend.name)
        return _backend


def reset_cache() -> None:
    """Drop the chosen backend. Tests only."""
    global _backend
    with _backend_lock:
        _backend = None


__all__ = [
    "CacheBackend",
    "CacheStats",
    "MemoryCache",
    "NullCache",
    "RedisCache",
    "get_cache",
    "reset_cache",
]
