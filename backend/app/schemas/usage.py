"""API contracts for token and cost tracking (F29)."""

from datetime import datetime

from pydantic import BaseModel


class UsageTotals(BaseModel):
    queries: int
    executed: int
    rejected: int
    recovered_by_correction: int
    tokens: int
    estimated_cost_usd: float
    mean_latency_ms: float


class UsageByUser(BaseModel):
    user_id: str
    email: str
    queries: int
    tokens: int
    estimated_cost_usd: float


class ModelRate(BaseModel):
    """The price the figures above were computed with.

    Returned with every response so a cost can always be traced back to the
    rate that produced it - prices change, and a number with no rate beside
    it silently becomes wrong.
    """

    model: str
    input_per_mtok: float
    output_per_mtok: float


class UsageResponse(BaseModel):
    window_days: int
    scope: str
    """'you' or 'all users' - which rows these totals cover."""

    totals: UsageTotals
    by_user: list[UsageByUser] = []
    rates: list[ModelRate] = []
    cost_note: str = ""


class AuditEntry(BaseModel):
    id: str
    user_id: str | None
    action: str
    payload: dict = {}
    created_at: datetime


__all__ = [
    "AuditEntry",
    "ModelRate",
    "UsageByUser",
    "UsageResponse",
    "UsageTotals",
]
