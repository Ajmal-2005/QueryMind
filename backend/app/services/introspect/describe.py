"""Natural-language descriptions of tables.

The description is what gets embedded, so it decides whether schema linking
finds the right table. It has to contain the words a user would actually
type: "orders", "purchase", "customer", "revenue" - not just identifiers.

Generation is deterministic and template-based rather than LLM-written. Two
reasons: indexing a 400-table schema would otherwise cost 400 LLM calls, and
a deterministic description makes the retrieval evaluation reproducible.
"""

import re

from app.services.introspect.introspector import TableInfo

# Identifier conventions that carry meaning worth spelling out for the model.
ABBREVIATIONS = {
    "id": "identifier",
    "qty": "quantity",
    "amt": "amount",
    "num": "number",
    "desc": "description",
    "addr": "address",
    "cust": "customer",
    "prod": "product",
    "ref": "reference",
    "cat": "category",
    "org": "organization",
    "acct": "account",
    "txn": "transaction",
    "dt": "date",
    "ts": "timestamp",
    "pct": "percent",
    "avg": "average",
}


def humanize(identifier: str) -> str:
    """Turn ``cust_ref_id_v2`` into ``cust ref identifier v2``.

    Splits snake_case and camelCase, then expands known abbreviations so the
    embedding sees real words.
    """
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", identifier)
    tokens = re.split(r"[\s_\-]+", spaced.lower())
    return " ".join(ABBREVIATIONS.get(t, t) for t in tokens if t)


def describe_table(table: TableInfo) -> str:
    """Compose the indexed description of one table."""
    parts: list[str] = []

    readable = humanize(table.name)
    if readable != table.name:
        parts.append(f"Table `{table.name}` ({readable}).")
    else:
        parts.append(f"Table `{table.name}`.")

    if table.row_estimate is not None:
        parts.append(f"Approximately {table.row_estimate:,} rows.")

    pk = table.primary_key
    if pk:
        parts.append(f"Primary key: {', '.join(pk)}.")

    column_phrases = [
        f"{c.name} ({c.data_type.lower()})" for c in table.columns if not c.fk_target
    ]
    if column_phrases:
        parts.append(f"Columns: {', '.join(column_phrases)}.")

    # Join paths are the single most useful thing to retrieve alongside a
    # table, so they are stated explicitly rather than left implicit.
    for fk in table.foreign_keys:
        local = ", ".join(fk.from_columns)
        remote = ", ".join(fk.to_columns) or "primary key"
        parts.append(f"Joins to `{fk.to_table}` via {local} = {fk.to_table}.{remote}.")

    valued = [
        f"{c.name} is one of [{', '.join(c.sample_values)}]"
        for c in table.columns
        if c.sample_values
    ]
    if valued:
        parts.append("Known values: " + "; ".join(valued) + ".")

    # Repeating the humanized words gives the embedding more natural-language
    # surface to match a question against.
    vocabulary = {humanize(c.name) for c in table.columns}
    if vocabulary:
        parts.append("Concepts: " + ", ".join(sorted(vocabulary)) + ".")

    return " ".join(parts)


def describe_snapshot(tables: list[TableInfo]) -> dict[str, str]:
    """Describe every table, keyed by table name."""
    return {table.name: describe_table(table) for table in tables}
