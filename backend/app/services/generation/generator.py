"""The NL→SQL pipeline.

Ties intent analysis, schema linking, prompt construction, and generation
into one call. Validation gates, sandboxed execution, and the self-correction
loop are phase 3 — this stage produces SQL and stops.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.connection import Connection
from app.models.query import Query, QueryStatus
from app.services.generation import prompts
from app.services.generation.intent import Intent, QuestionType, analyze
from app.services.generation.llm import Generation, LLMClient, LLMError, get_client
from app.services.linking.retriever import RetrievalResult, retrieve

log = get_logger(__name__)

HISTORY_TURNS = 4


@dataclass
class PipelineResult:
    question: str
    intent: Intent
    retrieval: RetrievalResult | None = None
    generation: Generation | None = None

    error: str | None = None
    query_id: str | None = None

    intent_ms: float = 0.0
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0

    stage_timings: dict[str, float] = field(default_factory=dict)

    @property
    def needs_clarification(self) -> bool:
        return self.intent.needs_clarification

    @property
    def succeeded(self) -> bool:
        return self.generation is not None and self.error is None


def _recent_questions(db: Session, session_id: str | None, user_id: str) -> list[str]:
    """Previous questions in this session, oldest first."""
    if not session_id:
        return []

    rows = db.scalars(
        select(Query.question)
        .where(Query.session_id == session_id, Query.user_id == user_id)
        .order_by(Query.created_at.desc())
        .limit(HISTORY_TURNS)
    ).all()
    return list(reversed(rows))


def _few_shot_examples(db: Session, connection_id: str) -> list[tuple[str, str]]:
    """Corrected queries to use as in-context examples.

    Phase 5 selects these by embedding similarity to the current question.
    For now the most recent successful queries on this connection are a
    reasonable stand-in, and the wiring is what matters.
    """
    rows = db.execute(
        select(Query.question, Query.final_sql)
        .where(
            Query.connection_id == connection_id,
            Query.status == QueryStatus.EXECUTED,
            Query.final_sql.is_not(None),
        )
        .order_by(Query.created_at.desc())
        .limit(3)
    ).all()
    return [(q, s) for q, s in rows if s]


def run(
    db: Session,
    connection: Connection,
    question: str,
    user_id: str,
    session_id: str | None = None,
    client: LLMClient | None = None,
    persist: bool = True,
) -> PipelineResult:
    """Translate one question into SQL."""
    started = time.perf_counter()
    client = client or get_client()

    # --- intent ---
    stage = time.perf_counter()
    history = _recent_questions(db, session_id, user_id)
    intent = analyze(question, history)
    intent_ms = (time.perf_counter() - stage) * 1000

    result = PipelineResult(question=question, intent=intent, intent_ms=intent_ms)

    # An ambiguous question is answered with a question, not a guess.
    if intent.needs_clarification:
        result.total_ms = (time.perf_counter() - started) * 1000
        log.info("clarification_requested", question=question[:120])
        return result

    # --- schema linking ---
    stage = time.perf_counter()
    retrieval = retrieve(db, connection.id, intent.resolved_question)
    result.retrieval = retrieval
    result.retrieval_ms = (time.perf_counter() - stage) * 1000

    if not retrieval.tables:
        result.error = (
            "No indexed schema for this connection. Index it before asking questions."
        )
        result.total_ms = (time.perf_counter() - started) * 1000
        return result

    # --- generation ---
    prompt = prompts.build(
        db=db,
        connection_id=connection.id,
        question=question,
        intent=intent,
        retrieval=retrieval,
        dialect=connection.dialect,
        examples=_few_shot_examples(db, connection.id),
    )

    stage = time.perf_counter()
    try:
        generation = client.generate(prompt)
        result.generation = generation
    except LLMError as exc:
        result.error = str(exc)
        log.warning("generation_failed", error=str(exc)[:200])
    result.generation_ms = (time.perf_counter() - stage) * 1000

    result.total_ms = (time.perf_counter() - started) * 1000
    result.stage_timings = {
        "intent": round(result.intent_ms, 1),
        "retrieval": round(result.retrieval_ms, 1),
        "generation": round(result.generation_ms, 1),
        "total": round(result.total_ms, 1),
    }

    if persist:
        result.query_id = _persist(
            db, connection, question, session_id, user_id, result
        )

    log.info(
        "query_generated",
        tables=len(retrieval.tables),
        succeeded=result.succeeded,
        **result.stage_timings,
    )
    return result


def _persist(
    db: Session,
    connection: Connection,
    question: str,
    session_id: str | None,
    user_id: str,
    result: PipelineResult,
) -> str:
    record = Query(
        user_id=user_id,
        connection_id=connection.id,
        session_id=session_id,
        question=question,
        generated_sql=result.generation.sql if result.generation else None,
        # `final_sql` stays empty until the query is validated and executed in
        # phase 3; it is what the few-shot selector reads back.
        status=QueryStatus.GENERATED if result.succeeded else QueryStatus.FAILED,
        error_message=result.error,
        latency_ms=int(result.total_ms),
        tokens_used=result.generation.total_tokens if result.generation else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record.id


__all__ = ["PipelineResult", "QuestionType", "run"]
