"""Schema linking — retrieving the tables a question actually needs.

This is the component that decides whether the system works on real
databases. A 400-table schema does not fit in a prompt; the answer is to
retrieve a subgraph of six.

Retrieval is hybrid: dense embeddings catch paraphrase ("revenue" → a table
described as holding sales totals), BM25 catches exact identifiers a dense
model blurs (`cust_ref_id_v2`). Neither alone is enough, so the two rankings
are fused and then expanded along foreign keys, because a table set that is
individually relevant is frequently not joinable.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.schema_index import SchemaTable
from app.services.linking.embeddings import Embedder, cosine_similarity, get_embedder
from app.services.linking.graph import ForeignKeyGraph
from app.services.linking.indexer import load_graph

log = get_logger(__name__)

DEFAULT_TOP_K = 6
DEFAULT_HOPS = 1

# Reciprocal-rank fusion constant. 60 is the value from the original RRF
# paper and is deliberately large: it flattens the contribution of top ranks
# so one retriever cannot dominate the other on a single confident hit.
RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Words that appear in nearly every schema description and would otherwise
# dominate BM25 scoring.
STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that
    the to was were will with table column columns row rows primary key keys
    joins value values approximately known concepts""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class RetrievedTable:
    table_name: str
    description: str
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    via_expansion: bool = False
    """True when this table was pulled in by foreign-key expansion rather
    than by either retriever — the join tables the proposal's example
    depends on arrive this way."""


@dataclass
class RetrievalResult:
    tables: list[RetrievedTable]
    graph: ForeignKeyGraph
    embedder: str
    duration_ms: float = 0.0
    expanded_count: int = field(default=0)

    @property
    def table_names(self) -> list[str]:
        return [t.table_name for t in self.tables]


class BM25:
    """Okapi BM25 over table descriptions.

    Implemented directly rather than pulled in as a dependency: the corpus is
    a few hundred short documents, and the scoring is 20 lines.
    """

    K1 = 1.5
    B = 0.75

    def __init__(self, documents: list[list[str]]) -> None:
        self.documents = documents
        self.doc_count = len(documents)
        self.doc_lengths = [len(d) for d in documents]
        self.avg_length = (
            sum(self.doc_lengths) / self.doc_count if self.doc_count else 0.0
        )

        self.term_frequencies = [Counter(d) for d in documents]

        document_frequency: Counter[str] = Counter()
        for doc in documents:
            document_frequency.update(set(doc))

        # Standard BM25 IDF with the +0.5 smoothing, floored at zero so a term
        # present in more than half the corpus cannot score negatively.
        self.idf = {
            term: max(
                0.0,
                math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1.0),
            )
            for term, freq in document_frequency.items()
        }

    def score(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.doc_count
        if not self.doc_count or not self.avg_length:
            return scores

        for index in range(self.doc_count):
            frequencies = self.term_frequencies[index]
            length = self.doc_lengths[index]
            total = 0.0
            for term in query_tokens:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                numerator = frequency * (self.K1 + 1)
                denominator = frequency + self.K1 * (
                    1 - self.B + self.B * length / self.avg_length
                )
                total += self.idf.get(term, 0.0) * numerator / denominator
            scores[index] = total
        return scores


def _rank_order(scores: list[float]) -> list[int]:
    """Indices sorted by descending score, ties broken by position."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def _reciprocal_rank_fusion(
    dense_order: list[int], sparse_order: list[int], count: int
) -> tuple[list[int], dict[int, float]]:
    """Fuse two rankings without needing their scores to be comparable.

    Dense cosine similarity and BM25 live on different scales, and
    normalising them against each other is fragile. RRF only reads position,
    so it sidesteps the calibration problem entirely.
    """
    scores: dict[int, float] = {i: 0.0 for i in range(count)}

    for rank, index in enumerate(dense_order):
        scores[index] += 1.0 / (RRF_K + rank + 1)
    for rank, index in enumerate(sparse_order):
        scores[index] += 1.0 / (RRF_K + rank + 1)

    fused = sorted(scores, key=lambda i: (-scores[i], i))
    return fused, scores


