"""Statistical profiling of a result set (F14).

Everything downstream of this module - chart selection, outlier detection,
trend analysis, and the narrative prompt - reads the profile rather than the
raw rows. That keeps one type-inference decision in one place instead of
four modules each guessing what a column is.

Inference is the hard part, not the arithmetic. A SQL result set arrives as
Python objects chosen by the driver, and SQLite in particular has no date
type at all: a `DATE` column comes back as `str`. So the classifier looks at
the values, not at any declared type, and records *how* it decided in
``inferred_from`` so a wrong call is visible rather than mysterious.
"""

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# How many distinct values a column may have and still act as a *label*.
# Deliberately not a ratio of distinct to total: the grouping key of any
# GROUP BY has exactly one row per value, so "revenue by region" would score
# 1.0 and be classified as free text - the single most common result shape
# this product produces. Cardinality alone is the honest test.
#
# This is the profiler's question ("can this label something?"), not the chart
# module's ("can 50 bars be read?"). Those are different limits and they live
# in different places - see charts.MAX_BARS.
MAX_CATEGORICAL_DISTINCT = 50

# Free text - a description, a comment, an address - is not a label whatever
# its cardinality. Length separates the two far better than counting does.
MAX_CATEGORICAL_VALUE_LENGTH = 60

# Fraction of non-null string values that must parse as a date before the
# column is called temporal. Not 1.0: one malformed row should not reclassify
# an entire date column.
TEMPORAL_PARSE_THRESHOLD = 0.9

MAX_TOP_VALUES = 10

_DATE_PATTERNS = (
    # ISO-8601 date, optionally with a time part. The overwhelming majority of
    # what SQLite and JSON-ish drivers hand back.
    re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?"),
    # Period grouping output: '2024-03' from strftime('%Y-%m', ...).
    re.compile(r"^\d{4}-\d{2}$"),
    # Year, as produced by strftime('%Y', ...) or EXTRACT(YEAR ...).
    re.compile(r"^\d{4}$"),
)


class ColumnKind(str, Enum):
    NUMERIC = "numeric"
    TEMPORAL = "temporal"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"
    EMPTY = "empty"
    """Every value is null - nothing can be said about it."""


@dataclass
class TopValue:
    value: str
    count: int
    fraction: float


@dataclass
class ColumnProfile:
    name: str
    index: int
    kind: ColumnKind
    inferred_from: str
    """Why the classifier chose this kind - surfaced in the UI."""

    count: int = 0
    """Non-null values."""
    null_count: int = 0
    null_fraction: float = 0.0
    distinct_count: int = 0

    # Numeric only.
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    q1: float | None = None
    q3: float | None = None

    # Temporal only.
    earliest: str | None = None
    latest: str | None = None

    # Categorical and boolean.
    top_values: list[TopValue] = field(default_factory=list)

    @property
    def iqr(self) -> float | None:
        if self.q1 is None or self.q3 is None:
            return None
        return self.q3 - self.q1

    @property
    def is_numeric(self) -> bool:
        return self.kind is ColumnKind.NUMERIC

    @property
    def is_temporal(self) -> bool:
        return self.kind is ColumnKind.TEMPORAL


