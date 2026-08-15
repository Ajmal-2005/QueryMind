"""The embedding layer and its local fallback."""

from app.models.schema_index import EMBEDDING_DIM
from app.services.linking.embeddings import (
    HashingEmbedder,
    cosine_similarity,
    get_embedder,
)


def test_embedding_has_the_declared_dimension() -> None:
    [vector] = HashingEmbedder().embed(["orders table"])
    assert len(vector) == EMBEDDING_DIM


def test_embedding_is_deterministic() -> None:
    # Reproducible retrieval evaluation depends on this.
    first = HashingEmbedder().embed(["customer orders"])
    second = HashingEmbedder().embed(["customer orders"])
    assert first == second


def test_embeddings_are_unit_length() -> None:
    [vector] = HashingEmbedder().embed(["orders and customers"])
    magnitude = sum(v * v for v in vector) ** 0.5
    assert abs(magnitude - 1.0) < 1e-9


def test_batch_preserves_input_order() -> None:
    embedder = HashingEmbedder()
    batch = embedder.embed(["alpha text", "beta text", "gamma text"])
    individually = [embedder.embed([t])[0] for t in ["alpha", "beta", "gamma"]]

    assert len(batch) == 3
    for i in range(3):
        assert cosine_similarity(batch[i], individually[i]) > 0.4


def test_empty_text_produces_a_zero_vector() -> None:
    [vector] = HashingEmbedder().embed([""])
    assert not any(vector)


def test_related_text_scores_higher_than_unrelated() -> None:
    embedder = HashingEmbedder()
    query, related, unrelated = embedder.embed(
        [
            "customer orders and purchases",
            "orders table holds one row per customer purchase",
            "shipping warehouse pallet dimensions",
        ]
    )

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_morphological_variants_are_similar() -> None:
    # Trigrams are what make 'customer' and 'customers' land near each other.
    a, b = HashingEmbedder().embed(["customer", "customers"])
    assert cosine_similarity(a, b) > 0.5


def test_cosine_of_identical_vectors_is_one() -> None:
    [vector] = HashingEmbedder().embed(["orders"])
    assert abs(cosine_similarity(vector, vector) - 1.0) < 1e-9


def test_cosine_handles_degenerate_input() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_get_embedder_falls_back_to_local_without_a_key() -> None:
    # Phase 0/1 run with no OPENAI_API_KEY configured.
    embedder = get_embedder()

    assert embedder.name == "hashing-local"
    assert embedder.dimension == EMBEDDING_DIM
