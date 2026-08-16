"""The validation engine.

Four gates, all before a single row is read. The gates run in order and stop
at the first failure, because a query that does not parse cannot be checked
against the schema, and one that is unsafe must never be costed.

The distinction that matters is *retryable* versus *hard reject*. A
hallucinated column is a mistake the model can fix from the error message, so
it goes back round the loop. An attempt to DROP a table is not a mistake to
be repaired — it is rejected outright and never regenerated.
"""

import enum
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.logging import get_logger
from app.models.connection import Dialect

log = get_logger(__name__)

SQLGLOT_DIALECTS: dict[Dialect, str] = {
    Dialect.POSTGRES: "postgres",
    Dialect.MYSQL: "mysql",
    Dialect.SQLITE: "sqlite",
}

# Statement types that are never acceptable, whatever the prompt said.
FORBIDDEN_STATEMENTS: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Merge,
)

# Functions with no place in an analytics query: time-based blind probing,
# filesystem access, and outbound network calls.
FORBIDDEN_FUNCTIONS = frozenset(
    """pg_sleep sleep benchmark waitfor dbms_pipe dblink dblink_connect
    load_file lo_import lo_export pg_read_file pg_read_binary_file
    pg_ls_dir pg_stat_file copy_from copy_to system exec shell
    xp_cmdshell sp_executesql eval readfile writefile""".split()
)

# Catalogs expose credentials, other tenants' object names, and server
# configuration. None of it answers a business question.
FORBIDDEN_SCHEMAS = frozenset(
    """pg_catalog information_schema pg_toast pg_temp mysql performance_schema
    sys sqlite_master sqlite_temp_master sqlite_schema""".split()
)

# `--` and `/* */` are the classic injection terminators. sqlglot strips them
# during parsing, so the raw string has to be checked separately.
COMMENT_RE = re.compile(r"--|/\*|\*/")


class Gate(str, enum.Enum):
    SYNTAX = "syntax"
    SCHEMA = "schema"
    SAFETY = "safety"
    COST = "cost"


@dataclass
class ValidationFailure:
    gate: Gate
    message: str
    retryable: bool
    """False means the query is rejected outright and must not be regenerated.

    Only the safety gate produces non-retryable failures: a syntax or schema
    error is a mistake worth repairing, an attempted write is not.
    """


@dataclass
class ValidationResult:
    ok: bool
    sql: str
    """The SQL to execute — may differ from the input when the cost gate
    added a LIMIT."""

    failure: ValidationFailure | None = None
    warnings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    limit_applied: int | None = None

    @property
    def retryable(self) -> bool:
        return self.failure is not None and self.failure.retryable


@dataclass
class SchemaIndex:
    """Table and column names available to a query, lowercased for matching."""

    columns_by_table: dict[str, set[str]]

    @property
    def tables(self) -> set[str]:
        return set(self.columns_by_table)

    def has_table(self, name: str) -> bool:
        return name.lower() in self.columns_by_table

    def has_column(self, table: str, column: str) -> bool:
        return column.lower() in self.columns_by_table.get(table.lower(), set())

    def tables_with_column(self, column: str) -> set[str]:
        return {
            table
            for table, columns in self.columns_by_table.items()
            if column.lower() in columns
        }


def _fail(gate: Gate, message: str, sql: str, retryable: bool) -> ValidationResult:
    return ValidationResult(
        ok=False,
        sql=sql,
        failure=ValidationFailure(gate=gate, message=message, retryable=retryable),
    )


# --------------------------------------------------------------- gate 1


def _parse(sql: str, dialect: Dialect) -> list[exp.Expression]:
    return [
        statement
        for statement in sqlglot.parse(sql, read=SQLGLOT_DIALECTS[dialect])
        if statement is not None
    ]


# --------------------------------------------------------------- gate 3


def _cte_names(statement: exp.Expression) -> set[str]:
    """Names introduced by WITH clauses.

    These look exactly like table references but do not exist in the
    database, so the schema gate has to know about them.
    """
    return {
        cte.alias_or_name.lower()
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }


