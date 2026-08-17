"""Saved dashboards (F18).

Appendix C specifies `dashboards (id, user_id, name, layout jsonb)` - tiles
inside a JSON blob. This splits tiles into their own table instead, for one
reason: a tile holds SQL that gets executed on every refresh. Rows can be
counted, indexed, cascaded, and audited individually; a blob cannot, and a
malformed one would take the whole dashboard down with it. `layout` survives
as JSON on the dashboard, holding only grid positions - which is the part
that genuinely is unstructured.

Tiles store the SQL, not just the question. Re-asking the question on every
open would re-run generation, cost tokens each time, and could quietly return
a different query than the one the user pinned. The question is kept beside
it so the tile can say what it was built to answer.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    """Grid positions, keyed by tile id. Presentation only."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    tiles: Mapped[list["DashboardTile"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardTile.position",
        lazy="selectin",
    )


class DashboardTile(Base):
    """One pinned query."""

    __tablename__ = "dashboard_tiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dashboard_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    # Deleting a connection must not silently leave a tile pointing at nothing
    # it can explain, so the tile survives and reports the connection as gone.
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    query_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(200))
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str] = mapped_column(Text)
    chart: Mapped[dict] = mapped_column(JSON, default=dict)
    """The chart spec the user had on screen when pinning - type and axes.
    Empty means "re-derive it", which is what a tile pinned from a table does."""

    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    dashboard: Mapped[Dashboard] = relationship(back_populates="tiles")
