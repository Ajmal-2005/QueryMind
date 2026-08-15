"""Natural-language query endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus
from app.models.query import Query
from app.models.user import User
from app.schemas.query import (
    GenerationRead,
    QueryRequest,
    QueryResponse,
    RetrievedTableRead,
)
from app.services.generation import generator

router = APIRouter()


@router.post("", response_model=QueryResponse, summary="Ask a question in English")
def create_query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QueryResponse:
    connection = db.get(Connection, payload.connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )

    if connection.status is not ConnectionStatus.INDEXED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This connection has no schema index yet. Index it first.",
        )

    result = generator.run(
        db=db,
        connection=connection,
        question=payload.question,
        user_id=user.id,
        session_id=payload.session_id,
    )

    db.add(
        AuditLog(
            user_id=user.id,
            action="query.generate",
            payload={
                "connection_id": connection.id,
                "question": payload.question[:500],
                "query_id": result.query_id,
                "succeeded": result.succeeded,
            },
        )
    )
    db.commit()

    return _to_response(result)


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
            "status": q.status.value,
            "latency_ms": q.latency_ms,
            "created_at": q.created_at.isoformat(),
        }
        for q in rows
    ]


def _to_response(result: generator.PipelineResult) -> QueryResponse:
    generation = None
    if result.generation:
        generation = GenerationRead(
            sql=result.generation.sql,
            confidence=result.generation.confidence,
            explanation=result.generation.explanation,
            assumptions=result.generation.assumptions,
            model=result.generation.model,
            input_tokens=result.generation.input_tokens,
            output_tokens=result.generation.output_tokens,
        )

    tables = []
    if result.retrieval:
        tables = [
            RetrievedTableRead(
                table_name=t.table_name,
                score=t.score,
                via_expansion=t.via_expansion,
                dense_rank=t.dense_rank,
                sparse_rank=t.sparse_rank,
            )
            for t in result.retrieval.tables
        ]

    return QueryResponse(
        query_id=result.query_id,
        question=result.question,
        resolved_question=result.intent.resolved_question,
        question_type=result.intent.question_type,
        needs_clarification=result.intent.needs_clarification,
        clarification=result.intent.clarification,
        generation=generation,
        retrieved_tables=tables,
        embedder=result.retrieval.embedder if result.retrieval else None,
        error=result.error,
        timings_ms=result.stage_timings,
    )
