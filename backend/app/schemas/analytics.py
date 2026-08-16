"""API contracts for the analytics stage.

Deliberately mirrors the dataclasses rather than serialising them directly.
The dataclasses carry things the wire does not need — column indexes,
internal reasons — and coupling the response shape to an internal structure
means every refactor becomes a breaking API change.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

ChartTypeName = Literal["line", "bar", "pie", "scatter", "kpi", "table"]
ColumnKindName = Literal[
    "numeric", "temporal", "categorical", "boolean", "text", "empty"
]
ExportFormatName = Literal["csv", "json", "xlsx", "pdf"]


class TopValueRead(BaseModel):
    value: str
    count: int
    fraction: float


class ColumnProfileRead(BaseModel):
    name: str
    kind: ColumnKindName
    inferred_from: str

    count: int
    null_count: int
    null_fraction: float
    distinct_count: int

    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    q1: float | None = None
    q3: float | None = None

    earliest: str | None = None
    latest: str | None = None

    top_values: list[TopValueRead] = []


class ProfileRead(BaseModel):
    row_count: int
    column_count: int
    truncated: bool
    columns: list[ColumnProfileRead] = []


class ChartRead(BaseModel):
    type: ChartTypeName
    reason: str
    x: str | None = None
    y: list[str] = []
    series: str | None = None
    alternatives: list[ChartTypeName] = []


class OutlierRead(BaseModel):
    row_index: int
    column: str
    value: float
    methods: list[str]
    z_score: float | None = None
    iqr_distance: float | None = None


class ColumnOutlierRead(BaseModel):
    column: str
    checked: bool
    reason: str
    iqr_count: int = 0
    zscore_count: int = 0
    agreed_count: int = 0
    lower_fence: float | None = None
    upper_fence: float | None = None


class OutliersRead(BaseModel):
    total: int
    truncated: bool
    columns: list[ColumnOutlierRead] = []
    outliers: list[OutlierRead] = []


class TrendPointRead(BaseModel):
    period: str
    value: float
    delta: float | None = None
    growth_rate: float | None = None
    moving_average: float | None = None


class TrendRead(BaseModel):
    period_column: str
    value_column: str
    direction: Literal["rising", "falling", "flat"]
    summary: str
    window: int
    first_value: float
    last_value: float
    total_change: float
    total_growth_rate: float | None = None
    average_growth_rate: float | None = None
    best_period: str | None = None
    worst_period: str | None = None
    points: list[TrendPointRead] = []


class AnalysisRead(BaseModel):
    profile: ProfileRead
    chart: ChartRead
    outliers: OutliersRead
    trend: TrendRead | None = None
    trend_unavailable: str | None = None
    """Why no trend was produced — shown instead of silently omitting it."""

    options: dict[str, list[str]] = {}
    """Columns available per axis type, for the manual chart override."""

    duration_ms: float = 0.0


class MaskedColumnRead(BaseModel):
    column: str
    rule: str
    detected_as: str
    values_masked: int


class NarrativeRead(BaseModel):
    headline: str
    summary: str
    findings: list[str] = []
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    masked_columns: list[MaskedColumnRead] = []


class InsightRequest(BaseModel):
    """Summarise a result set.

    Carries the SQL rather than a result payload: the server re-runs it
    through the same gates and the same cache, so a client cannot ask for a
    narrative about rows it invented, and 10,000 rows never travel upstream.
    """

    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)
    question: str = Field(default="", max_length=2000)


class ExportRequest(BaseModel):
    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)
    format: ExportFormatName
    question: str = Field(default="", max_length=2000)
    title: str = Field(default="Query result", max_length=200)

    # PDF only.
    include_narrative: bool = False
    chart_png: str | None = Field(default=None, max_length=6_000_000)
    """`data:image/png;base64,...` of the chart as the browser drew it."""


class CacheStatusRead(BaseModel):
    backend: str
    hits: int
    misses: int
    writes: int
    errors: int
    hit_rate: float
    ttl_seconds: int


# --------------------------------------------------------------- converters
#
# Three routers return an analysis — /query, /query/insight and dashboard
# refresh — so the mapping lives once, here, next to the shapes it produces.


def to_analysis_read(analysis: Any) -> AnalysisRead:
    """Map an `analytics.Analysis` onto the wire contract."""
    profile = analysis.profile
    trend = analysis.trend.trend

    return AnalysisRead(
        profile=ProfileRead(
            row_count=profile.row_count,
            column_count=profile.column_count,
            truncated=profile.truncated,
            columns=[
                ColumnProfileRead(
                    name=c.name,
                    kind=c.kind.value,
                    inferred_from=c.inferred_from,
                    count=c.count,
                    null_count=c.null_count,
                    null_fraction=c.null_fraction,
                    distinct_count=c.distinct_count,
                    minimum=c.minimum,
                    maximum=c.maximum,
                    mean=c.mean,
                    median=c.median,
                    stddev=c.stddev,
                    q1=c.q1,
                    q3=c.q3,
                    earliest=c.earliest,
                    latest=c.latest,
                    top_values=[
                        TopValueRead(value=t.value, count=t.count, fraction=t.fraction)
                        for t in c.top_values
                    ],
                )
                for c in profile.columns
            ],
        ),
        chart=ChartRead(
            type=analysis.chart.type.value,
            reason=analysis.chart.reason,
            x=analysis.chart.x,
            y=analysis.chart.y,
            series=analysis.chart.series,
            alternatives=[a.value for a in analysis.chart.alternatives],
        ),
        outliers=OutliersRead(
            total=analysis.outliers.total,
            truncated=analysis.outliers.truncated,
            columns=[
                ColumnOutlierRead(
                    column=c.column,
                    checked=c.checked,
                    reason=c.reason,
                    iqr_count=c.iqr_count,
                    zscore_count=c.zscore_count,
                    agreed_count=c.agreed_count,
                    lower_fence=c.lower_fence,
                    upper_fence=c.upper_fence,
                )
                for c in analysis.outliers.columns
            ],
            outliers=[
                OutlierRead(
                    row_index=o.row_index,
                    column=o.column,
                    value=o.value,
                    methods=o.methods,
                    z_score=o.z_score,
                    iqr_distance=o.iqr_distance,
                )
                for o in analysis.outliers.outliers
            ],
        ),
        trend=(
            TrendRead(
                period_column=trend.period_column,
                value_column=trend.value_column,
                direction=trend.direction,
                summary=trend.summary,
                window=trend.window,
                first_value=trend.first_value,
                last_value=trend.last_value,
                total_change=trend.total_change,
                total_growth_rate=trend.total_growth_rate,
                average_growth_rate=trend.average_growth_rate,
                best_period=trend.best_period,
                worst_period=trend.worst_period,
                points=[
                    TrendPointRead(
                        period=p.period,
                        value=p.value,
                        delta=p.delta,
                        growth_rate=p.growth_rate,
                        moving_average=p.moving_average,
                    )
                    for p in trend.points
                ],
            )
            if trend
            else None
        ),
        trend_unavailable=analysis.trend.reason or None,
        options=analysis.options,
        duration_ms=round(analysis.duration_ms, 1),
    )


def to_narrative_read(narrative: Any) -> NarrativeRead:
    return NarrativeRead(
        headline=narrative.headline,
        summary=narrative.summary,
        findings=narrative.findings,
        model=narrative.model,
        input_tokens=narrative.input_tokens,
        output_tokens=narrative.output_tokens,
        latency_ms=round(narrative.latency_ms, 1),
        masked_columns=[
            MaskedColumnRead(
                column=c.column,
                rule=c.rule,
                detected_as=c.detected_as,
                values_masked=c.values_masked,
            )
            for c in narrative.masking.columns
        ],
    )


__all__ = [
    "AnalysisRead",
    "CacheStatusRead",
    "ChartRead",
    "ColumnProfileRead",
    "ExportRequest",
    "InsightRequest",
    "NarrativeRead",
    "OutliersRead",
    "ProfileRead",
    "TrendRead",
    "to_analysis_read",
    "to_narrative_read",
]
