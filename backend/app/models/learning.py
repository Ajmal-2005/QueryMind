"""What the system learns from its users (F22, F24).

Two tables, both feeding the same place — the prompt. A correction is an
implicit lesson ("when I asked X, the right SQL was Y"); a glossary term is an
explicit one ("'active user' means this predicate"). Both are retrieved by
similarity to the current question and rendered into the prompt as context.

Corrections carry an embedding for the same reason schema tables do: selecting
few-shot examples by recency picks whatever happened last, which has no
relationship to what the current question needs. Similarity picks the example
that actually teaches something.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.schema_index import _embedding_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Correction(Base):
    """SQL a user fixed by hand, kept as a future example.

    Appendix C specifies `corrections (id, query_id, corrected_sql,
    embedding)`. The question is denormalised onto the row as well: the
    embedding is *of* the question, and a correction whose query row has since
    been deleted is still a perfectly good lesson.
    """

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    query_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )

    question: Mapped[str] = mapped_column(Text)
    original_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What the model produced. Kept for the error taxonomy in Phase 6."""

    corrected_sql: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    embedding: Mapped[list | None] = mapped_column(_embedding_column(), nullable=True)
    """Of the *question*, not the SQL — retrieval matches on what was asked."""

    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    """The corrected SQL passed the gates and executed when it was saved.
    An unverified correction must never be shown to the model as an example."""

    times_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class GlossaryTerm(Base):
    """A business term and what it means in SQL (F24).

    "Active user" is not in any schema. It is a definition the organisation
    holds, and without it every model guesses — differently each time.
    """

    __tablename__ = "glossary_terms"
    __table_args__ = (
        UniqueConstraint("connection_id", "term", name="uq_glossary_connection_term"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    term: Mapped[str] = mapped_column(String(200))
    definition: Mapped[str] = mapped_column(Text)
    """Plain English — what the term means to the business."""

    sql_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The predicate or expression that implements it, when there is one."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
