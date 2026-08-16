"""Semantic query cache (F25).

Phase 4's cache keys on the *SQL*, so it only helps once the model has already
been called — the expensive part is over by then. This one keys on the
*question*, and skips generation entirely when someone asks something the
system has already answered in different words.

"What was revenue last quarter" and "how much did we make in Q3" should not
cost two model calls.

The obvious danger is answering the wrong question. Three things hold it back:

1. **A high threshold.** 0.93 cosine, far above the 0.15 used to pick a
   few-shot example, because the cost of being wrong is completely different.
   A bad example wastes tokens; a bad cache hit returns someone else's answer
   and says nothing.
2. **Negation and comparative guards.** "revenue in the north" and "revenue
   *not* in the north" are close in every embedding space and are opposites.
   Any difference in the negation, comparison or superlative words between two
   questions disqualifies the hit outright, whatever the score.
3. **It is always visible.** A served hit reports the question it matched and
   the score. The user can see they were given the answer to a slightly
   different question and re-run it.

The local hashing embedder makes this mostly lexical, so paraphrase across
vocabulary ("revenue" vs "sales") will not match until a real embedding
provider is configured. That limitation is honest and is reported by name.
"""

import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.query import Query, QueryStatus
from app.services.linking.embeddings import Embedder, cosine_similarity, get_embedder

log = get_logger(__name__)

# Deliberately severe. See the module docstring — the failure mode here is
# confidently answering a question nobody asked.
SIMILARITY_THRESHOLD = 0.93

CANDIDATE_LIMIT = 100

# Candidates that actually get embedded. Same reasoning as the correction
# selector: embedding every past question on every request is a cost that
# grows with history, and a load test caught it doing exactly that.
EMBED_LIMIT = 40

# Words whose presence or absence flips meaning without moving an embedding
# far. Any disagreement on these blocks a hit regardless of similarity.
POLARITY_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "without",
        "excluding",
        "except",
        "exclude",
        "top",
        "bottom",
        "best",
        "worst",
        "highest",
        "lowest",
        "most",
        "least",
        "more",
        "less",
        "fewer",
        "greater",
        "above",
        "below",
        "over",
        "under",
        "increase",
        "decrease",
        "growth",
        "decline",
        "gained",
        "lost",
        "before",
        "after",
        "since",
        "until",
    }
)

# Numbers change meaning too: "top 5" and "top 50" are different questions.
_NUMBER = re.compile(r"\b\d+\b")


@dataclass
class SemanticHit:
    question: str
    """The earlier question this matched."""

    sql: str
    similarity: float
    query_id: str
    embedder: str


def _polarity(question: str) -> frozenset[str]:
    words = set(re.findall(r"[a-z']+", question.lower()))
    return frozenset(words & POLARITY_WORDS)


def _numbers(question: str) -> frozenset[str]:
    return frozenset(_NUMBER.findall(question))


def compatible(a: str, b: str) -> bool:
    """Do two questions agree on the words that decide meaning?

    Cheap, and it catches the class of near-miss that similarity cannot: the
    opposite of a question is its nearest neighbour in embedding space.
    """
    return _polarity(a) == _polarity(b) and _numbers(a) == _numbers(b)


def lookup(
    db: Session,
    connection_id: str,
    question: str,
    user_id: str,
    embedder: Embedder | None = None,
) -> SemanticHit | None:
    """Find an earlier question close enough to reuse its SQL.

    Scoped to the user as well as the connection. Reusing a colleague's SQL
    would leak what they have been asking, which is not something a cache
    should decide to do.
    """
    if not settings.SEMANTIC_CACHE_ENABLED:
        return None

    started = time.perf_counter()
    embedder = embedder or get_embedder()

    rows = db.execute(
        select(Query.id, Query.question, Query.final_sql)
        .where(
            Query.connection_id == connection_id,
            Query.user_id == user_id,
            Query.status == QueryStatus.EXECUTED,
            Query.final_sql.is_not(None),
        )
        .order_by(Query.created_at.desc())
        .limit(CANDIDATE_LIMIT)
    ).all()

    candidates = [
        (qid, q, sql)
        for qid, q, sql in rows
        # An identical question is served by the SQL cache already; this is
        # for the differently-worded ones.
        if sql and q and q.strip().lower() != question.strip().lower()
    ]
    if not candidates:
        return None

    # Word overlap first, embeddings second. A past question sharing no
    # content word with this one cannot clear a 0.93 threshold, so paying to
    # embed it is waste.
    if len(candidates) > EMBED_LIMIT:
        wanted = set(re.findall(r"[a-z0-9]+", question.lower()))
        candidates = sorted(
            candidates,
            key=lambda c: len(wanted & set(re.findall(r"[a-z0-9]+", c[1].lower()))),
            reverse=True,
        )[:EMBED_LIMIT]

    vectors = embedder.embed([question] + [q for _, q, _ in candidates])
    query_vector, candidate_vectors = vectors[0], vectors[1:]

    best: SemanticHit | None = None
    for (query_id, past, sql), vector in zip(
        candidates, candidate_vectors, strict=False
    ):
        similarity = cosine_similarity(query_vector, vector)
        if similarity < SIMILARITY_THRESHOLD:
            continue
        if not compatible(question, past):
            log.info("semantic_cache_polarity_block", similarity=round(similarity, 3))
            continue
        if best is None or similarity > best.similarity:
            best = SemanticHit(
                question=past,
                sql=sql,
                similarity=similarity,
                query_id=query_id,
                embedder=embedder.name,
            )

    if best:
        log.info(
            "semantic_cache_hit",
            similarity=round(best.similarity, 3),
            embedder=best.embedder,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    return best


__all__ = ["SIMILARITY_THRESHOLD", "SemanticHit", "compatible", "lookup"]
