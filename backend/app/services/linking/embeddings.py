"""Embedding providers for schema descriptions.

Two implementations behind one interface. ``OpenAIEmbedder`` is the real one
from the proposal (``text-embedding-3-small``). ``HashingEmbedder`` is a
deterministic local fallback so the indexing pipeline — and its tests — run
with no API key, no network, and no cost.

The fallback is a hashing vectorizer, not a learned model: it captures
lexical overlap only, and will not match "revenue" to "sales". It is honest
development infrastructure, not a substitute for real embeddings, and any
benchmark result must record which provider produced it.
"""

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schema_index import EMBEDDING_DIM

log = get_logger(__name__)

OPENAI_MODEL = "text-embedding-3-small"
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Weight of a character trigram relative to a whole token. Singular/plural
# mismatches between a schema ("orders") and a question ("order") are common
# enough that morphological overlap needs real weight, but not so much that
# incidental substring collisions outrank exact word matches.
TRIGRAM_WEIGHT = 0.5


@runtime_checkable
class Embedder(Protocol):
    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class HashingEmbedder:
    """Deterministic bag-of-words vectorizer.

    Each token is hashed to a bucket and its sign; sub-word trigrams are
    added too, so ``customer`` and ``customers`` land near each other rather
    than in unrelated buckets.
    """

    name = "hashing-local"

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.dimension = dimension

    def _bucket(self, token: str) -> tuple[int, float]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % self.dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return index, sign

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            tokens = _tokenize(text)

            for token in tokens:
                index, sign = self._bucket(token)
                vector[index] += sign

                # Character trigrams give morphological tolerance.
                for i in range(len(token) - 2):
                    tri_index, tri_sign = self._bucket(token[i : i + 3])
                    vector[tri_index] += tri_sign * TRIGRAM_WEIGHT

            vectors.append(_l2_normalize(vector))
        return vectors


class OpenAIEmbedder:
    """The production embedder from the proposal."""

    name = OPENAI_MODEL

    def __init__(self, api_key: str, dimension: int = EMBEDDING_DIM) -> None:
        self.api_key = api_key
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        # The endpoint accepts batches; one request per index run beats one
        # per table on a 400-table schema.
        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": OPENAI_MODEL, "input": texts},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()

        # Ordering is guaranteed by index, not by position — sort explicitly.
        ordered = sorted(payload["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in ordered]


def get_embedder() -> Embedder:
    """Pick the embedder from configuration."""
    if settings.OPENAI_API_KEY:
        return OpenAIEmbedder(settings.OPENAI_API_KEY)

    log.info("using_local_embedder", reason="OPENAI_API_KEY not set")
    return HashingEmbedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors, 0.0 if either is degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
