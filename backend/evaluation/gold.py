"""Reading the ground truth out of a gold query.

Benchmark datasets give a question and the SQL that answers it. They do not
give the table set, which is what schema-linking recall is measured against -
so it is parsed out of the gold SQL here.

Doing this with sqlglot rather than a regex matters more than it looks. A
regex over `FROM (\\w+)` misses every joined table, every CTE reference, and
every subquery, and it happily counts an alias or a CTE *name* as a real
table. Each of those errors inflates recall, because the denominator shrinks.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass
class GoldQuery:
    sql: str
    tables: list[str]
    parsed: bool
    order_matters: bool
    """True when the gold query has an ORDER BY - row order is then part of
    the answer and execution match must respect it."""


def _cte_names(statement: exp.Expression) -> set[str]:
    """Names bound by WITH. These are not base tables and must not count."""
    names: set[str] = set()
    for with_clause in statement.find_all(exp.With):
        for cte in with_clause.expressions:
            if cte.alias:
                names.add(cte.alias.lower())
    return names


def gold_tables(sql: str, dialect: str = "sqlite") -> list[str]:
    """Base tables a query reads, lowercased and deduplicated."""
    try:
        statement = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 - an unparseable gold query has no tables
        return []
    if statement is None:
        return []

    skip = _cte_names(statement)
    found: list[str] = []
    for table in statement.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name or name in skip or name in found:
            continue
        found.append(name)
    return found


def parse_gold(sql: str, dialect: str = "sqlite") -> GoldQuery:
    try:
        statement = sqlglot.parse_one(sql, read=dialect)
        parsed = statement is not None
    except Exception:  # noqa: BLE001
        statement, parsed = None, False

    return GoldQuery(
        sql=sql,
        tables=gold_tables(sql, dialect) if parsed else [],
        parsed=parsed,
        order_matters=bool(statement and statement.args.get("order")),
    )


__all__ = ["GoldQuery", "gold_tables", "parse_gold"]
