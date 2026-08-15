"""Prompt construction for SQL generation.

Renders the retrieved schema subgraph as DDL — models have seen far more
`CREATE TABLE` than any prose schema format — and layers dialect rules,
resolved time windows, and similar past examples on top.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Dialect
from app.models.schema_index import SchemaColumn, SchemaTable
from app.services.generation.intent import Intent, QuestionType
from app.services.linking.retriever import RetrievalResult

MAX_SAMPLE_VALUES = 8

DIALECT_RULES: dict[Dialect, str] = {
    Dialect.POSTGRES: """- Target PostgreSQL 16.
- Quote identifiers with double quotes only when they need it (mixed case or
  reserved words).
- Use DATE_TRUNC('month', col) for period grouping and INTERVAL arithmetic for
  relative dates.
- String matching is case-sensitive; use ILIKE for case-insensitive matching.
- Integer division truncates — cast to numeric before dividing to get a
  fraction.""",
    Dialect.MYSQL: """- Target MySQL 8.
- Quote identifiers with backticks when they need it.
- Use DATE_FORMAT(col, '%Y-%m-01') or DATE_SUB(...) for period grouping;
  MySQL has no DATE_TRUNC.
- String comparison is case-insensitive by default under the usual collations.
- Window functions are available (8.0+); CTEs with WITH are available.""",
    Dialect.SQLITE: """- Target SQLite 3.
- Quote identifiers with double quotes when they need it.
- Dates are stored as ISO-8601 text; use strftime('%Y-%m', col) for period
  grouping and date(col, '-30 days') for relative windows. There is no
  DATE_TRUNC or INTERVAL.
- There is no full outer join and no RIGHT JOIN; rewrite using LEFT JOIN.
- Division of two integers yields an integer; multiply by 1.0 to force a real
  result.""",
}

SYSTEM_PROMPT = """You translate natural-language questions into a single \
read-only SQL SELECT statement.

Rules, in order of priority:

1. Emit exactly one statement. It must be a SELECT (a leading WITH is fine).
   Never emit INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, GRANT, TRUNCATE, or
   multiple statements separated by semicolons.
2. Use only the tables and columns given in the schema below. Do not invent an
   identifier because it seems like it ought to exist — if the schema cannot
   answer the question, say so in `assumptions` and return your closest attempt.
3. Join only along the foreign-key relationships stated in the schema.
4. Prefer explicit JOIN ... ON over comma joins, and qualify every column with
   its table alias when more than one table is involved.
5. When the question implies a ranking or a "top N", include ORDER BY and LIMIT.
6. Return a result a person can read: name aggregate columns with AS, and do
   not select more columns than the question calls for.

Answer with the SQL, a confidence score, a plain-English explanation aimed at \
someone who does not read SQL, and any assumptions you had to make. Be honest \
in `confidence`: a low score on a genuinely ambiguous question is more useful \
than false certainty."""


@dataclass
class BuiltPrompt:
    system: str
    user: str
    table_names: list[str]

    @property
    def approx_tokens(self) -> int:
        """Rough size estimate for logging and cost budgeting.

        Deliberately crude — the real count comes from the provider's usage
        field; this only needs to be good enough to spot a prompt that has
        grown out of control.
        """
        return (len(self.system) + len(self.user)) // 4


def _render_column(column: SchemaColumn) -> str:
    parts = [f"  {column.column_name} {column.data_type}"]

    if column.is_pk:
        parts.append("PRIMARY KEY")
    if not column.is_nullable:
        parts.append("NOT NULL")
    if column.fk_target:
        table, _, col = column.fk_target.partition(".")
        parts.append(f"REFERENCES {table}({col})")

    line = " ".join(parts)

    if column.sample_values:
        shown = column.sample_values[:MAX_SAMPLE_VALUES]
        values = ", ".join(repr(str(v)) for v in shown)
        suffix = ", ..." if len(column.sample_values) > len(shown) else ""
        line += f"  -- values: {values}{suffix}"

    return line


def render_schema(db: Session, connection_id: str, table_names: list[str]) -> str:
    """Render the retrieved subgraph as CREATE TABLE statements."""
    if not table_names:
        return "-- no tables matched this question"

    tables = list(
        db.scalars(
            select(SchemaTable).where(
                SchemaTable.connection_id == connection_id,
                SchemaTable.table_name.in_(table_names),
            )
        )
    )
    # Preserve retrieval order — the most relevant table should be read first.
    order = {name: i for i, name in enumerate(table_names)}
    tables.sort(key=lambda t: order.get(t.table_name, len(order)))

    blocks = []
    for table in tables:
        header = f"CREATE TABLE {table.table_name} ("
        columns = ",\n".join(_render_column(c) for c in table.columns)
        footer = ");"
        if table.row_estimate is not None:
            footer += f"  -- approximately {table.row_estimate:,} rows"
        blocks.append(f"{header}\n{columns}\n{footer}")

    return "\n\n".join(blocks)


def _render_examples(examples: list[tuple[str, str]]) -> str:
    if not examples:
        return ""
    rendered = "\n\n".join(
        f"Question: {question}\nSQL: {sql}" for question, sql in examples
    )
    return f"\n\nExamples of correct SQL for this database:\n\n{rendered}"


def build(
    db: Session,
    connection_id: str,
    question: str,
    intent: Intent,
    retrieval: RetrievalResult,
    dialect: Dialect,
    examples: list[tuple[str, str]] | None = None,
    error_feedback: str | None = None,
    previous_sql: str | None = None,
) -> BuiltPrompt:
    """Assemble the generation prompt.

    ``error_feedback`` and ``previous_sql`` drive the phase 3 self-correction
    loop; on a first attempt both are absent.
    """
    table_names = retrieval.table_names
    schema = render_schema(db, connection_id, table_names)

    sections = [
        f"Database dialect rules:\n{DIALECT_RULES[dialect]}",
        f"Schema (only these tables and columns exist):\n\n{schema}",
    ]

    edges = sorted(
        {
            (min(a, b), max(a, b))
            for a, neighbours in retrieval.graph.adjacency.items()
            for b in neighbours
            if a in table_names and b in table_names
        }
    )
    if edges:
        joins = "\n".join(f"- {a} joins to {b}" for a, b in edges)
        sections.append(f"Valid join paths between these tables:\n{joins}")

    if intent.time_windows:
        windows = "\n".join(f"- {w}" for w in intent.time_windows)
        sections.append(
            "Interpret the relative dates in the question as follows:\n" + windows
        )

    if intent.limit_hint:
        sections.append(
            f"The question asks for {intent.limit_hint} rows — "
            f"use LIMIT {intent.limit_hint}."
        )
    elif intent.wants_ordering:
        sections.append(
            "The question implies an ordering; include ORDER BY, and a LIMIT if "
            "it asks for a 'top' or 'bottom' subset."
        )

    if intent.question_type is not QuestionType.AMBIGUOUS:
        sections.append(f"Question type: {intent.question_type.value}.")

    if examples:
        sections.append(_render_examples(examples).strip())

    if previous_sql and error_feedback:
        sections.append(
            "Your previous attempt failed. Fix it.\n\n"
            f"Previous SQL:\n{previous_sql}\n\n"
            f"Error reported by the database:\n{error_feedback}\n\n"
            "Return corrected SQL. Do not repeat the same mistake."
        )

    sections.append(f"Question: {intent.resolved_question}")

    return BuiltPrompt(
        system=SYSTEM_PROMPT,
        user="\n\n".join(sections),
        table_names=table_names,
    )
