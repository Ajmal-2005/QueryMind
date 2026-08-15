import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QueryStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATED = "generated"
    VALIDATED = "validated"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Query(Base):
    """One natural-language question and everything the pipeline made of it."""

    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, native_enum=False), default=QueryStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_attempts: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
