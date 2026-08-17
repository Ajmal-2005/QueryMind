"""Predictors: the thing being measured.

Phase 0 left a stub here with a note saying the pipeline did not exist yet.
It does now, and `pipeline_predictor` calls it - the real one, with the real
gates and the real execution, so the harness measures the system rather than a
sketch of it.

Two things this module is careful about:

**Gold execution.** Execution accuracy compares result sets, so the gold query
has to run too. It goes through the same read-only sandbox as the prediction;
a benchmark is not a reason to open a write path.

**Honest labelling.** `describe()` reports which provider answered. Without an
`ANTHROPIC_API_KEY` the pipeline falls back to a stub that ignores the
question, and a 0% score from that is a stub baseline, not an accuracy figure.
Every saved result carries the provider name so no run can be misreported.
"""

from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import settings
from app.models.connection import Connection
from app.services.connection.manager import create_target_engine
from app.services.generation import pipeline
from app.services.generation.llm import LLMClient
from evaluation import datasets
from evaluation.gold import parse_gold
from evaluation.harness import Bench
from evaluation.metrics import EvalRecord, execution_match, schema_linking_recall
from evaluation.taxonomy import classify


@dataclass
class PredictorInfo:
    """What produced a set of results - recorded alongside every run."""

    provider: str
    model: str
    embedder: str
    live_model: bool
    """False when the stub answered, which makes every accuracy figure a
    stub baseline rather than a measurement."""

    def as_lines(self) -> list[str]:
        return [
            f"  provider              {self.provider}",
            f"  model                 {self.model}",
            f"  embedder              {self.embedder}",
            "  live model            "
            + ("yes" if self.live_model else "NO - stub baseline"),
        ]


def describe(bench: Bench, client: LLMClient | None = None) -> PredictorInfo:
    from app.services.generation.llm import get_client

    resolved = client or get_client()
    name = getattr(resolved, "name", "unknown")
    return PredictorInfo(
        provider=name,
        model=getattr(resolved, "model", name),
        embedder=bench.embedder,
        live_model=name == "anthropic",
    )


def run_gold(connection: Connection, sql: str) -> list[tuple] | None:
    """Execute a gold query read-only, or None if it cannot run."""
    engine = create_target_engine(connection)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(sql)).fetchmany(10_001)]
    except Exception:  # noqa: BLE001 - a gold query that will not run is data,
        # not a crash: some benchmark rows are simply broken.
        return None
    finally:
        engine.dispose()


def pipeline_predictor(
    bench: Bench,
    client: LLMClient | None = None,
    max_attempts: int | None = None,
    top_k: int | None = None,
    hops: int | None = None,
    mode: str = "hybrid",
):
    """Build a predictor bound to a live indexed connection.

    ``top_k``, ``hops`` and ``mode`` exist for the ablation study; leaving them
    unset runs the configuration the product ships with.
    """

    def predict(example: datasets.BenchmarkExample) -> EvalRecord:
        gold = parse_gold(example.gold_sql)

        outcome = pipeline.run(
            db=bench.db,
            connection=bench.connection,
            question=example.question,
            user_id=bench.user_id,
            client=client,
            max_attempts=max_attempts or settings.MAX_CORRECTION_ATTEMPTS,
            # Benchmark rows are not a conversation, and persisting 1,034 of
            # them would poison the few-shot pool for the next run.
            persist=False,
            retrieval_top_k=top_k,
            retrieval_hops=hops,
            retrieval_mode=mode,
        )

        predicted_sql = (
            outcome.validation.sql
            if outcome.validation and outcome.validation.ok
            else (outcome.generation.sql if outcome.generation else None)
        )
        retrieved = outcome.retrieval.table_names if outcome.retrieval else []

        correct = False
        if outcome.succeeded and outcome.execution is not None:
            gold_rows = run_gold(bench.connection, example.gold_sql)
            correct = execution_match(
                [tuple(r) for r in outcome.execution.rows],
                gold_rows,
                order_matters=gold.order_matters,
            )

        record = EvalRecord(
            question_id=example.question_id,
            question=example.question,
            db_id=example.db_id,
            gold_sql=example.gold_sql,
            predicted_sql=predicted_sql,
            correct=correct,
            executed=outcome.succeeded,
            error=outcome.error,
            correction_attempts=outcome.correction_attempts,
            recovered_by_correction=outcome.recovered_by_correction,
            retrieved_tables=retrieved,
            gold_tables=gold.tables,
            latency_ms=outcome.stage_timings.get("total", 0.0),
            tokens_used=(outcome.generation.total_tokens if outcome.generation else 0),
        )
        record.error_category = classify(record)
        return record

    return predict


def retrieval_only_predictor(
    bench: Bench,
    top_k: int | None = None,
    hops: int | None = None,
    mode: str = "hybrid",
):
    """Measure schema linking without calling a model at all.

    This is the part of the system that can be evaluated honestly with no API
    key, and it is the part research question 1 asks about. Recall here is a
    real measurement, not a placeholder.
    """
    from app.services.linking.retriever import DEFAULT_HOPS, DEFAULT_TOP_K, retrieve

    def predict(example: datasets.BenchmarkExample) -> EvalRecord:
        gold = parse_gold(example.gold_sql)
        result = retrieve(
            bench.db,
            bench.connection.id,
            example.question,
            top_k=DEFAULT_TOP_K if top_k is None else top_k,
            hops=DEFAULT_HOPS if hops is None else hops,
            mode=mode,
        )
        retrieved = result.table_names

        return EvalRecord(
            question_id=example.question_id,
            question=example.question,
            db_id=example.db_id,
            gold_sql=example.gold_sql,
            predicted_sql=None,
            # "Correct" for a retrieval-only run means every gold table was
            # found. Execution accuracy is not defined without a model, and
            # reporting it as 0% here would be misleading.
            correct=schema_linking_recall(retrieved, gold.tables) == 1.0,
            executed=False,
            retrieved_tables=retrieved,
            gold_tables=gold.tables,
            latency_ms=result.duration_ms,
            error=None if gold.tables else "gold SQL had no parseable tables",
            error_category=None if gold.tables else "unparseable_gold",
        )

    return predict


__all__ = [
    "PredictorInfo",
    "describe",
    "pipeline_predictor",
    "retrieval_only_predictor",
    "run_gold",
]
