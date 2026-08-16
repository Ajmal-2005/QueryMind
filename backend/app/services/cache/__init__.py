"""Result caching, deferred from Phase 3."""

from app.services.cache.results import (
    cache_status,
    invalidate_connection,
    result_key,
    run_cached,
)
from app.services.cache.store import CacheBackend, get_cache, reset_cache

__all__ = [
    "CacheBackend",
    "cache_status",
    "get_cache",
    "invalidate_connection",
    "reset_cache",
    "result_key",
    "run_cached",
]
