"""Health and readiness endpoints.

``/health`` is the milestone-1 gate: it reports the app itself plus every
backing service, so a green response means the stack is genuinely up rather
than merely serving HTTP.
"""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import settings
from app.core.database import get_db
from app.schemas.health import HealthResponse, ServiceHealth

router = APIRouter()


def _check_database(db: Session) -> ServiceHealth:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health checks report, never raise
        return ServiceHealth(status="unavailable", detail=str(exc)[:200])
    elapsed = (time.perf_counter() - started) * 1000
    return ServiceHealth(status="ok", latency_ms=round(elapsed, 2))


def _check_redis() -> ServiceHealth:
    if not settings.REDIS_URL:
        return ServiceHealth(
            status="not_configured", detail="REDIS_URL is unset; caching disabled"
        )

    started = time.perf_counter()
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return ServiceHealth(status="unavailable", detail=str(exc)[:200])
    elapsed = (time.perf_counter() - started) * 1000
    return ServiceHealth(status="ok", latency_ms=round(elapsed, 2))


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(db: Session = Depends(get_db)) -> HealthResponse:
    services = {
        "database": _check_database(db),
        "redis": _check_redis(),
    }
    # An unconfigured optional service is not a degradation; an unreachable
    # one is.
    degraded = any(s.status in ("unavailable", "degraded") for s in services.values())

    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        environment=settings.ENVIRONMENT,
        services=services,
    )


@router.get("/health/live", summary="Liveness probe")
def liveness() -> dict:
    """Cheap probe for orchestrators — no dependency checks."""
    return {"status": "alive"}
