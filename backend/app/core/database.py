"""Application database session management.

This is the *app's own* Postgres (users, connections, schema index, history)
— not the user's target database, which is handled by the connection
service with a separate read-only engine.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for every application model."""


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        # check_same_thread is a SQLite-only concern; pooling options below
        # are not valid for its default pool.
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }


engine = create_engine(settings.DATABASE_URL, echo=False, **_engine_kwargs())

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that always closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
