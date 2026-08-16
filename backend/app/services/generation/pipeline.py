"""Generate → validate → execute, with self-correction.

The loop the proposal's research question 2 asks about: when a query fails,
does feeding the database's own error message back to the model recover a
meaningful fraction of them?

The database's errors are unusually good repair signals because they are
specific — "no such column: cust_name" rather than "query failed" — and the
schema gate deliberately produces messages in the same shape, with a "did you
mean" hint, so a validation failure repairs as readily as an execution one.

One rule governs the loop: **safety failures never retry.** A hallucinated
column is a mistake worth repairing; an attempted write is not a mistake, and
regenerating it would just be asking the model again for something it must
never be given.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.connection import Connection
from app.models.query import Query, QueryStatus
from app.models.schema_index import SchemaTable
from app.services.analytics.analyze import Analysis
from app.services.analytics.analyze import analyze as analyze_result
from app.services.cache.results import run_cached
from app.services.cache.semantic import SemanticHit
from app.services.cache.semantic import lookup as semantic_lookup
from app.services.execution.runner import ExecutionResult
from app.services.generation import prompts
from app.services.generation.explain import Explanation
from app.services.generation.explain import explain as explain_sql
from app.services.generation.generator import _recent_questions
from app.services.generation.intent import Intent, analyze
from app.services.generation.llm import Generation, LLMClient, LLMError, get_client
from app.services.learning import glossary as glossary_service
from app.services.learning.corrections import Example, similar_examples
from app.services.linking.retriever import RetrievalResult, retrieve
from app.services.validation.gates import (
    Gate,
    SchemaIndex,
    ValidationResult,
    validate,
)

log = get_logger(__name__)


@dataclass
class Attempt:
    """One pass round the loop, kept for the evaluation and the UI."""

    number: int
    sql: str
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.execution is not None and self.execution.ok


@dataclass
class QueryOutcome:
    question: str
    intent: Intent
    retrieval: RetrievalResult | None = None

    generation: Generation | None = None
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    analysis: Analysis | None = None
    """Profile, chart, outliers and trend. Only ever set on a successful run —
    there is nothing to profile about a rejected or failed query."""

    explanation: Explanation | None = None
    """Clause-by-clause reading of the SQL, derived from the parsed statement
    rather than from the model's account of its own work (F21)."""

    semantic_hit: SemanticHit | None = None
    """Set when generation was skipped because an earlier, differently-worded
    question had already been answered (F25)."""

    examples_used: list[Example] = field(default_factory=list)
    """The few-shot examples selected, kept so the UI can show which past
    corrections influenced this answer (F22)."""

    glossary_terms: list = field(default_factory=list)
    """Business terms matched in the question (F24)."""

    attempts: list[Attempt] = field(default_factory=list)
    rejected: bool = False
    """True when a safety gate refused the query outright."""

    error: str | None = None
    query_id: str | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)

    @property
    def needs_clarification(self) -> bool:
        return self.intent.needs_clarification

    @property
    def succeeded(self) -> bool:
        return self.execution is not None and self.execution.ok

    @property
    def correction_attempts(self) -> int:
        """Repair passes made — zero when the first attempt worked."""
        return max(0, len(self.attempts) - 1)

    @property
    def recovered_by_correction(self) -> bool:
        return self.succeeded and self.correction_attempts > 0


def build_schema_index(db: Session, connection_id: str) -> SchemaIndex:
    """The identifier set the schema gate validates against."""
    tables = db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == connection_id)
    )
    return SchemaIndex(
        columns_by_table={
            table.table_name.lower(): {c.column_name.lower() for c in table.columns}
            for table in tables
        }
    )


