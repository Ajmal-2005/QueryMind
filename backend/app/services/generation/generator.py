"""Context lookups for the generation stage.

Session history for coreference resolution, and past successful queries for
few-shot selection. The orchestration that uses them lives in `pipeline.py`.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.query import Query, QueryStatus

HISTORY_TURNS = 4
MAX_EXAMPLES = 3


def _recent_questions(db: Session, session_id: str | None, user_id: str) -> list[str]:
    """Previous questions in this session, oldest first.

    Scoped to both session and user: a follow-up must never resolve against
    someone else's conversation, or against an unrelated one of your own.
    """
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
    """Past queries to use as in-context examples.

    Only queries that actually executed qualify — a syntactically valid one
    that failed at runtime would teach the model the wrong thing.

    Phase 5 selects these by embedding similarity to the current question;
    the most recent successes are a reasonable stand-in until then, and the
    wiring is what matters.
    """
    rows = db.execute(
        select(Query.question, Query.final_sql)
        .where(
            Query.connection_id == connection_id,
            Query.status == QueryStatus.EXECUTED,
            Query.final_sql.is_not(None),
        )
        .order_by(Query.created_at.desc())
        .limit(MAX_EXAMPLES)
    ).all()
    return [(question, sql) for question, sql in rows if sql]


__all__ = ["_few_shot_examples", "_recent_questions"]
