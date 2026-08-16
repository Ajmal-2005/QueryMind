"""Learning from corrections (F22).

The wiring for this was left in place at Phase 2: `_few_shot_examples` picked
the most recent successes, with a note saying Phase 5 would select by
similarity instead. This is that swap.

Why it matters more than it sounds. Recency selects whatever happened last,
which bears no relationship to the question being asked now — three examples
about product inventory teach nothing about a revenue question, and they cost
the same tokens as three good ones. Similarity selects the example that
actually demonstrates the join, the filter or the date handling the current
question needs.

A correction is a stronger signal than a success, and is ranked above one:
a query the user *fixed* is a place the system got it wrong and was told the
right answer. That is the most valuable training data this application ever
sees, and it is why the corrections table exists at all.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.learning import Correction
from app.models.query import Query, QueryStatus
from app.services.linking.embeddings import Embedder, cosine_similarity, get_embedder

log = get_logger(__name__)

MAX_EXAMPLES = 3

# Below this, an "example" is about something else entirely and is worse than
# no example — it spends tokens and anchors the model on the wrong pattern.
MIN_SIMILARITY = 0.15

# How far a correction's similarity is boosted over a plain success. Enough to
# win a close contest, not enough to drag in an unrelated correction.
CORRECTION_BONUS = 0.15

# Candidates fetched per source before any embedding happens.
CANDIDATE_LIMIT = 200

# How many survive the lexical pre-filter and actually get embedded.
#
# Embedding 200 questions into 1,536 dimensions and taking 200 cosines is pure
# Python, and the cost grows with every question ever asked. Measured at ~100
# rows of history it was tens of milliseconds — not yet a problem, but one
# whose slope is wrong. The pre-filter bounds it with set arithmetic first.
EMBED_LIMIT = 40


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _prefilter(question: str, candidates: list, key, limit: int = EMBED_LIMIT) -> list:
    """Cheapest-first shortlisting before the expensive step.

    Word overlap is a poor similarity measure and a fine *filter*: a past
    question sharing no content word with this one will not survive embedding
    ranking either, so paying to embed it is waste. Ties keep the original
    order, which is recency.
    """
    if len(candidates) <= limit:
        return candidates

    wanted = _tokens(question)
    if not wanted:
        return candidates[:limit]

    scored = sorted(
        candidates,
        key=lambda c: len(wanted & _tokens(key(c))),
        reverse=True,
    )
    return scored[:limit]


@dataclass
class Example:
    question: str
    sql: str
    score: float
    source: str
    """'correction' or 'history' — surfaced so provenance stays visible."""


def record_correction(
    db: Session,
    user_id: str,
    connection_id: str,
    question: str,
    corrected_sql: str,
    original_sql: str | None = None,
    query_id: str | None = None,
    note: str | None = None,
    verified: bool = True,
    embedder: Embedder | None = None,
) -> Correction:
    """Save SQL a user fixed by hand.

    `verified` must reflect whether the corrected SQL actually passed the
    gates and ran. An unverified correction is stored — it is still evidence
    for the Phase 6 error taxonomy — but never retrieved as an example.
    """
    embedder = embedder or get_embedder()

    correction = Correction(
        query_id=query_id,
        user_id=user_id,
        connection_id=connection_id,
        question=question,
        original_sql=original_sql,
        corrected_sql=corrected_sql,
        note=note,
        verified=verified,
        # Of the question: retrieval matches on what was asked, not on the SQL.
        embedding=embedder.embed([question])[0],
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)

    log.info(
        "correction_recorded",
        connection_id=connection_id,
        verified=verified,
        embedder=embedder.name,
    )
    return correction


def similar_examples(
    db: Session,
    connection_id: str,
    question: str,
    limit: int = MAX_EXAMPLES,
    embedder: Embedder | None = None,
) -> list[Example]:
    """The most relevant past queries to show the model as examples."""
    embedder = embedder or get_embedder()
    query_vector = embedder.embed([question])[0]
    scored: list[Example] = []

    corrections = db.scalars(
        select(Correction)
        .where(
            Correction.connection_id == connection_id,
            Correction.verified.is_(True),
        )
        .order_by(Correction.created_at.desc())
        .limit(CANDIDATE_LIMIT)
    ).all()

    for correction in _prefilter(
        question, [c for c in corrections if c.embedding], lambda c: c.question
    ):
        scored.append(
            Example(
                question=correction.question,
                sql=correction.corrected_sql,
                score=cosine_similarity(query_vector, correction.embedding)
                + CORRECTION_BONUS,
                source="correction",
            )
        )

    # Successful history has no stored embedding — queries are not indexed —
    # so the questions are embedded here. One batch call, not one per row.
    rows = db.execute(
        select(Query.question, Query.final_sql)
        .where(
            Query.connection_id == connection_id,
            Query.status == QueryStatus.EXECUTED,
            Query.final_sql.is_not(None),
        )
        .order_by(Query.created_at.desc())
        .limit(CANDIDATE_LIMIT)
    ).all()

    history = _prefilter(
        question, [(q, s) for q, s in rows if s and q], lambda pair: pair[0]
    )
    if history:
        vectors = embedder.embed([q for q, _ in history])
        for (past_question, sql), vector in zip(history, vectors, strict=False):
            scored.append(
                Example(
                    question=past_question,
                    sql=sql,
                    score=cosine_similarity(query_vector, vector),
                    source="history",
                )
            )

    scored.sort(key=lambda e: e.score, reverse=True)

    chosen: list[Example] = []
    seen: set[str] = set()
    for example in scored:
        if example.score < MIN_SIMILARITY:
            break
        # The same question corrected twice, or asked and then corrected,
        # would otherwise fill the example budget with one lesson.
        key = " ".join(example.sql.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(example)
        if len(chosen) >= limit:
            break

    if chosen:
        log.info(
            "examples_selected",
            count=len(chosen),
            corrections=sum(1 for e in chosen if e.source == "correction"),
            top_score=round(chosen[0].score, 3),
        )
    return chosen


__all__ = [
    "CORRECTION_BONUS",
    "MIN_SIMILARITY",
    "Example",
    "record_correction",
    "similar_examples",
]
