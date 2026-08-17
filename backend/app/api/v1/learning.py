"""Corrections (F22) and the business glossary (F24).

Both feed the prompt, and both are user-authored, so both are validated before
they can ever reach a model. A correction is stored only after its SQL has
passed the same four gates and executed - an unverified correction taught as
an example would propagate a mistake instead of fixing one.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.audit import AuditLog
from app.models.connection import Connection
from app.models.learning import Correction, GlossaryTerm
from app.models.user import User
from app.schemas.learning import (
    CorrectionCreate,
    CorrectionRead,
    GlossaryTermCreate,
    GlossaryTermRead,
)
from app.services.cache.results import run_cached
from app.services.generation import pipeline
from app.services.learning.corrections import record_correction
from app.services.validation.gates import validate

log = get_logger(__name__)
router = APIRouter()


def _owned_connection(connection_id: str, db: Session, user: User) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )
    return connection


@router.post(
    "/corrections",
    response_model=CorrectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save SQL you fixed by hand",
)
def create_correction(
    payload: CorrectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrectionRead:
    """Record a correction so future questions like this one go better (F22).

    The corrected SQL must pass the gates *and* execute before it is stored as
    verified. A correction is the highest-signal example this system has - it
    is a place the model got something wrong and a human said what right looks
    like - which is exactly why it must not be taken on trust.
    """
    connection = _owned_connection(payload.connection_id, db, user)

    index = pipeline.build_schema_index(db, connection.id)
    validation = validate(
        payload.corrected_sql,
        connection.dialect,
        index,
        max_rows=settings.MAX_RESULT_ROWS,
    )
    if not validation.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The corrected SQL was blocked by the "
                f"{validation.failure.gate.value} gate: {validation.failure.message}"
            ),
        )

    result = run_cached(connection, validation.sql)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The corrected SQL did not run: {result.error}",
        )

    correction = record_correction(
        db,
        user_id=user.id,
        connection_id=connection.id,
        question=payload.question,
        corrected_sql=validation.sql,
        original_sql=payload.original_sql,
        query_id=payload.query_id,
        note=payload.note,
        verified=True,
    )

    db.add(
        AuditLog(
            user_id=user.id,
            action="correction.create",
            payload={
                "connection_id": connection.id,
                "correction_id": correction.id,
                "question": payload.question[:500],
            },
        )
    )
    db.commit()

    return CorrectionRead(
        id=correction.id,
        question=correction.question,
        original_sql=correction.original_sql,
        corrected_sql=correction.corrected_sql,
        note=correction.note,
        verified=correction.verified,
        created_at=correction.created_at,
    )


@router.get(
    "/corrections", response_model=list[CorrectionRead], summary="List corrections"
)
def list_corrections(
    connection_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CorrectionRead]:
    connection = _owned_connection(connection_id, db, user)
    rows = db.scalars(
        select(Correction)
        .where(
            Correction.connection_id == connection.id,
            Correction.user_id == user.id,
        )
        .order_by(Correction.created_at.desc())
        .limit(min(limit, 200))
    ).all()

    return [
        CorrectionRead(
            id=c.id,
            question=c.question,
            original_sql=c.original_sql,
            corrected_sql=c.corrected_sql,
            note=c.note,
            verified=c.verified,
            created_at=c.created_at,
        )
        for c in rows
    ]


@router.delete(
    "/corrections/{correction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget a correction",
)
def delete_correction(
    correction_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    correction = db.get(Correction, correction_id)
    if correction is None or correction.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Correction not found"
        )
    db.delete(correction)
    db.commit()


# ---------------------------------------------------------------- glossary


@router.post(
    "/glossary",
    response_model=GlossaryTermRead,
    status_code=status.HTTP_201_CREATED,
    summary="Define a business term",
)
def upsert_term(
    payload: GlossaryTermCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GlossaryTermRead:
    """Define what a term means in SQL (F24).

    Upsert rather than create: a definition is a single agreed fact per
    connection, and a second POST of the same term is someone refining it, not
    creating a rival definition for the matcher to choose between.
    """
    connection = _owned_connection(payload.connection_id, db, user)

    if payload.sql_expression:
        # The expression is spliced into a prompt and may reach a query, so it
        # is checked for anything that is not an expression.
        forbidden = (";", "--", "/*", "drop ", "delete ", "insert ", "update ")
        lowered = payload.sql_expression.lower()
        if any(token in lowered for token in forbidden):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A glossary expression must be a plain SQL fragment - no "
                    "statements, semicolons, or comments."
                ),
            )

    existing = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.connection_id == connection.id,
            GlossaryTerm.term == payload.term,
        )
    )
    if existing:
        existing.definition = payload.definition
        existing.sql_expression = payload.sql_expression
        term = existing
    else:
        term = GlossaryTerm(
            connection_id=connection.id,
            user_id=user.id,
            term=payload.term,
            definition=payload.definition,
            sql_expression=payload.sql_expression,
        )
        db.add(term)

    db.commit()
    db.refresh(term)

    return GlossaryTermRead(
        id=term.id,
        term=term.term,
        definition=term.definition,
        sql_expression=term.sql_expression,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


@router.get(
    "/glossary", response_model=list[GlossaryTermRead], summary="List glossary terms"
)
def list_terms(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GlossaryTermRead]:
    connection = _owned_connection(connection_id, db, user)
    rows = db.scalars(
        select(GlossaryTerm)
        .where(GlossaryTerm.connection_id == connection.id)
        .order_by(GlossaryTerm.term)
    ).all()

    return [
        GlossaryTermRead(
            id=t.id,
            term=t.term,
            definition=t.definition,
            sql_expression=t.sql_expression,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in rows
    ]


@router.delete(
    "/glossary/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a glossary term",
)
def delete_term(
    term_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    term = db.get(GlossaryTerm, term_id)
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Term not found"
        )
    _owned_connection(term.connection_id, db, user)
    db.delete(term)
    db.commit()