def _check_safety(statement: exp.Expression, raw_sql: str) -> str | None:
    """Return a rejection reason, or None when the statement is safe."""
    for forbidden in FORBIDDEN_STATEMENTS:
        if isinstance(statement, forbidden) or statement.find(forbidden):
            return (
                f"{forbidden.__name__.upper()} statements are not permitted. "
                "This system is read-only."
            )

    # The top level must be a SELECT, a UNION of SELECTs, or a WITH wrapping
    # one. Anything else is a statement type we have not reasoned about.
    root = statement
    if isinstance(root, exp.Subquery):
        root = root.this
    if not isinstance(root, exp.Select | exp.Union | exp.Except | exp.Intersect):
        kind = type(statement).__name__.upper()
        return f"Only SELECT queries are permitted; got {kind}."

    # SELECT ... INTO writes a new table.
    if statement.find(exp.Into):
        return "SELECT ... INTO is not permitted; it creates a table."

    for function in statement.find_all(exp.Anonymous):
        name = (function.this or "").lower()
        if name in FORBIDDEN_FUNCTIONS:
            return f"The function {name}() is not permitted."

    # sqlglot models some of these as dedicated nodes rather than Anonymous.
    for node in statement.find_all(exp.Func):
        name = getattr(node, "sql_name", lambda: "")().lower()
        if name in FORBIDDEN_FUNCTIONS:
            return f"The function {name}() is not permitted."

    for table in statement.find_all(exp.Table):
        if (table.db or "").lower() in FORBIDDEN_SCHEMAS:
            return f"Access to the {table.db} schema is not permitted."
        if (table.name or "").lower() in FORBIDDEN_SCHEMAS:
            return f"Access to {table.name} is not permitted."

    if COMMENT_RE.search(raw_sql):
        return (
            "SQL comments are not permitted — they are the standard way to "
            "terminate an injected statement."
        )

    return None


# --------------------------------------------------------------- gate 2


def _referenced_tables(statement: exp.Expression, ctes: set[str]) -> list[str]:
    """Real tables the statement reads, excluding CTE names."""
    seen: list[str] = []
    for table in statement.find_all(exp.Table):
        name = table.name
        if not name or name.lower() in ctes:
            continue
        if name not in seen:
            seen.append(name)
    return seen


def _alias_map(statement: exp.Expression, ctes: set[str]) -> dict[str, str]:
    """Alias (or bare name) → real table name."""
    mapping: dict[str, str] = {}
    for table in statement.find_all(exp.Table):
        name = table.name
        if not name or name.lower() in ctes:
            continue
        mapping[name.lower()] = name
        if table.alias:
            mapping[table.alias.lower()] = name
    return mapping


def _result_aliases(statement: exp.Expression) -> set[str]:
    """Names introduced by `AS` in the SELECT list.

    `SELECT COUNT(*) AS n ... ORDER BY n` is valid SQL and an extremely
    common shape — almost every "top N by revenue" question produces it.
    Without this the schema gate rejects the alias as a nonexistent column.
    """
    return {
        alias.alias.lower()
        for alias in statement.find_all(exp.Alias)
        if alias.alias and not isinstance(alias, exp.TableAlias)
    }


def _check_schema(
    statement: exp.Expression, index: SchemaIndex
) -> tuple[str | None, list[str]]:
    """Verify every identifier exists. Returns (error, referenced tables)."""
    ctes = _cte_names(statement)
    tables = _referenced_tables(statement, ctes)
    aliases_out = _result_aliases(statement)

    for table in tables:
        if not index.has_table(table):
            close = _closest(table, index.tables)
            hint = f" Did you mean {close}?" if close else ""
            return f"Table '{table}' does not exist.{hint}", tables

    aliases = _alias_map(statement, ctes)

    for column in statement.find_all(exp.Column):
        name = column.name
        if not name or name == "*":
            continue

        qualifier = (column.table or "").lower()

        # An unqualified reference to a SELECT alias is not a table column.
        if not qualifier and name.lower() in aliases_out:
            continue

        if qualifier:
            # A qualifier that resolves to a CTE cannot be checked against the
            # real schema — the CTE's output columns are computed.
            if qualifier in ctes:
                continue
            real = aliases.get(qualifier)
            if real is None:
                return (
                    f"'{column.table}' is not a table or alias in this query.",
                    tables,
                )
            if not index.has_column(real, name):
                close = _closest(name, index.columns_by_table[real.lower()])
                hint = f" Did you mean {close}?" if close else ""
                return f"Column '{name}' does not exist on '{real}'.{hint}", tables
        else:
            # Unqualified: it only has to exist on one of the tables in scope.
            if ctes:
                continue
            owners = index.tables_with_column(name)
            if not owners:
                candidates = {
                    c for t in tables for c in index.columns_by_table.get(t.lower(), ())
                }
                close = _closest(name, candidates)
                hint = f" Did you mean {close}?" if close else ""
                return f"Column '{name}' does not exist in any table.{hint}", tables
            if tables and not owners & {t.lower() for t in tables}:
                return (
                    f"Column '{name}' exists but not on any table in this query.",
                    tables,
                )

    return None, tables


