from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "degraded", "unavailable", "not_configured"]


class ServiceHealth(BaseModel):
    status: Status
    detail: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    services: dict[str, ServiceHealth]