def retrieve(
    db: Session,
    connection_id: str,
    question: str,
    top_k: int = DEFAULT_TOP_K,
    hops: int = DEFAULT_HOPS,
    embedder: Embedder | None = None,
    mode: str = "hybrid",
) -> RetrievalResult:
    """Retrieve the schema subgraph relevant to ``question``.

    ``mode`` selects which retrievers contribute, and exists so the Phase 6
    ablation can isolate each one's contribution to schema-linking recall:

    - ``hybrid`` — dense + BM25 fused with reciprocal rank fusion. The default
      and the configuration the proposal describes.
    - ``dense`` — embeddings only.
    - ``sparse`` — BM25 only.

    Setting ``hops=0`` disables foreign-key expansion, which is the other arm
    of the ablation. Both knobs are here rather than in the harness so the
    thing being measured is the production code path, not a reimplementation
    of it that could quietly differ.
    """
    import time

    started = time.perf_counter()
    embedder = embedder or get_embedder()

    tables = list(
        db.scalars(
            select(SchemaTable)
            .where(SchemaTable.connection_id == connection_id)
            .order_by(SchemaTable.table_name)
        )
    )
    graph = load_graph(db, connection_id)

    if not tables:
        return RetrievalResult(
            tables=[], graph=graph, embedder=embedder.name, duration_ms=0.0
        )

    # --- dense ---
    query_vector = embedder.embed([question])[0]
    dense_scores = [cosine_similarity(query_vector, t.embedding or []) for t in tables]
    dense_order = _rank_order(dense_scores)

    # --- sparse ---
    # The table name is prepended so an exact name match scores strongly even
    # when the description is dominated by column vocabulary.
    corpus = [tokenize(f"{t.table_name} {t.description}") for t in tables]
    sparse_scores = BM25(corpus).score(tokenize(question))
    sparse_order = _rank_order(sparse_scores)

    def _by_rank(order: list[int]) -> list[float]:
        """Reciprocal-rank score per table, so single-retriever modes report
        on the same scale as the fused one."""
        scores = [0.0] * len(tables)
        for rank, index in enumerate(order):
            scores[index] = 1.0 / (1 + rank)
        return scores

    if mode == "dense":
        fused_order, fused_scores = dense_order, _by_rank(dense_order)
    elif mode == "sparse":
        fused_order, fused_scores = sparse_order, _by_rank(sparse_order)
    else:
        fused_order, fused_scores = _reciprocal_rank_fusion(
            dense_order, sparse_order, len(tables)
        )

    dense_positions = {index: rank for rank, index in enumerate(dense_order)}
    sparse_positions = {index: rank for rank, index in enumerate(sparse_order)}

    selected_indices = fused_order[:top_k]
    by_name = {t.table_name: t for t in tables}

    retrieved: list[RetrievedTable] = [
        RetrievedTable(
            table_name=tables[i].table_name,
            description=tables[i].description,
            score=round(fused_scores[i], 6),
            dense_rank=dense_positions[i],
            sparse_rank=sparse_positions[i],
        )
        for i in selected_indices
    ]

    # --- foreign-key expansion ---
    # Retrieval ranks tables independently, so it routinely returns two tables
    # with no direct edge between them. Adding their neighbours keeps the
    # subgraph joinable.
    core = {t.table_name for t in retrieved}
    expanded = graph.expand(core, hops=hops)

    for name in sorted(expanded - core):
        table = by_name.get(name)
        if table is None:
            continue
        retrieved.append(
            RetrievedTable(
                table_name=table.table_name,
                description=table.description,
                score=0.0,
                via_expansion=True,
            )
        )

    duration = (time.perf_counter() - started) * 1000
    log.info(
        "schema_linked",
        connection_id=connection_id,
        retrieved=len(core),
        expanded=len(retrieved) - len(core),
        duration_ms=round(duration, 1),
    )

    return RetrievalResult(
        tables=retrieved,
        graph=graph,
        embedder=embedder.name,
        duration_ms=duration,
        expanded_count=len(retrieved) - len(core),
    )
