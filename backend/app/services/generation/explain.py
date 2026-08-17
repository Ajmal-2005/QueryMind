"""Query explanation (F21): what the SQL actually does, clause by clause.

The generation already returns a prose `explanation`, but that is the model's
account of its own work - it describes what the model *meant*, and on the
occasions the SQL does something else the explanation follows the intention
rather than the query. This module reads the parsed statement instead, so it
cannot drift from what will run.

That distinction is the point of the feature. The user gets two independent
descriptions: the model's, and one derived mechanically from the SQL. Where
they disagree, something is wrong, and the reader can see it.

No LLM call. Walking a sqlglot AST is deterministic, instant, and free.
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.core.logging import get_logger
from app.models.connection import Dialect

log = get_logger(__name__)

DIALECT_NAMES: dict[Dialect, str] = {
    Dialect.POSTGRES: "postgres",
    Dialect.MYSQL: "mysql",
    Dialect.SQLITE: "sqlite",
}

# Aggregate functions get named in plain English rather than left as SQL.
AGGREGATE_PHRASING: dict[str, str] = {
    "SUM": "adds up",
    "COUNT": "counts",
    "AVG": "averages",
    "MIN": "takes the smallest",
    "MAX": "takes the largest",
}


@dataclass
class Step:
    """One clause, in the order the database conceptually evaluates it."""

    order: int
    clause: str
    """The SQL keyword this step corresponds to - FROM, WHERE, GROUP BY…"""

    title: str
    detail: str
    sql: str = ""
    """The fragment of the query this step describes, for highlighting."""


@dataclass
class Explanation:
    steps: list[Step] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    aggregates: list[str] = field(default_factory=list)
    row_limit: int | None = None
    is_aggregate: bool = False
    parsed: bool = True
    """False when the SQL could not be parsed; `steps` is then empty."""

    @property
    def summary(self) -> str:
        """One sentence describing the whole query."""
        if not self.parsed:
            return "This query could not be parsed for a step-by-step reading."

        source = " and ".join(self.tables) if self.tables else "the database"
        if self.is_aggregate:
            return f"Summarises data from {source}."
        return f"Lists rows from {source}."


def _table_names(statement: exp.Expression) -> list[str]:
    names: list[str] = []
    for table in statement.find_all(exp.Table):
        name = table.name
        if name and name not in names:
            names.append(name)
    return names


def _describe_condition(condition: exp.Expression) -> str:
    """Render a WHERE/HAVING predicate as something readable.

    Deliberately shallow: the goal is to make the shape of the filter obvious,
    not to translate arbitrary boolean algebra into English. A complex
    predicate is shown as SQL, which an analyst reads faster than a paragraph.
    """
    parts: list[str] = []
    for comparison in condition.find_all(
        exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.In, exp.Between
    ):
        parts.append(comparison.sql())
        if len(parts) >= 4:
            break
    return "; ".join(parts) or condition.sql()


def _join_steps(statement: exp.Expression, start: int) -> list[Step]:
    steps: list[Step] = []
    for join in statement.find_all(exp.Join):
        table = join.this
        name = table.name if isinstance(table, exp.Table) else table.sql()
        kind = (join.side or join.kind or "inner").lower()
        condition = join.args.get("on")

        steps.append(
            Step(
                order=start + len(steps),
                clause="JOIN",
                title=f"Join {name}",
                detail=(
                    f"Matches rows against {name}"
                    + (f" where {condition.sql()}" if condition else "")
                    + (
                        ", keeping rows with no match on the other side"
                        if kind in ("left", "right", "full")
                        else ""
                    )
                    + "."
                ),
                sql=join.sql(),
            )
        )
    return steps


def explain(sql: str, dialect: Dialect = Dialect.SQLITE) -> Explanation:
    """Describe a SELECT statement clause by clause.

    Never raises: an explanation is a reading aid on a query the user already
    has, so a parse failure degrades to "no walkthrough available" rather than
    taking the answer down with it.
    """
    try:
        statement = sqlglot.parse_one(sql, read=DIALECT_NAMES.get(dialect, "sqlite"))
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same outcome
        log.warning("explanation_parse_failed", error=str(exc)[:120])
        return Explanation(parsed=False)

    if statement is None:
        return Explanation(parsed=False)

    explanation = Explanation(tables=_table_names(statement))
    order = 1

    # Presented in evaluation order - FROM before SELECT - because that is the
    # order that makes a query make sense, and it is not the order it is
    # written in. Readers who have only ever seen the written order usually
    # find this the most useful part.
    source = statement.args.get("from")
    if source:
        origin = (
            source.this.name if isinstance(source.this, exp.Table) else "the source"
        )
        explanation.steps.append(
            Step(
                order=order,
                clause="FROM",
                title=f"Start with {origin}",
                detail="Reads every row from this table as the starting set.",
                sql=source.sql(),
            )
        )
        order += 1

    joins = _join_steps(statement, order)
    explanation.steps.extend(joins)
    order += len(joins)

    where = statement.args.get("where")
    if where:
        explanation.steps.append(
            Step(
                order=order,
                clause="WHERE",
                title="Keep only matching rows",
                detail=(
                    "Discards every row except where "
                    f"{_describe_condition(where.this)}."
                ),
                sql=where.sql(),
            )
        )
        order += 1

    group = statement.args.get("group")
    if group:
        keys = [e.sql() for e in group.expressions]
        explanation.is_aggregate = True
        explanation.steps.append(
            Step(
                order=order,
                clause="GROUP BY",
                title=f"Collapse into one row per {', '.join(keys)}",
                detail=(
                    "Rows sharing the same value are folded together so the "
                    "aggregates below are computed per group."
                ),
                sql=group.sql(),
            )
        )
        order += 1

    having = statement.args.get("having")
    if having:
        explanation.steps.append(
            Step(
                order=order,
                clause="HAVING",
                title="Drop groups that do not qualify",
                detail=(
                    "Filters the grouped rows - unlike WHERE, which filtered "
                    f"before grouping: {_describe_condition(having.this)}."
                ),
                sql=having.sql(),
            )
        )
        order += 1

    # SELECT list, described last-but-one because that is when it is evaluated.
    projections = statement.expressions if isinstance(statement, exp.Select) else []
    if projections:
        described: list[str] = []
        for projection in projections:
            alias = projection.alias if isinstance(projection, exp.Alias) else None
            inner = projection.this if isinstance(projection, exp.Alias) else projection

            if isinstance(inner, exp.Star):
                described.append("every column")
                continue

            function = next(
                (f for f in inner.find_all(exp.AggFunc) if isinstance(f, exp.AggFunc)),
                None,
            )
            if function is not None:
                explanation.is_aggregate = True
                name = function.sql_name().upper()
                explanation.aggregates.append(name)
                verb = AGGREGATE_PHRASING.get(name, name.lower())
                target = (
                    "the rows"
                    if isinstance(function.this, exp.Star) or function.this is None
                    else function.this.sql()
                )
                described.append(
                    f"{verb} {target}" + (f", as {alias}" if alias else "")
                )
            else:
                label = alias or inner.sql()
                described.append(label)
                explanation.columns.append(label)

        explanation.steps.append(
            Step(
                order=order,
                clause="SELECT",
                title="Produce the output columns",
                detail="Returns " + ", ".join(described) + ".",
                sql=", ".join(p.sql() for p in projections),
            )
        )
        order += 1

    ordering = statement.args.get("order")
    if ordering:
        described = []
        for item in ordering.expressions:
            direction = "highest first" if item.args.get("desc") else "lowest first"
            described.append(f"{item.this.sql()} ({direction})")
        explanation.steps.append(
            Step(
                order=order,
                clause="ORDER BY",
                title="Sort the result",
                detail="Orders by " + ", ".join(described) + ".",
                sql=ordering.sql(),
            )
        )
        order += 1

    limit = statement.args.get("limit")
    if limit is not None:
        try:
            explanation.row_limit = int(limit.expression.name)
        except (AttributeError, ValueError):
            explanation.row_limit = None
        explanation.steps.append(
            Step(
                order=order,
                clause="LIMIT",
                title=(
                    f"Return at most {explanation.row_limit:,} rows"
                    if explanation.row_limit
                    else "Cap the number of rows"
                ),
                detail=(
                    "Everything past this point is discarded - a different "
                    "sort order would return different rows."
                ),
                sql=limit.sql(),
            )
        )

    return explanation


__all__ = ["Explanation", "Step", "explain"]
