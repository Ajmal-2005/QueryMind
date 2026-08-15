import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Dialect(str, enum.Enum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    # In scope for development and the demo only. Introspection runs through
    # SQLAlchemy's dialect-agnostic Inspector, so supporting it costs nothing
    # and gives us a target database that needs no server.
    SQLITE = "sqlite"


class ConnectionStatus(str, enum.Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Connection(Base):
    """A registered target database.

    Credentials are stored Fernet-encrypted in ``encrypted_credentials`` and
    are never returned to the client — see the connection service.
    """

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    dialect: Mapped[Dialect] = mapped_column(Enum(Dialect, native_enum=False))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(String(255))
    encrypted_credentials: Mapped[str] = mapped_column(Text)
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, native_enum=False), default=ConnectionStatus.PENDING
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
