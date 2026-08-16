"""Schema-aware starter questions (F23).

The Ask page shipped with four hardcoded starters — "Top 5 products by price"
— which are right for the demo database and wrong for every other one. Point
this at a schema of insurance claims and it offers to rank products that do
not exist.

So the starters are generated from the indexed schema: find the fact table,
find its measures and its dimensions, and phrase the questions those support.
Rule-based, because a wrong suggestion is one click from being ignored and an
LLM call per connection-open is not.

The questions are deliberately answerable. There is no value in suggesting
something the schema cannot support — a starter that fails is worse than no
starter, because the user reasonably concludes the whole product is broken.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema_index import SchemaColumn, SchemaTable

MAX_SUGGESTIONS = 6

# Column names that measure something worth summing.
MEASURE_HINTS = (
    "amount",
    "total",
    "price",
    "cost",
    "revenue",
    "value",
    "spend",
    "quantity",
    "qty",
    "count",
    "score",
    "balance",
    "salary",
    "fee",
)

# Columns that label a row rather than measure it.
LABEL_HINTS = ("name", "title", "label", "category", "type", "status", "region")

DATE_HINTS = ("date", "_at", "time", "created", "updated", "timestamp")

NUMERIC_TYPES = ("int", "float", "double", "decimal", "numeric", "real", "money")
DATE_TYPES = ("date", "time", "timestamp")


@dataclass
class Suggestion:
    question: str
    reason: str
    """Which part of the schema produced it — kept so the UI can explain."""


def _is_numeric(column: SchemaColumn) -> bool:
    kind = (column.data_type or "").lower()
    return any(t in kind for t in NUMERIC_TYPES)


def _is_date(column: SchemaColumn) -> bool:
    kind = (column.data_type or "").lower()
    name = column.column_name.lower()
    # SQLite stores dates as TEXT, so the name is the only signal there.
    return any(t in kind for t in DATE_TYPES) or any(h in name for h in DATE_HINTS)


def _humanise(name: str) -> str:
    """`total_amount` → `total amount`, `createdAt` → `created at`."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return spaced.replace("_", " ").strip().lower()


def _measure_phrase(column: SchemaColumn) -> str:
    """`total_amount` → `total amount`, not `total total amount`.

    Column names frequently already carry the aggregate word, and the naive
    template reads like a stutter.
    """
    label = _humanise(column.column_name)
    if label.split()[0] in ("total", "sum", "count", "average", "avg", "number"):
        return label
    return f"total {label}"


def _measure(columns: list[SchemaColumn]) -> SchemaColumn | None:
    named = [
        c
        for c in columns
        if _is_numeric(c)
        and not c.is_pk
        and not c.fk_target
        and any(h in c.column_name.lower() for h in MEASURE_HINTS)
    ]
    if named:
        return named[0]
    # Fall back to any non-key number: an unhelpfully named measure still
    # beats offering nothing.
    plain = [c for c in columns if _is_numeric(c) and not c.is_pk and not c.fk_target]
    return plain[0] if plain else None


def _label(columns: list[SchemaColumn]) -> SchemaColumn | None:
    for hint in LABEL_HINTS:
        for column in columns:
            if hint in column.column_name.lower() and not _is_numeric(column):
                return column
    return None


def _date(columns: list[SchemaColumn]) -> SchemaColumn | None:
    return next((c for c in columns if _is_date(c)), None)


def suggest(
    db: Session, connection_id: str, limit: int = MAX_SUGGESTIONS
) -> list[Suggestion]:
    """Starter questions this schema can actually answer."""
    tables = list(
        db.scalars(
            select(SchemaTable).where(SchemaTable.connection_id == connection_id)
        )
    )
    if not tables:
        return []

    # Biggest table first — row estimates are the cheapest available proxy for
    # "which of these is the fact table anyone cares about".
    tables.sort(key=lambda t: t.row_estimate or 0, reverse=True)
    suggestions: list[Suggestion] = []

    for table in tables:
        if len(suggestions) >= limit:
            break

        columns = list(table.columns)
        name = _humanise(table.table_name)
        measure = _measure(columns)
        label = _label(columns)
        date = _date(columns)

        if measure and date:
            suggestions.append(
                Suggestion(
                    question=f"What is {_measure_phrase(measure)} by month?",
                    reason=(
                        f"{table.table_name} has a measure "
                        f"({measure.column_name}) and a date ({date.column_name})"
                    ),
                )
            )
        if measure and label:
            suggestions.append(
                Suggestion(
                    question=(
                        f"Top 5 {_humanise(label.column_name)} by "
                        f"{_humanise(measure.column_name)}"
                    ),
                    reason=(
                        f"{table.table_name} can be grouped by "
                        f"{label.column_name} and ranked by {measure.column_name}"
                    ),
                )
            )
        if not measure and not label:
            suggestions.append(
                Suggestion(
                    question=f"How many {name} are there?",
                    reason=f"{table.table_name} has no obvious measure to summarise",
                )
            )

    # A count of the largest table always works and is the cheapest possible
    # proof to a new user that the thing is wired up at all.
    biggest = tables[0]
    suggestions.insert(
        0,
        Suggestion(
            question=f"How many {_humanise(biggest.table_name)} are there?",
            reason=f"{biggest.table_name} is the largest indexed table",
        ),
    )

    seen: set[str] = set()
    unique: list[Suggestion] = []
    for suggestion in suggestions:
        key = suggestion.question.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(suggestion)

    return unique[:limit]


__all__ = ["Suggestion", "suggest"]
