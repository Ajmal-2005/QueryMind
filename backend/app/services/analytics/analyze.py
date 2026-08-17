"""The analytics stage: everything that can be said about a result set
without calling a model.

Composed as one function because the four steps have a strict dependency
order - profile first, then the three readers of it - and because the query
pipeline, the export path, and dashboard refresh all need exactly the same
thing. Splitting it would give three call sites three chances to disagree.

Narrative generation is *not* here. It costs an API call, and holding the
table and chart back while waiting on prose would make the whole product feel
slower than it is. It is a separate endpoint the UI fires once the result is
already on screen.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.services.analytics import charts, outliers, trends
from app.services.analytics.charts import ChartSpec
from app.services.analytics.outliers import OutlierReport
from app.services.analytics.profile import ResultProfile, profile_result
from app.services.analytics.trends import TrendResult

log = get_logger(__name__)


@dataclass
class Analysis:
    profile: ResultProfile
    chart: ChartSpec
    outliers: OutlierReport
    trend: TrendResult
    options: dict[str, list[str]] = field(default_factory=dict)
    duration_ms: float = 0.0


def analyze(
    columns: list[str], rows: list[list[Any]], truncated: bool = False
) -> Analysis:
    """Profile a result set and derive its chart, outliers, and trend."""
    started = time.perf_counter()

    profile = profile_result(columns, rows, truncated=truncated)
    analysis = Analysis(
        profile=profile,
        chart=charts.recommend(profile),
        outliers=outliers.detect(profile, rows),
        trend=trends.analyze(profile, rows),
        options=charts.options(profile),
    )
    analysis.duration_ms = (time.perf_counter() - started) * 1000

    log.info(
        "result_analyzed",
        rows=profile.row_count,
        columns=profile.column_count,
        chart=analysis.chart.type.value,
        outliers=analysis.outliers.total,
        trend=analysis.trend.trend is not None,
        duration_ms=round(analysis.duration_ms, 1),
    )
    return analysis


__all__ = ["Analysis", "analyze"]
