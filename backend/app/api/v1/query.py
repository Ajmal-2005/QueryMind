"""Natural-language query endpoints."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus
from app.models.query import Query
from app.models.user import User
from app.schemas.analytics import (
    AnalysisRead,
    CacheStatusRead,
    ExportRequest,
    InsightRequest,
    NarrativeRead,
    to_analysis_read,
    to_narrative_read,
)
from app.schemas.learning import (
    ExampleRead,
    ExplanationRead,
    GlossaryMatchRead,
    SemanticHitRead,
    StepRead,
    SuggestionRead,
)
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
from app.services.analytics import export as export_service
from app.services.analytics.analyze import analyze
from app.services.analytics.narrative import narrate
from app.services.cache.results import cache_status, run_cached
from app.services.generation import pipeline
from app.services.generation.explain import explain as explain_sql
from app.services.learning.suggestions import suggest
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

    result = run_cached(connection, validation.sql)
    analysis = (
        analyze(result.columns, result.rows, truncated=result.truncated)
        if result.ok
        else None
    )

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
        analysis=to_analysis_read(analysis) if analysis else None,
        explanation=to_explanation_read(
            explain_sql(validation.sql, connection.dialect)
        ),
        error=result.error,
    )


@router.get(
    "/suggestions",
    response_model=list[SuggestionRead],
    summary="Starter questions this schema can answer",
)
def suggestions(
    connection_id: str,
    limit: int = 6,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SuggestionRead]:
    """Schema-aware starters (F23).

    Generated from the indexed schema rather than hardcoded, so pointing this
    at a different database offers questions that database can actually
    answer. A starter that fails is worse than no starter — the user
    reasonably concludes the product is broken.
    """
    connection = _owned_connection(connection_id, db, user)
    _require_indexed(connection)

    return [
        SuggestionRead(question=s.question, reason=s.reason)
        for s in suggest(db, connection.id, limit=min(limit, 12))
    ]


def _validated_result(payload_sql: str, connection: Connection, db: Session):
    """Run SQL through the gates and return (validated_sql, result).

    Every path that executes SQL on behalf of a client goes through here, so
    an export and a narrative are gated exactly as tightly as a query. A
    request that names a connection the caller owns still cannot smuggle a
    write past the safety gate by asking for it as a CSV.
    """
    index = pipeline.build_schema_index(db, connection.id)
    validation = validate(
        payload_sql, connection.dialect, index, max_rows=settings.MAX_RESULT_ROWS
    )
    if not validation.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Blocked by the {validation.failure.gate.value} gate: "
            f"{validation.failure.message}",
        )

    result = run_cached(connection, validation.sql)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=result.error
        )
    return validation.sql, result


@router.post(
    "/insight",
    response_model=NarrativeRead,
    summary="Write a plain-English summary of a result",
)
def insight(
    payload: InsightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NarrativeRead:
    """Summarise a result set in prose (F13).

    Separate from `/query` on purpose: this is the one analytics step that
    costs an LLM call, and holding the table and chart back while waiting on
    prose would make the product feel slower than it is. The UI renders the
    result first and fills this in when it lands.

    The rows are re-fetched here rather than posted up by the client — the
    server will not narrate data it has not read out of the database itself.
    """
    connection = _owned_connection(payload.connection_id, db, user)
    _require_indexed(connection)

    if not settings.NARRATIVE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Narrative generation is disabled on this deployment.",
        )

    sql, result = _validated_result(payload.sql, connection, db)
    analysis = analyze(result.columns, result.rows, truncated=result.truncated)
    narrative = narrate(payload.question, sql, analysis, result.rows)

    db.add(
        AuditLog(
            user_id=user.id,
            action="query.insight",
            payload={
                "connection_id": connection.id,
                "narrator": narrative.model,
                "rows_summarised": result.row_count,
                # The security model asks for evidence that masking ran, not
                # just that it was configured.
                "masked_columns": narrative.masking.column_names,
                "values_masked": narrative.masking.values_masked,
            },
        )
    )
    db.commit()

    return to_narrative_read(narrative)


@router.post("/analyze", response_model=AnalysisRead, summary="Profile a result set")
def analyze_sql(
    payload: InsightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisRead:
    """Re-profile a query without generating anything.

    Used when a dashboard tile or a saved query needs its chart and statistics
    back without paying for narration.
    """
    connection = _owned_connection(payload.connection_id, db, user)
    _require_indexed(connection)

    _, result = _validated_result(payload.sql, connection, db)
    return to_analysis_read(
        analyze(result.columns, result.rows, truncated=result.truncated)
    )


def _filename(title: str, extension: str) -> str:
    """A safe download name.

    Quoted in a Content-Disposition header, so anything that could break out
    of the quoting — or out of the directory — is stripped rather than escaped.
    """
    cleaned = re.sub(r"[^\w\-. ]+", "", title).strip().replace(" ", "-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"{(cleaned or 'query-result')[:60]}-{stamp}.{extension}"


@router.post("/export", summary="Download a result as CSV, JSON, Excel, or PDF")
def export(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Serialise a result set for download (F17).

    PNG is absent by design: the chart is an SVG that only exists in the
    browser, and the browser saves it directly. Re-drawing it here would mean
    a second charting implementation that could disagree with what the user
    saw.
    """
    connection = _owned_connection(payload.connection_id, db, user)
    _require_indexed(connection)

    sql, result = _validated_result(payload.sql, connection, db)
    fmt = export_service.ExportFormat(payload.format)

    context = export_service.ReportContext(
        title=payload.title,
        question=payload.question,
        sql=sql,
    )

    if fmt is export_service.ExportFormat.PDF:
        analysis = analyze(result.columns, result.rows, truncated=result.truncated)
        context.analysis = analysis
        context.chart_png = export_service.decode_chart_image(payload.chart_png)

        if payload.include_narrative and settings.NARRATIVE_ENABLED:
            narrative = narrate(payload.question, sql, analysis, result.rows)
            context.headline = narrative.headline
            context.summary = narrative.summary
            context.findings = narrative.findings
            context.narrator = narrative.model

    body = export_service.render(fmt, result.columns, result.rows, context)

    db.add(
        AuditLog(
            user_id=user.id,
            action="query.export",
            payload={
                "connection_id": connection.id,
                "format": fmt.value,
                "rows": result.row_count,
                "bytes": len(body),
            },
        )
    )
    db.commit()

    name = _filename(payload.title, fmt.value)
    return Response(
        content=body,
        media_type=export_service.MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/cache", response_model=CacheStatusRead, summary="Result cache statistics")
def cache(user: User = Depends(get_current_user)) -> CacheStatusRead:
    return CacheStatusRead(**cache_status())


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


def to_explanation_read(explanation) -> ExplanationRead | None:
    if explanation is None:
        return None
    return ExplanationRead(
        parsed=explanation.parsed,
        summary=explanation.summary,
        steps=[
            StepRead(
                order=s.order,
                clause=s.clause,
                title=s.title,
                detail=s.detail,
                sql=s.sql,
            )
            for s in explanation.steps
        ],
        tables=explanation.tables,
        aggregates=explanation.aggregates,
        row_limit=explanation.row_limit,
        is_aggregate=explanation.is_aggregate,
    )


def _result_read(result) -> ResultRead | None:
    if not result or not result.ok:
        return None
    return ResultRead(
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        duration_ms=round(result.duration_ms, 1),
        cached=result.cached,
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
        clarification_options=outcome.intent.clarification_options,
        is_follow_up=outcome.intent.is_follow_up,
        rejected=outcome.rejected,
        generation=generation,
        validation=validation,
        result=_result_read(outcome.execution),
        analysis=to_analysis_read(outcome.analysis) if outcome.analysis else None,
        explanation=to_explanation_read(outcome.explanation),
        semantic_hit=(
            SemanticHitRead(
                question=outcome.semantic_hit.question,
                similarity=round(outcome.semantic_hit.similarity, 4),
                embedder=outcome.semantic_hit.embedder,
            )
            if outcome.semantic_hit
            else None
        ),
        examples_used=[
            ExampleRead(
                question=e.question,
                sql=e.sql,
                score=round(e.score, 4),
                source=e.source,
            )
            for e in outcome.examples_used
        ],
        glossary_terms=[
            GlossaryMatchRead(
                term=t.term,
                definition=t.definition,
                sql_expression=t.sql_expression,
            )
            for t in outcome.glossary_terms
        ],
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
