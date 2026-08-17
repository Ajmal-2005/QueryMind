"""Outlier detection (F15).

Two methods, deliberately, because they disagree in useful ways. The z-score
asks how many standard deviations a value sits from the mean; the IQR rule
asks whether it falls outside the middle half of the data stretched by 1.5.
The z-score is the weaker of the two on the shapes this system produces -
revenue, counts, durations are all right-skewed, and a single large value
inflates the standard deviation enough to hide itself. The IQR rule reads
quartiles, which that value cannot move.

So both run, and a flag records which methods agreed. A value both methods
flag is worth a user's attention; one only the z-score flags usually is not.
"""

from dataclasses import dataclass, field
from typing import Any

from app.services.analytics.profile import ColumnKind, ResultProfile, as_number

IQR_MULTIPLIER = 1.5
Z_SCORE_THRESHOLD = 3.0

# Quartiles computed from a handful of points describe nothing. Below this the
# column is reported as "too few rows" rather than producing confident-looking
# flags from noise.
MIN_ROWS_FOR_DETECTION = 8

# A pathological column - say a join that fanned out - could flag thousands of
# rows and bloat the response. The count stays honest; the detail is capped.
MAX_REPORTED = 200


@dataclass
class Outlier:
    row_index: int
    column: str
    value: float
    methods: list[str]
    """Which detectors flagged it: 'iqr', 'zscore', or both."""

    z_score: float | None = None
    iqr_distance: float | None = None
    """How many IQRs beyond the nearer fence the value sits."""


@dataclass
class ColumnOutliers:
    column: str
    checked: bool
    reason: str
    """Why the column was or was not checked."""

    iqr_count: int = 0
    zscore_count: int = 0
    agreed_count: int = 0
    lower_fence: float | None = None
    upper_fence: float | None = None


@dataclass
class OutlierReport:
    columns: list[ColumnOutliers] = field(default_factory=list)
    outliers: list[Outlier] = field(default_factory=list)
    total: int = 0
    truncated: bool = False
    """True when more outliers were found than are listed."""

    @property
    def any_found(self) -> bool:
        return self.total > 0

    def rows_flagged(self) -> set[int]:
        return {o.row_index for o in self.outliers}


def _detect_column(
    profile, values: list[tuple[int, float]]
) -> tuple[ColumnOutliers, list[Outlier]]:
    summary = ColumnOutliers(column=profile.name, checked=True, reason="checked")

    iqr = profile.iqr
    lower = upper = None
    if iqr is not None and iqr > 0:
        lower = profile.q1 - IQR_MULTIPLIER * iqr
        upper = profile.q3 + IQR_MULTIPLIER * iqr
        summary.lower_fence, summary.upper_fence = lower, upper

    mean, stddev = profile.mean, profile.stddev
    use_z = stddev is not None and stddev > 0 and mean is not None

    found: list[Outlier] = []
    for row_index, value in values:
        methods: list[str] = []
        z = iqr_distance = None

        if lower is not None and (value < lower or value > upper):
            methods.append("iqr")
            fence_gap = lower - value if value < lower else value - upper
            iqr_distance = fence_gap / iqr

        if use_z:
            z_candidate = (value - mean) / stddev
            if abs(z_candidate) >= Z_SCORE_THRESHOLD:
                methods.append("zscore")
                z = z_candidate

        if not methods:
            continue

        found.append(
            Outlier(
                row_index=row_index,
                column=profile.name,
                value=value,
                methods=methods,
                z_score=z,
                iqr_distance=iqr_distance,
            )
        )

    summary.iqr_count = sum(1 for o in found if "iqr" in o.methods)
    summary.zscore_count = sum(1 for o in found if "zscore" in o.methods)
    summary.agreed_count = sum(1 for o in found if len(o.methods) == 2)

    if lower is None and not use_z:
        summary.checked = False
        summary.reason = "every value is identical - nothing can be an outlier"

    return summary, found


def detect(profile: ResultProfile, rows: list[list[Any]]) -> OutlierReport:
    """Flag numeric values that sit far outside their column's distribution."""
    report = OutlierReport()
    all_found: list[Outlier] = []

    for column in profile.columns:
        if column.kind is not ColumnKind.NUMERIC:
            continue

        if column.count < MIN_ROWS_FOR_DETECTION:
            report.columns.append(
                ColumnOutliers(
                    column=column.name,
                    checked=False,
                    reason=(
                        f"{column.count} rows - too few for a distribution "
                        f"(need {MIN_ROWS_FOR_DETECTION})"
                    ),
                )
            )
            continue

        values = [
            (index, number)
            for index, row in enumerate(rows)
            if column.index < len(row)
            and (number := as_number(row[column.index])) is not None
        ]
        summary, found = _detect_column(column, values)
        report.columns.append(summary)
        all_found.extend(found)

    report.total = len(all_found)
    # Most extreme first, so a truncated list still shows what matters. Both
    # scores are optional, hence the explicit floor rather than `or 0`.
    all_found.sort(
        key=lambda o: max(abs(o.z_score or 0.0), o.iqr_distance or 0.0), reverse=True
    )
    report.outliers = all_found[:MAX_REPORTED]
    report.truncated = len(all_found) > MAX_REPORTED
    return report


__all__ = [
    "IQR_MULTIPLIER",
    "MIN_ROWS_FOR_DETECTION",
    "Z_SCORE_THRESHOLD",
    "ColumnOutliers",
    "Outlier",
    "OutlierReport",
    "detect",
]
