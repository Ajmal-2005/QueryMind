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
from app.services.execution.runner import ExecutionResult, execute
from app.services.generation import prompts
from app.services.generation.generator import _few_shot_examples, _recent_questions
from app.services.generation.intent import Intent, analyze
from app.services.generation.llm import Generation, LLMClient, LLMError, get_client
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
) -> QueryOutcome:
    """Answer one question, repairing failures up to the attempt cap."""
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
    retrieval = retrieve(db, connection.id, intent.resolved_question)
    outcome.retrieval = retrieval
    retrieval_ms = (time.perf_counter() - stage) * 1000

    if not retrieval.tables:
        outcome.error = (
            "No indexed schema for this connection. Index it before asking questions."
        )
        return outcome

    index = build_schema_index(db, connection.id)
    examples = _few_shot_examples(db, connection.id)

    generation_ms = 0.0
    execution_ms = 0.0
    previous_sql: str | None = None
    feedback: str | None = None

    for attempt_number in range(1, max_attempts + 1):
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
        execution = execute(connection, validation.sql)
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

    outcome.stage_timings = {
        "intent": round(intent_ms, 1),
        "retrieval": round(retrieval_ms, 1),
        "generation": round(generation_ms, 1),
        "execution": round(execution_ms, 1),
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
