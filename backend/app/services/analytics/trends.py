"""Trend analysis over a time series (F16).

Runs only when the result actually is a series: one temporal column, at least
one numeric column, and one value per period. A result with several rows per
period is a detail listing, not a trend, and averaging it here would invent a
series the user never asked for — so that case is declined with a reason
rather than answered badly.

Direction comes from a least-squares slope over the whole series rather than
from comparing the first and last points. Every period gets a vote that way,
so a modest bump in the final month cannot by itself declare a declining
series to be growing. It is not robust to a *large* outlier — least squares
never is — and a genuine spike will still move the verdict, which is the
correct outcome for a series that really did spike.
"""

from dataclasses import dataclass, field
from typing import Any

from app.services.analytics.profile import (
    ColumnKind,
    ResultProfile,
    as_number,
    stringify,
)

MIN_POINTS = 3

DEFAULT_WINDOW = 3

# Slope is compared against the series mean, so "flat" means the total drift
# across the whole series is under 5% of the typical value.
FLAT_SLOPE_RATIO = 0.05


@dataclass
class TrendPoint:
    period: str
    value: float
    delta: float | None = None
    """Change from the previous period."""

    growth_rate: float | None = None
    """Fractional change from the previous period; None when it was zero."""

    moving_average: float | None = None


@dataclass
class Trend:
    period_column: str
    value_column: str
    direction: str
    """'rising', 'falling', or 'flat'."""

    points: list[TrendPoint] = field(default_factory=list)
    window: int = DEFAULT_WINDOW

    first_value: float = 0.0
    last_value: float = 0.0
    total_change: float = 0.0
    total_growth_rate: float | None = None
    average_growth_rate: float | None = None
    """Mean of the period-over-period rates — the typical step, not the total."""

    best_period: str | None = None
    worst_period: str | None = None
    slope: float = 0.0

    @property
    def summary(self) -> str:
        """One sentence, used by the template narrator and the UI caption."""
        span = f"{self.points[0].period} to {self.points[-1].period}"
        if self.total_growth_rate is None:
            return (
                f"{self.value_column} moved from {self.first_value:,.2f} to "
                f"{self.last_value:,.2f} over {span}."
            )
        return (
            f"{self.value_column} is {self.direction} — "
            f"{self.total_growth_rate:+.1%} from {self.first_value:,.2f} to "
            f"{self.last_value:,.2f} over {span}."
        )


@dataclass
class TrendResult:
    trend: Trend | None = None
    reason: str = ""
    """Why no trend was produced. Empty when one was."""


def _slope(values: list[float]) -> float:
    """Least-squares slope against position, i.e. change per period."""
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n

    numerator = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


def _direction(values: list[float], slope: float) -> str:
    scale = sum(abs(v) for v in values) / len(values)
    if scale == 0:
        return "flat"
    # Total drift across the series, relative to the typical magnitude.
    drift = abs(slope) * (len(values) - 1) / scale
    if drift < FLAT_SLOPE_RATIO:
        return "flat"
    return "rising" if slope > 0 else "falling"


def _build(
    period_column: str, value_column: str, series: list[tuple[str, float]]
) -> Trend:
    values = [value for _, value in series]
    window = min(DEFAULT_WINDOW, len(values))
    slope = _slope(values)

    points: list[TrendPoint] = []
    for index, (period, value) in enumerate(series):
        point = TrendPoint(period=period, value=value)

        if index > 0:
            previous = values[index - 1]
            point.delta = value - previous
            # A growth rate off a zero base is undefined, not infinite.
            if previous != 0:
                point.growth_rate = (value - previous) / abs(previous)

        if index + 1 >= window:
            point.moving_average = sum(values[index + 1 - window : index + 1]) / window

        points.append(point)

    rates = [p.growth_rate for p in points if p.growth_rate is not None]
    first, last = values[0], values[-1]

    return Trend(
        period_column=period_column,
        value_column=value_column,
        direction=_direction(values, slope),
        points=points,
        window=window,
        first_value=first,
        last_value=last,
        total_change=last - first,
        total_growth_rate=(last - first) / abs(first) if first != 0 else None,
        average_growth_rate=sum(rates) / len(rates) if rates else None,
        best_period=max(series, key=lambda pair: pair[1])[0],
        worst_period=min(series, key=lambda pair: pair[1])[0],
        slope=slope,
    )


def analyze(
    profile: ResultProfile, rows: list[list[Any]], value_column: str | None = None
) -> TrendResult:
    """Describe how a numeric column moves over a temporal one."""
    temporal = profile.by_kind(ColumnKind.TEMPORAL)
    if not temporal:
        return TrendResult(reason="no date column in the result")

    numeric = profile.by_kind(ColumnKind.NUMERIC)
    if value_column:
        numeric = [c for c in numeric if c.name == value_column] or numeric
    if not numeric:
        return TrendResult(reason="no numeric column to trend")

    period, measure = temporal[0], numeric[0]

    series: list[tuple[str, float]] = []
    seen: set[str] = set()
    for row in rows:
        if period.index >= len(row) or measure.index >= len(row):
            continue
        key, value = row[period.index], row[measure.index]
        if key is None or (number := as_number(value)) is None:
            continue

        label = stringify(key)
        if label in seen:
            return TrendResult(
                reason=(
                    f"{period.name} repeats — this is a detail listing, "
                    "not one value per period"
                )
            )
        seen.add(label)
        series.append((label, number))

    if len(series) < MIN_POINTS:
        return TrendResult(
            reason=f"{len(series)} periods — need at least {MIN_POINTS} for a trend"
        )

    # Chronological order, whatever the query's ORDER BY happened to be. The
    # ISO-8601 shapes the profiler accepts as temporal all sort correctly as
    # text, which is why it insists on that format.
    series.sort(key=lambda pair: pair[0])
    return TrendResult(trend=_build(period.name, measure.name, series))


__all__ = ["MIN_POINTS", "Trend", "TrendPoint", "TrendResult", "analyze"]