@dataclass
class ResultProfile:
    row_count: int
    column_count: int
    truncated: bool = False
    columns: list[ColumnProfile] = field(default_factory=list)

    def by_kind(self, kind: ColumnKind) -> list[ColumnProfile]:
        return [c for c in self.columns if c.kind is kind]

    def get(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def is_scalar(self) -> bool:
        """One row, one column - a single number, not a table."""
        return self.row_count == 1 and self.column_count == 1


def _is_missing(value: Any) -> bool:
    # An empty string from a text column is missing data in every practical
    # sense, and counting it as a present value skews null density.
    return value is None or (isinstance(value, str) and not value.strip())


def as_number(value: Any) -> float | None:
    """Coerce a driver value to a float, or None if it is not a number.

    `bool` is excluded deliberately: it is a subclass of `int`, and averaging
    a flag column produces a meaningless number presented with authority.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    return None


def _looks_temporal(value: Any) -> bool:
    if isinstance(value, datetime | date):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    return any(pattern.match(text) for pattern in _DATE_PATTERNS)


def stringify(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _classify(values: list[Any], row_count: int) -> tuple[ColumnKind, str]:
    """Decide what a column is from its values."""
    if not values:
        return ColumnKind.EMPTY, "every value is null"

    if all(isinstance(v, bool) for v in values):
        return ColumnKind.BOOLEAN, "all values are booleans"

    numbers = sum(1 for v in values if as_number(v) is not None)
    if numbers == len(values):
        return ColumnKind.NUMERIC, "all values are numbers"

    temporal = sum(1 for v in values if _looks_temporal(v))
    if temporal / len(values) >= TEMPORAL_PARSE_THRESHOLD:
        native = any(isinstance(v, datetime | date) for v in values)
        return (
            ColumnKind.TEMPORAL,
            "values are dates" if native else "values parse as ISO-8601 dates",
        )

    rendered = [stringify(v) for v in values]
    longest = max(len(v) for v in rendered)
    if longest > MAX_CATEGORICAL_VALUE_LENGTH:
        return ColumnKind.TEXT, f"values run to {longest} characters - free text"

    distinct = len(set(rendered))
    if distinct <= MAX_CATEGORICAL_DISTINCT:
        return ColumnKind.CATEGORICAL, f"{distinct} distinct values across {row_count}"

    return ColumnKind.TEXT, f"{distinct} distinct values - too many to be labels"


def _numeric_statistics(profile: ColumnProfile, values: list[Any]) -> None:
    numbers = sorted(n for v in values if (n := as_number(v)) is not None)
    if not numbers:
        return

    profile.minimum = numbers[0]
    profile.maximum = numbers[-1]
    profile.mean = statistics.fmean(numbers)
    profile.median = statistics.median(numbers)
    # Population stdev, not sample: a result set is the whole thing being
    # described, not a draw from a larger population.
    profile.stddev = statistics.pstdev(numbers) if len(numbers) > 1 else 0.0

    if len(numbers) >= 2:
        # 'inclusive' treats the data as the entire population, matching the
        # median above and NumPy's default linear interpolation.
        q1, _, q3 = statistics.quantiles(numbers, n=4, method="inclusive")
        profile.q1, profile.q3 = q1, q3
    else:
        profile.q1 = profile.q3 = numbers[0]


def _top_values(values: list[Any]) -> list[TopValue]:
    counts: dict[str, int] = {}
    for value in values:
        key = stringify(value)
        counts[key] = counts.get(key, 0) + 1

    total = len(values)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        TopValue(value=value, count=count, fraction=count / total)
        for value, count in ranked[:MAX_TOP_VALUES]
    ]


def profile_column(
    name: str, index: int, column: list[Any], row_count: int
) -> ColumnProfile:
    present = [v for v in column if not _is_missing(v)]
    kind, reason = _classify(present, row_count)

    profile = ColumnProfile(
        name=name,
        index=index,
        kind=kind,
        inferred_from=reason,
        count=len(present),
        null_count=row_count - len(present),
        null_fraction=(row_count - len(present)) / row_count if row_count else 0.0,
        distinct_count=len({stringify(v) for v in present}),
    )

    if kind is ColumnKind.NUMERIC:
        _numeric_statistics(profile, present)
    elif kind is ColumnKind.TEMPORAL and present:
        stamps = sorted(stringify(v) for v in present)
        profile.earliest, profile.latest = stamps[0], stamps[-1]
    elif kind in (ColumnKind.CATEGORICAL, ColumnKind.BOOLEAN) and present:
        profile.top_values = _top_values(present)

    return profile


def profile_result(
    columns: list[str], rows: list[list[Any]], truncated: bool = False
) -> ResultProfile:
    """Describe a result set column by column."""
    row_count = len(rows)
    profiles = [
        profile_column(
            name=name,
            index=index,
            # A short row is padded rather than skipped: a ragged result would
            # otherwise silently drop values from every column after the gap.
            column=[row[index] if index < len(row) else None for row in rows],
            row_count=row_count,
        )
        for index, name in enumerate(columns)
    ]

    return ResultProfile(
        row_count=row_count,
        column_count=len(columns),
        truncated=truncated,
        columns=profiles,
    )


__all__ = [
    "MAX_CATEGORICAL_DISTINCT",
    "MAX_CATEGORICAL_VALUE_LENGTH",
    "ColumnKind",
    "ColumnProfile",
    "ResultProfile",
    "TopValue",
    "as_number",
    "profile_column",
    "profile_result",
    "stringify",
]
