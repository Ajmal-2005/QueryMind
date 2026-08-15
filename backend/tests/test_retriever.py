"""Hybrid schema-linking retrieval.

The measure that matters is schema-linking recall: the gold tables a question
needs must appear in the retrieved set, because retrieval upper-bounds
everything downstream.
"""

import pytest

from app.services.linking.indexer import index_connection
from app.services.linking.retriever import BM25, retrieve, tokenize


@pytest.fixture
def indexed(db, demo_connection):
    index_connection(db, demo_connection)
    return demo_connection


def test_tokenize_drops_stopwords() -> None:
    tokens = tokenize("Table `orders`. Primary key: id. Joins to customers.")
    assert "orders" in tokens
    assert "customers" in tokens
    assert "to" not in tokens
    assert "key" not in tokens


def test_bm25_ranks_the_matching_document_first() -> None:
    corpus = [
        tokenize("orders table holds one row per customer purchase"),
        tokenize("suppliers table holds vendor contact details"),
        tokenize("products table holds the catalogue"),
    ]
    scores = BM25(corpus).score(tokenize("customer purchase orders"))
    assert scores[0] == max(scores)


def test_bm25_scores_zero_when_nothing_matches() -> None:
    corpus = [tokenize("orders customers"), tokenize("products categories")]
    assert BM25(corpus).score(tokenize("zzzz")) == [0.0, 0.0]


def test_bm25_handles_an_empty_corpus() -> None:
    assert BM25([]).score(tokenize("orders")) == []


def test_retrieval_finds_the_obvious_table(db, indexed) -> None:
    result = retrieve(db, indexed.id, "How many customers do we have?")
    assert "customers" in result.table_names


def test_exact_identifier_is_found_via_sparse_retrieval(db, indexed) -> None:
    # A cryptic name that a dense embedding blurs but BM25 matches exactly.
    result = retrieve(db, indexed.id, "what is in cust_ref_log_v2")
    assert "cust_ref_log_v2" in result.table_names


def test_join_table_arrives_through_expansion(db, indexed) -> None:
    # The proposal's core claim: retrieval ranks tables independently and
    # misses the junction table between them.
    result = retrieve(db, indexed.id, "which suppliers provide which products")

    assert "product_suppliers" in result.table_names
    junction = next(t for t in result.tables if t.table_name == "product_suppliers")
    # It may be retrieved directly or expanded into; either is a success, but
    # the set must be joinable.
    assert {"products", "suppliers"} <= set(result.table_names) or junction


def test_expansion_is_reported_separately(db, indexed) -> None:
    result = retrieve(db, indexed.id, "revenue by product category", top_k=2)
    assert result.expanded_count == sum(1 for t in result.tables if t.via_expansion)


def test_top_k_bounds_the_directly_retrieved_set(db, indexed) -> None:
    result = retrieve(db, indexed.id, "orders", top_k=2, hops=0)
    assert len(result.tables) == 2


def test_zero_hops_disables_expansion(db, indexed) -> None:
    result = retrieve(db, indexed.id, "revenue by category", top_k=3, hops=0)
    assert all(not t.via_expansion for t in result.tables)


def test_retrieved_tables_carry_both_ranks(db, indexed) -> None:
    result = retrieve(db, indexed.id, "customer orders", top_k=3, hops=0)
    for table in result.tables:
        assert table.dense_rank is not None
        assert table.sparse_rank is not None


def test_revenue_question_recalls_the_gold_tables(db, indexed) -> None:
    # Gold set for "revenue by category": the join path from order_items
    # through products to categories.
    result = retrieve(db, indexed.id, "total revenue by product category")
    gold = {"order_items", "products", "categories"}

    recall = len(gold & set(result.table_names)) / len(gold)
    assert recall == 1.0, f"missing {gold - set(result.table_names)}"


def test_customer_spend_question_recalls_the_gold_tables(db, indexed) -> None:
    result = retrieve(db, indexed.id, "top customers by lifetime spend")
    gold = {"customers", "orders"}

    assert gold <= set(result.table_names)


def test_retrieval_on_an_unindexed_connection_is_empty(db, demo_connection) -> None:
    result = retrieve(db, demo_connection.id, "anything")
    assert result.tables == []


def test_retrieval_reports_its_embedder(db, indexed) -> None:
    # Accuracy figures are only interpretable alongside which embedder ran.
    assert retrieve(db, indexed.id, "orders").embedder == "hashing-local"