def run(
    db: Session,
    connection: Connection,
    question: str,
    user_id: str,
    session_id: str | None = None,
    client: LLMClient | None = None,
    max_attempts: int | None = None,
    persist: bool = True,
    retrieval_top_k: int | None = None,
    retrieval_hops: int | None = None,
    retrieval_mode: str = "hybrid",
) -> QueryOutcome:
    """Answer one question, repairing failures up to the attempt cap.

    The three ``retrieval_*`` arguments exist for the Phase 6 ablation study
    and default to the shipping configuration. They are threaded through here
    rather than reimplemented in the harness so what gets measured is this
    code path, not a copy of it that could drift.
    """
    started = time.perf_counter()
    client = client or get_client()
    max_attempts = max_attempts or settings.MAX_CORRECTION_ATTEMPTS

    stage = time.perf_counter()
    history = _recent_questions(db, session_id, user_id)
    intent = analyze(question, history)
    intent_ms = (time.perf_counter() - stage) * 1000

    outcome = QueryOutcome(question=question, intent=intent)

    if intent.needs_clarification:
        outcome.stage_timings = {"intent": round(intent_ms, 1)}
        return outcome

    stage = time.perf_counter()
    retrieval = retrieve(
        db,
        connection.id,
        intent.resolved_question,
        **({"top_k": retrieval_top_k} if retrieval_top_k is not None else {}),
        **({"hops": retrieval_hops} if retrieval_hops is not None else {}),
        mode=retrieval_mode,
    )
    outcome.retrieval = retrieval
    retrieval_ms = (time.perf_counter() - stage) * 1000

    if not retrieval.tables:
        outcome.error = (
            "No indexed schema for this connection. Index it before asking questions."
        )
        return outcome

    index = build_schema_index(db, connection.id)

    # Examples chosen by similarity to *this* question, with corrections
    # ranked above plain successes (F22). Timed separately because its cost
    # grows with query history rather than with the question — the one stage
    # here that gets slower the longer the system is used. An untimed stage is
    # an uninvestigable one.
    stage = time.perf_counter()
    outcome.examples_used = similar_examples(
        db,
        connection.id,
        intent.resolved_question,
        limit=settings.MAX_FEW_SHOT_EXAMPLES,
    )
    examples = [(e.question, e.sql) for e in outcome.examples_used]

    outcome.glossary_terms = glossary_service.match(
        db, connection.id, intent.resolved_question
    )
    glossary_text = glossary_service.render(outcome.glossary_terms)
    learning_ms = (time.perf_counter() - stage) * 1000

    generation_ms = 0.0
    execution_ms = 0.0
    previous_sql: str | None = None
    feedback: str | None = None

    # A question already answered in different words skips generation
    # entirely (F25). Only for a first turn: a follow-up depends on
    # conversational context a cached question never had.
    if not intent.is_follow_up:
        stage = time.perf_counter()
        hit = semantic_lookup(db, connection.id, intent.resolved_question, user_id)
        generation_ms += (time.perf_counter() - stage) * 1000

        if hit is not None:
            outcome.semantic_hit = hit
            outcome.generation = Generation(
                sql=hit.sql,
                confidence=hit.similarity,
                explanation=(
                    "Reused the SQL from an earlier question that means the "
                    f"same thing: “{hit.question}”."
                ),
                assumptions=[
                    f"Answered from a previous question ({hit.similarity:.0%} "
                    f"similar), not regenerated. Embedder: {hit.embedder}."
                ],
                model=f"semantic-cache:{hit.embedder}",
            )

    for attempt_number in range(1, max_attempts + 1):
        # The cached SQL takes the first attempt. If it fails validation or
        # execution — the schema may have moved since — the loop falls through
        # to real generation on the next pass rather than giving up.
        if attempt_number == 1 and outcome.semantic_hit is not None:
            generation = outcome.generation
            attempt = Attempt(number=attempt_number, sql=generation.sql)
            validation = validate(
                generation.sql,
                connection.dialect,
                index,
                max_rows=settings.MAX_RESULT_ROWS,
            )
            attempt.validation = validation
            outcome.validation = validation

            if validation.ok:
                stage = time.perf_counter()
                execution = run_cached(connection, validation.sql)
                execution_ms += (time.perf_counter() - stage) * 1000
                attempt.execution = execution
                outcome.execution = execution
                outcome.attempts.append(attempt)
                if execution.ok:
                    break
                attempt.error = execution.error
            else:
                attempt.error = validation.failure.message
                outcome.attempts.append(attempt)

            # The cached answer did not hold up; stop claiming it did.
            outcome.semantic_hit = None
            outcome.generation = None
            outcome.validation = None
            outcome.execution = None
            continue

        prompt = prompts.build(
            db=db,
            connection_id=connection.id,
            question=question,
            intent=intent,
            retrieval=retrieval,
            dialect=connection.dialect,
            examples=examples,
            previous_sql=previous_sql,
            error_feedback=feedback,
            glossary=glossary_text,
        )

        stage = time.perf_counter()
        try:
            generation = client.generate(prompt)
        except LLMError as exc:
            generation_ms += (time.perf_counter() - stage) * 1000
            outcome.error = str(exc)
            outcome.attempts.append(
                Attempt(number=attempt_number, sql="", error=str(exc))
            )
            break
        generation_ms += (time.perf_counter() - stage) * 1000

        outcome.generation = generation
        attempt = Attempt(number=attempt_number, sql=generation.sql)

        validation = validate(
            generation.sql,
            connection.dialect,
            index,
            max_rows=settings.MAX_RESULT_ROWS,
        )
        attempt.validation = validation
        outcome.validation = validation

        if not validation.ok:
            failure = validation.failure
            attempt.error = failure.message
            outcome.attempts.append(attempt)

            # A safety rejection ends the loop. Asking again for something
            # that must never be permitted is not a repair.
            if not failure.retryable:
                outcome.rejected = True
                outcome.error = failure.message
                log.warning(
                    "query_rejected", gate=failure.gate.value, reason=failure.message
                )
                break

            previous_sql, feedback = generation.sql, failure.message
            continue

        stage = time.perf_counter()
        execution = run_cached(connection, validation.sql)
        execution_ms += (time.perf_counter() - stage) * 1000

        attempt.execution = execution
        outcome.execution = execution
        outcome.attempts.append(attempt)

        if execution.ok:
            outcome.error = None
            break

        attempt.error = execution.error
        outcome.error = execution.error
        previous_sql, feedback = validation.sql, execution.error

    # Profiling, chart selection, outliers and trend. All local arithmetic, so
    # it runs inline; the narrative is the one analytics step that costs an API
    # call and it has its own endpoint.
    analysis_ms = 0.0
    if outcome.succeeded and outcome.execution is not None:
        stage = time.perf_counter()
        outcome.analysis = analyze_result(
            outcome.execution.columns,
            outcome.execution.rows,
            truncated=outcome.execution.truncated,
        )
        analysis_ms = (time.perf_counter() - stage) * 1000

    # Read from the parsed statement, so it describes what will actually run
    # rather than what the model says it wrote (F21).
    if outcome.validation and outcome.validation.ok:
        outcome.explanation = explain_sql(outcome.validation.sql, connection.dialect)

    outcome.stage_timings = {
        "intent": round(intent_ms, 1),
        "retrieval": round(retrieval_ms, 1),
        "generation": round(generation_ms, 1),
        "execution": round(execution_ms, 1),
        "learning": round(learning_ms, 1),
        "analysis": round(analysis_ms, 1),
        "total": round((time.perf_counter() - started) * 1000, 1),
    }

    if persist:
        outcome.query_id = _persist(db, connection, session_id, user_id, outcome)

    log.info(
        "query_completed",
        succeeded=outcome.succeeded,
        rejected=outcome.rejected,
        attempts=len(outcome.attempts),
        recovered=outcome.recovered_by_correction,
        **outcome.stage_timings,
    )
    return outcome


def _status(outcome: QueryOutcome) -> QueryStatus:
    if outcome.rejected:
        return QueryStatus.REJECTED
    if outcome.succeeded:
        return QueryStatus.EXECUTED
    if outcome.validation and outcome.validation.ok:
        return QueryStatus.VALIDATED
    return QueryStatus.FAILED


def _persist(
    db: Session,
    connection: Connection,
    session_id: str | None,
    user_id: str,
    outcome: QueryOutcome,
) -> str:
    record = Query(
        user_id=user_id,
        connection_id=connection.id,
        session_id=session_id,
        question=outcome.question,
        resolved_question=outcome.intent.resolved_question,
        generated_sql=outcome.attempts[0].sql if outcome.attempts else None,
        # Only a query that actually ran becomes a few-shot example; a
        # syntactically valid one that failed would teach the wrong thing.
        final_sql=outcome.validation.sql if outcome.succeeded else None,
        status=_status(outcome),
        error_message=outcome.error,
        correction_attempts=outcome.correction_attempts,
        latency_ms=int(outcome.stage_timings.get("total", 0)),
        tokens_used=outcome.generation.total_tokens if outcome.generation else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record.id


__all__ = ["Attempt", "Gate", "QueryOutcome", "build_schema_index", "run"]
