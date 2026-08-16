"""Error taxonomy over benchmark failures.

The proposal asks for failures to be categorised: wrong table, wrong column,
wrong join, wrong aggregation, wrong filter, wrong ordering, ambiguous,
unanswerable. A single accuracy number says how often the system is wrong; the
taxonomy says *how*, which is the part that tells you what to fix.

Classification is structural — it compares the predicted statement against the
gold one clause by clause — and it is ordered, because a query that used the
wrong table also has the wrong columns, and reporting that as a column error
would send you looking in the wrong place. The first category that matches
wins, and they are ordered from most to least fundamental.

A caveat worth carrying into the report: two SQL queries can be written very
differently and mean the same thing. This classifier compares surface
structure, so it will occasionally label a *correct* alternative formulation
as a difference. It is therefore only ever applied to queries already known to
be wrong, where the question is not "is this wrong" but "in what way".
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Ordered most to least fundamental. The first match wins.
CATEGORIES = (
    "not_generated",
    "rejected_unsafe",
    "invalid_sql",
    "execution_failed",
    "wrong_table",
    "wrong_join",
    "wrong_aggregation",
    "wrong_filter",
    "wrong_column",
    "wrong_ordering",
    "wrong_result",
)

DESCRIPTIONS = {
    "not_generated": "No SQL was produced — the provider failed or declined.",
    "rejected_unsafe": "A safety gate refused the query outright.",
    "invalid_sql": "The SQL did not parse or referenced unknown identifiers.",
    "execution_failed": "The SQL was valid but the database refused to run it.",
    "wrong_table": "Reads a different set of tables than the gold query.",
    "wrong_join": "Same tables, different join structure.",
    "wrong_aggregation": "Different aggregate functions or grouping keys.",
    "wrong_filter": "Different WHERE conditions.",
    "wrong_column": "Different columns projected.",
    "wrong_ordering": "Different ORDER BY or LIMIT.",
    "wrong_result": "Structurally similar but the rows do not match.",
    "unparseable_gold": "The benchmark's own gold SQL could not be parsed.",
}


@dataclass
class _Shape:
    """The parts of a query the taxonomy compares."""

    tables: set[str]
    columns: set[str]
    aggregates: set[str]
    group_keys: set[str]
    filters: set[str]
    joins: set[str]
    ordering: set[str]
    limit: str | None


def _shape(sql: str, dialect: str = "sqlite") -> _Shape | None:
    try:
        statement = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001
        return None
    if statement is None:
        return None

    def _normalise(node) -> str:
        # Aliases differ freely between two correct queries; the column they
        # point at does not.
        return node.sql(comments=False).lower().replace('"', "").replace("`", "")

    group = statement.args.get("group")
    order = statement.args.get("order")
    where = statement.args.get("where")
    limit = statement.args.get("limit")

    return _Shape(
        tables={(t.name or "").lower() for t in statement.find_all(exp.Table)},
        columns={_normalise(c) for c in statement.find_all(exp.Column)},
        aggregates={f.sql_name().upper() for f in statement.find_all(exp.AggFunc)},
        group_keys={_normalise(e) for e in (group.expressions if group else [])},
        filters={
            _normalise(c)
            for c in (where.find_all(exp.Condition) if where else [])
            if isinstance(c, exp.Binary)
        },
        joins={
            (j.this.name or "").lower()
            for j in statement.find_all(exp.Join)
            if isinstance(j.this, exp.Table)
        },
        ordering={_normalise(e) for e in (order.expressions if order else [])},
        limit=_normalise(limit) if limit is not None else None,
    )


def classify(record) -> str | None:
    """Name the way a failed prediction differs from the gold query.

    Returns None when the prediction was correct — there is nothing to
    classify about a right answer.
    """
    if record.correct:
        return None

    if not record.predicted_sql:
        return "not_generated"

    error = (record.error or "").lower()
    if "gate" in error and ("safety" in error or "refused" in error):
        return "rejected_unsafe"

    predicted = _shape(record.predicted_sql)
    if predicted is None:
        return "invalid_sql"

    gold = _shape(record.gold_sql)
    if gold is None:
        return "unparseable_gold"

    if not record.executed:
        # It parsed here but the database would not run it: a hallucinated
        # identifier, a type mismatch, an impossible join.
        return "execution_failed" if record.error else "invalid_sql"

    if predicted.tables != gold.tables:
        return "wrong_table"
    if predicted.joins != gold.joins:
        return "wrong_join"
    if (
        predicted.aggregates != gold.aggregates
        or predicted.group_keys != gold.group_keys
    ):
        return "wrong_aggregation"
    if predicted.filters != gold.filters:
        return "wrong_filter"
    if predicted.columns != gold.columns:
        return "wrong_column"
    if predicted.ordering != gold.ordering or predicted.limit != gold.limit:
        return "wrong_ordering"

    # Every clause we compare agrees, and the rows still disagree. Usually a
    # DISTINCT, a NULL-handling difference, or a subquery we do not inspect.
    return "wrong_result"


def tally(records) -> dict[str, int]:
    """Failure counts by category, most common first."""
    counts: dict[str, int] = {}
    for record in records:
        category = record.error_category
        if category:
            counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def as_table(counts: dict[str, int]) -> str:
    if not counts:
        return "  (no failures to categorise)"

    total = sum(counts.values())
    width = max(len(c) for c in counts)
    lines = []
    for category, count in counts.items():
        share = count / total
        bar = "#" * round(share * 24)
        lines.append(f"  {category:<{width}}  {count:>4}  {share:>6.1%}  {bar}")
        lines.append(f"  {'':<{width}}        {DESCRIPTIONS.get(category, '')}")
    return "\n".join(lines)


__all__ = ["CATEGORIES", "DESCRIPTIONS", "as_table", "classify", "tally"]
