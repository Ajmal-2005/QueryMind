"""Chart selection from result shape (F11), and the options behind the
manual override (F12).

Rule-based, not model-based, for the same reason intent classification is:
the answer is fully determined by the shape of the result, an LLM round trip
would cost more than the whole rest of the analytics stage, and a wrong
choice here is a cosmetic problem the user fixes with one click.

The rules are ordered most-specific first and the first match wins. Every
decision carries the sentence that produced it, so the UI can say *why* it
drew a line chart rather than leaving the user to guess.

Anything the rules decline falls through to a table. A table is never wrong -
it is only ever less illuminating than a chart would have been - so it is the
right floor for a system that must not present data misleadingly.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.services.analytics.profile import ColumnKind, ResultProfile

# Beyond this many bars the labels overlap into an unreadable smear, so the
# result is better served as a table the user can sort.
MAX_BARS = 25

# A pie chart stops communicating proportion well past a handful of slices.
MAX_PIE_SLICES = 6

# A scatter plot of a million points is a filled rectangle. This is generous
# for a chart that is genuinely about the cloud's shape.
MAX_SCATTER_POINTS = 5_000


class ChartType(str, Enum):
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    SCATTER = "scatter"
    KPI = "kpi"
    TABLE = "table"


@dataclass
class ChartSpec:
    """What to draw, and why."""

    type: ChartType
    reason: str
    x: str | None = None
    y: list[str] = field(default_factory=list)
    series: str | None = None
    """Column whose values split the data into separate lines or bar groups."""

    alternatives: list[ChartType] = field(default_factory=list)
    """Other types that make sense for this shape - the override menu (F12)."""

    @property
    def is_chart(self) -> bool:
        return self.type not in (ChartType.TABLE, ChartType.KPI)


def _table(reason: str) -> ChartSpec:
    return ChartSpec(type=ChartType.TABLE, reason=reason, alternatives=[])


def _numeric_names(profile: ResultProfile) -> list[str]:
    return [c.name for c in profile.by_kind(ColumnKind.NUMERIC)]


def recommend(profile: ResultProfile) -> ChartSpec:
    """Choose a chart for this result set."""
    if profile.row_count == 0:
        return _table("the query returned no rows")

    numeric = profile.by_kind(ColumnKind.NUMERIC)
    temporal = profile.by_kind(ColumnKind.TEMPORAL)
    categorical = profile.by_kind(ColumnKind.CATEGORICAL) + profile.by_kind(
        ColumnKind.BOOLEAN
    )

    # --- a single number ---
    if profile.row_count == 1 and len(numeric) == 1 and profile.column_count <= 2:
        return ChartSpec(
            type=ChartType.KPI,
            reason="one row with a single number - this is a headline figure",
            y=[numeric[0].name],
            # The label column, when the query returned one alongside the value.
            x=next((c.name for c in categorical), None),
            alternatives=[ChartType.TABLE],
        )

    # --- a series over time ---
    if temporal and numeric:
        period = temporal[0]
        if period.distinct_count < 2:
            return _table("every row falls in the same period - nothing to plot")

        return ChartSpec(
            type=ChartType.LINE,
            reason=(
                f"{period.name} is a date and there "
                f"{'is' if len(numeric) == 1 else 'are'} {len(numeric)} numeric "
                f"column{'' if len(numeric) == 1 else 's'} "
                "- a series over time reads as a line"
            ),
            x=period.name,
            y=_numeric_names(profile),
            # A second categorical column splits the series, e.g. revenue per
            # month *per region*.
            series=categorical[0].name if categorical else None,
            alternatives=[ChartType.BAR, ChartType.TABLE],
        )

    # --- one category against measures ---
    if len(categorical) >= 1 and numeric:
        label = categorical[0]
        if label.distinct_count > MAX_BARS:
            return _table(
                f"{label.name} has {label.distinct_count} distinct values - "
                f"more than the {MAX_BARS} a bar chart can label legibly"
            )

        alternatives = [ChartType.TABLE]
        # Pie only earns a place when the parts genuinely sum to a whole:
        # few slices, one measure, and nothing negative to draw.
        if (
            label.distinct_count <= MAX_PIE_SLICES
            and len(numeric) == 1
            and (numeric[0].minimum or 0) >= 0
        ):
            alternatives.insert(0, ChartType.PIE)

        return ChartSpec(
            type=ChartType.BAR,
            reason=(
                f"{label.name} has {label.distinct_count} distinct values, "
                f"compared across {numeric[0].name}"
            ),
            x=label.name,
            y=_numeric_names(profile),
            series=categorical[1].name if len(categorical) > 1 else None,
            alternatives=alternatives,
        )

    # --- two measures against each other ---
    if len(numeric) >= 2 and not categorical and not temporal:
        if profile.row_count > MAX_SCATTER_POINTS:
            return _table(
                f"{profile.row_count:,} rows - too many points to read as a scatter"
            )
        return ChartSpec(
            type=ChartType.SCATTER,
            reason=(
                f"two numeric columns and nothing to group by - "
                f"{numeric[0].name} against {numeric[1].name}"
            ),
            x=numeric[0].name,
            y=[numeric[1].name],
            alternatives=[ChartType.TABLE],
        )

    if not numeric:
        return _table("no numeric column - there is nothing to measure")

    return _table("the shape of this result does not match any chart rule")


def options(profile: ResultProfile) -> dict[str, list[str]]:
    """Columns the user may pick for each axis in the override (F12).

    The frontend needs this to populate the axis pickers without re-deriving
    the type inference, and it keeps the two from disagreeing about what
    counts as a category.
    """
    return {
        "numeric": _numeric_names(profile),
        "temporal": [c.name for c in profile.by_kind(ColumnKind.TEMPORAL)],
        "categorical": [
            c.name
            for c in profile.by_kind(ColumnKind.CATEGORICAL)
            + profile.by_kind(ColumnKind.BOOLEAN)
        ],
        "all": [c.name for c in profile.columns],
    }


__all__ = [
    "MAX_BARS",
    "MAX_PIE_SLICES",
    "ChartSpec",
    "ChartType",
    "options",
    "recommend",
]
