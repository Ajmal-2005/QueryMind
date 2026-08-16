"""Natural-language query endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus
from app.models.query import Query
from app.models.user import User
from app.schemas.query import (
    AttemptRead,
    ExecuteRequest,
    GenerationRead,
    QueryRequest,
    QueryResponse,
    ResultRead,
    RetrievedTableRead,
    ValidationRead,
)
from app.services.execution.runner import execute as run_sql
from app.services.generation import pipeline
from app.services.validation.gates import validate

router = APIRouter()


def _owned_connection(connection_id: str, db: Session, user: User) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )
    return connection


def _require_indexed(connection: Connection) -> None:
    if connection.status is not ConnectionStatus.INDEXED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This connection has no schema index yet. Index it first.",
        )


@router.post("", response_model=QueryResponse, summary="Ask a question in English")
def create_query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QueryResponse:
    connection = _owned_connection(payload.connection_id, db, user)
    _require_indexed(connection)

    outcome = pipeline.run(
        db=db,
        connection=connection,
        question=payload.question,
        user_id=user.id,
        session_id=payload.session_id,
    )

    db.add(
        AuditLog(
            user_id=user.id,
            action="query.answer",
            payload={
                "connection_id": connection.id,
                "question": payload.question[:500],
                "query_id": outcome.query_id,
                "succeeded": outcome.succeeded,
                "rejected": outcome.rejected,
                "correction_attempts": outcome.correction_attempts,
            },
        )
    )
    db.commit()

    return _to_response(outcome)


@router.post("/execute", response_model=QueryResponse, summary="Run user-edited SQL")
def execute_sql(
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QueryResponse:
    """Execute SQL the user wrote or edited.

    Runs the identical gates. A hand-edited query is not more trusted than a
    generated one — if anything it is less, since it did not come from a
    prompt that forbade writes.
    """
    connection = _owned_connection(payload.connection_id, db, user)
    _require_indexed(connection)

    index = pipeline.build_schema_index(db, connection.id)
    validation = validate(
        payload.sql, connection.dialect, index, max_rows=settings.MAX_RESULT_ROWS
    )

    db.add(
        AuditLog(
            user_id=user.id,
            action="query.execute_manual",
            payload={
                "connection_id": connection.id,
                "sql": payload.sql[:1000],
                "accepted": validation.ok,
                "gate": validation.failure.gate.value if validation.failure else None,
            },
        )
    )
    db.commit()

    if not validation.ok:
        failure = validation.failure
        return QueryResponse(
            query_id=None,
            question=payload.sql,
            resolved_question=payload.sql,
            question_type="filter",
            rejected=not failure.retryable,
            validation=ValidationRead(
                ok=False,
                sql=payload.sql,
                gate=failure.gate.value,
                message=failure.message,
                retryable=failure.retryable,
            ),
            error=failure.message,
        )

    result = run_sql(connection, validation.sql)

    return QueryResponse(
        query_id=None,
        question=payload.sql,
        resolved_question=payload.sql,
        question_type="filter",
        validation=ValidationRead(
            ok=True,
            sql=validation.sql,
            warnings=validation.warnings,
            limit_applied=validation.limit_applied,
        ),
        result=_result_read(result),
        error=result.error,
    )


@router.get(
    "/history", response_model=list[dict], summary="Recent questions for this user"
)
def history(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    rows = db.scalars(
        select(Query)
        .where(Query.user_id == user.id)
        .order_by(Query.created_at.desc())
        .limit(min(limit, 100))
    )
    return [
        {
            "id": q.id,
            "question": q.question,
            "generated_sql": q.generated_sql,
            "final_sql": q.final_sql,
            "status": q.status.value,
            "correction_attempts": q.correction_attempts,
            "latency_ms": q.latency_ms,
            "created_at": q.created_at.isoformat(),
        }
        for q in rows
    ]


def _result_read(result) -> ResultRead | None:
    if not result or not result.ok:
        return None
    return ResultRead(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        duration_ms=round(result.duration_ms, 1),
    )


def _to_response(outcome: pipeline.QueryOutcome) -> QueryResponse:
    generation = None
    if outcome.generation:
        generation = GenerationRead(
            sql=outcome.generation.sql,
            confidence=outcome.generation.confidence,
            explanation=outcome.generation.explanation,
            assumptions=outcome.generation.assumptions,
            model=outcome.generation.model,
            input_tokens=outcome.generation.input_tokens,
            output_tokens=outcome.generation.output_tokens,
        )

    validation = None
    if outcome.validation:
        failure = outcome.validation.failure
        validation = ValidationRead(
            ok=outcome.validation.ok,
            sql=outcome.validation.sql,
            gate=failure.gate.value if failure else None,
            message=failure.message if failure else None,
            retryable=failure.retryable if failure else None,
            warnings=outcome.validation.warnings,
            limit_applied=outcome.validation.limit_applied,
        )

    tables = []
    if outcome.retrieval:
        tables = [
            RetrievedTableRead(
                table_name=t.table_name,
                score=t.score,
                via_expansion=t.via_expansion,
                dense_rank=t.dense_rank,
                sparse_rank=t.sparse_rank,
            )
            for t in outcome.retrieval.tables
        ]

    return QueryResponse(
        query_id=outcome.query_id,
        question=outcome.question,
        resolved_question=outcome.intent.resolved_question,
        question_type=outcome.intent.question_type,
        needs_clarification=outcome.intent.needs_clarification,
        clarification=outcome.intent.clarification,
        rejected=outcome.rejected,
        generation=generation,
        validation=validation,
        result=_result_read(outcome.execution),
        attempts=[
            AttemptRead(
                number=a.number,
                sql=a.sql,
                error=a.error,
                gate=(
                    a.validation.failure.gate.value
                    if a.validation and a.validation.failure
                    else None
                ),
                succeeded=a.succeeded,
            )
            for a in outcome.attempts
        ],
        correction_attempts=outcome.correction_attempts,
        recovered_by_correction=outcome.recovered_by_correction,
        retrieved_tables=tables,
        embedder=outcome.retrieval.embedder if outcome.retrieval else None,
        error=outcome.error,
        timings_ms=outcome.stage_timings,
    )
