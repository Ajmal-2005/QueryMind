"""API contracts for saved dashboards (F18)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.analytics import AnalysisRead, ChartRead
from app.schemas.query import ResultRead, ValidationRead


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    layout: dict | None = None


class TileCreate(BaseModel):
    """Pin a query to a dashboard.

    The SQL is stored, not the question, so opening the dashboard re-runs a
    known query instead of re-generating one that might come back different.
    """

    title: str = Field(min_length=1, max_length=200)
    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)
    question: str | None = Field(default=None, max_length=2000)
    query_id: str | None = None
    chart: dict = Field(default_factory=dict)


class TileRead(BaseModel):
    id: str
    title: str
    connection_id: str | None
    connection_name: str | None = None
    question: str | None
    sql: str
    chart: dict = {}
    position: int
    created_at: datetime


class DashboardRead(BaseModel):
    id: str
    name: str
    description: str | None
    layout: dict = {}
    tile_count: int
    created_at: datetime
    updated_at: datetime


class DashboardDetail(DashboardRead):
    tiles: list[TileRead] = []


class TileResult(BaseModel):
    """One tile's data after a refresh.

    Every tile carries its own error rather than failing the whole refresh:
    a dashboard with five working tiles and one broken one should show five
    charts and one clearly labelled failure.
    """

    tile_id: str
    ok: bool
    result: ResultRead | None = None
    analysis: AnalysisRead | None = None
    chart: ChartRead | None = None
    validation: ValidationRead | None = None
    cached: bool = False
    error: str | None = None


class DashboardRefresh(BaseModel):
    dashboard_id: str
    refreshed_at: datetime
    tiles: list[TileResult] = []
    duration_ms: float = 0.0


__all__ = [
    "DashboardCreate",
    "DashboardDetail",
    "DashboardRead",
    "DashboardRefresh",
    "DashboardUpdate",
    "TileCreate",
    "TileRead",
    "TileResult",
]