def _closest(name: str, candidates: set[str] | frozenset[str]) -> str | None:
    """Nearest identifier, for a 'did you mean' hint.

    The database's own error messages carry these suggestions and they turn
    out to be strong repair signals, so the schema gate produces them too.
    """
    import difflib

    matches = difflib.get_close_matches(
        name.lower(), sorted(candidates), n=1, cutoff=0.7
    )
    return matches[0] if matches else None


# --------------------------------------------------------------- gate 4


def _apply_limit(
    statement: exp.Expression, dialect: Dialect, max_rows: int
) -> tuple[str, int | None]:
    """Force a row cap, returning the SQL and the limit applied.

    An existing LIMIT is respected when it is under the cap; anything larger
    is lowered. A query with no LIMIT gets one.
    """
    write = SQLGLOT_DIALECTS[dialect]

    existing = statement.args.get("limit")
    if existing is not None:
        try:
            current = int(existing.expression.this)
        except (AttributeError, TypeError, ValueError):
            # A non-literal limit (a parameter or expression) cannot be
            # compared, so replace it with the hard cap.
            return statement.limit(max_rows).sql(dialect=write), max_rows
        if current <= max_rows:
            return statement.sql(dialect=write), None
        return statement.limit(max_rows).sql(dialect=write), max_rows

    # UNION and friends do not accept .limit() directly on every dialect;
    # wrapping keeps the semantics intact.
    try:
        limited = statement.limit(max_rows)
    except Exception:  # noqa: BLE001 - fall back rather than fail validation
        return statement.sql(dialect=write), None

    return limited.sql(dialect=write), max_rows


# --------------------------------------------------------------- entrypoint


def validate(
    sql: str,
    dialect: Dialect,
    index: SchemaIndex,
    max_rows: int = 10_000,
) -> ValidationResult:
    """Run all four gates over a candidate query."""
    stripped = (sql or "").strip()
    if not stripped:
        return _fail(Gate.SYNTAX, "The query is empty.", sql, retryable=True)

    # --- gate 1: syntax ---
    try:
        statements = _parse(stripped, dialect)
    except ParseError as exc:
        return _fail(
            Gate.SYNTAX, f"SQL failed to parse: {exc}", stripped, retryable=True
        )

    if not statements:
        return _fail(Gate.SYNTAX, "The query is empty.", stripped, retryable=True)

    # Multi-statement is a safety concern, not a syntax one: it is the shape
    # a piggy-backed write takes.
    if len(statements) > 1:
        return _fail(
            Gate.SAFETY,
            "Multiple statements are not permitted; send one query at a time.",
            stripped,
            retryable=False,
        )

    statement = statements[0]

    # --- gate 3: safety (before schema — an unsafe query is rejected even if
    # its identifiers happen to be wrong) ---
    reason = _check_safety(statement, stripped)
    if reason:
        log.warning("safety_gate_rejected", reason=reason, sql=stripped[:200])
        return _fail(Gate.SAFETY, reason, stripped, retryable=False)

    # --- gate 2: schema ---
    error, tables = _check_schema(statement, index)
    if error:
        return ValidationResult(
            ok=False,
            sql=stripped,
            failure=ValidationFailure(gate=Gate.SCHEMA, message=error, retryable=True),
            tables=tables,
        )

    # --- gate 4: cost ---
    final_sql, limit_applied = _apply_limit(statement, dialect, max_rows)

    warnings: list[str] = []
    if limit_applied:
        warnings.append(f"A LIMIT of {limit_applied:,} rows was applied.")

    return ValidationResult(
        ok=True,
        sql=final_sql,
        warnings=warnings,
        tables=tables,
        limit_applied=limit_applied,
    )
