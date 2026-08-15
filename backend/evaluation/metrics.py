"""Text-to-SQL evaluation metrics.

These are the numbers reported in section 9 of the proposal. They are pure
functions over already-computed results so the harness can be tested without
a database or an LLM.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

Row = Sequence[Any]


def _normalize_row(row: Row) -> tuple[str, ...]:
    """Render a row as comparable strings.

    Databases disagree on numeric types across dialects (``Decimal('3')``
    vs ``3`` vs ``3.0``), so compare on a canonical string form instead.
    """
    normalized = []
    for value in row:
        if value is None:
            normalized.append("\x00NULL")
        elif isinstance(value, bool):
            normalized.append(str(value))
        elif isinstance(value, int | float):
            as_float = float(value)
            # Collapse 3.0 and 3 to the same token.
            normalized.append(
                str(int(as_float)) if as_float.is_integer() else repr(as_float)
            )
        else:
            normalized.append(str(value).strip())
    return tuple(normalized)


def execution_match(
    predicted: list[Row] | None,
    gold: list[Row] | None,
    order_matters: bool = False,
) -> bool:
    """Do two result sets agree?

    ``order_matters`` should be True only when the gold query has an
    ORDER BY; otherwise row order is not part of the answer.
    """
    if predicted is None or gold is None:
        return False

    pred_rows = [_normalize_row(r) for r in predicted]
    gold_rows = [_normalize_row(r) for r in gold]

    if len(pred_rows) != len(gold_rows):
        return False

    if order_matters:
        return pred_rows == gold_rows
    return sorted(pred_rows) == sorted(gold_rows)


@dataclass
class EvalRecord:
    """One benchmark question and what the system did with it."""

    question_id: str
    question: str
    db_id: str
    gold_sql: str
    predicted_sql: str | None = None
    correct: bool = False
    executed: bool = False
    error: str | None = None
    correction_attempts: int = 0
    recovered_by_correction: bool = False
    retrieved_tables: list[str] = field(default_factory=list)
    gold_tables: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    tokens_used: int = 0
    error_category: str | None = None


@dataclass
class EvalSummary:
    total: int
    execution_accuracy: float
    valid_sql_rate: float
    schema_linking_recall: float
    correction_recovery_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    total_tokens: int

    def as_table(self) -> str:
        return "\n".join(
            [
                f"  questions             {self.total}",
                f"  execution accuracy    {self.execution_accuracy:.1%}",
                f"  valid SQL rate        {self.valid_sql_rate:.1%}",
                f"  schema-linking recall {self.schema_linking_recall:.1%}",
                f"  correction recovery   {self.correction_recovery_rate:.1%}",
                f"  latency p50/p95/p99   {self.latency_p50_ms:.0f} / "
                f"{self.latency_p95_ms:.0f} / {self.latency_p99_ms:.0f} ms",
                f"  tokens                {self.total_tokens:,}",
            ]
        )


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Avoids a numpy dependency in the harness."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(pct / 100 * len(ordered))))
    return ordered[rank - 1]


def schema_linking_recall(retrieved: Sequence[str], gold: Sequence[str]) -> float:
    """Fraction of gold-required tables present in the retrieved set.

    A question needing no tables is vacuously fully recalled.
    """
    gold_set = {t.lower() for t in gold}
    if not gold_set:
        return 1.0
    retrieved_set = {t.lower() for t in retrieved}
    return len(gold_set & retrieved_set) / len(gold_set)


def summarize(records: Sequence[EvalRecord]) -> EvalSummary:
    total = len(records)
    if total == 0:
        return EvalSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    correct = sum(1 for r in records if r.correct)
    executed = sum(1 for r in records if r.executed)

    recalls = [
        schema_linking_recall(r.retrieved_tables, r.gold_tables)
        for r in records
        if r.gold_tables
    ]

    # Recovery rate is over questions that needed a correction, not over all.
    attempted_correction = [r for r in records if r.correction_attempts > 0]
    recovered = sum(1 for r in attempted_correction if r.recovered_by_correction)

    latencies = [r.latency_ms for r in records]

    return EvalSummary(
        total=total,
        execution_accuracy=correct / total,
        valid_sql_rate=executed / total,
        schema_linking_recall=sum(recalls) / len(recalls) if recalls else 0.0,
        correction_recovery_rate=(
            recovered / len(attempted_correction) if attempted_correction else 0.0
        ),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
        total_tokens=sum(r.tokens_used for r in records),
    )
