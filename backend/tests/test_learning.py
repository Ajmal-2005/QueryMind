"""Corrections (F22), suggestions (F23), glossary (F24), semantic cache (F25)."""

import pytest
from sqlalchemy.orm import Session

from app.models.query import Query, QueryStatus
from app.services.cache.semantic import SIMILARITY_THRESHOLD, compatible
from app.services.cache.semantic import lookup as semantic_lookup
from app.services.learning import glossary as glossary_service
from app.services.learning.corrections import record_correction, similar_examples
from app.services.learning.suggestions import suggest


@pytest.fixture
def indexed(db: Session, demo_connection):
    from app.services.linking.indexer import index_connection

    index_connection(db, demo_connection)
    return demo_connection


def _executed(db: Session, connection, question: str, sql: str) -> Query:
    row = Query(
        user_id=connection.user_id,
        connection_id=connection.id,
        question=question,
        generated_sql=sql,
        final_sql=sql,
        status=QueryStatus.EXECUTED,
    )
    db.add(row)
    db.commit()
    return row


# --------------------------------------------------------------- corrections


def test_a_correction_is_retrieved_as_an_example(db: Session, demo_connection) -> None:
    record_correction(
        db,
        user_id=demo_connection.user_id,
        connection_id=demo_connection.id,
        question="total revenue by region",
        corrected_sql="SELECT region, SUM(total_amount) FROM orders GROUP BY region",
    )

    examples = similar_examples(db, demo_connection.id, "total revenue by region")
    assert examples
    assert examples[0].source == "correction"
    assert "SUM(total_amount)" in examples[0].sql


def test_a_correction_outranks_an_equally_similar_success(
    db: Session, demo_connection
) -> None:
    """A query a human fixed is better evidence than one that merely ran."""
    question = "total revenue by region"
    _executed(db, demo_connection, question, "SELECT 1 AS wrong_but_ran")
    record_correction(
        db,
        user_id=demo_connection.user_id,
        connection_id=demo_connection.id,
        question=question,
        corrected_sql="SELECT region, SUM(total_amount) FROM orders GROUP BY region",
    )

    examples = similar_examples(db, demo_connection.id, question)
    assert examples[0].source == "correction"


def test_unverified_corrections_are_never_taught(db: Session, demo_connection) -> None:
    record_correction(
        db,
        user_id=demo_connection.user_id,
        connection_id=demo_connection.id,
        question="total revenue by region",
        corrected_sql="SELECT nonsense FROM nowhere",
        verified=False,
    )
    examples = similar_examples(db, demo_connection.id, "total revenue by region")
    assert all(e.source != "correction" for e in examples)


def test_irrelevant_examples_are_left_out(db: Session, demo_connection) -> None:
    """Three examples about the wrong thing cost the same tokens as three good ones."""
    _executed(db, demo_connection, "how many suppliers are in Germany", "SELECT 1")
    examples = similar_examples(
        db, demo_connection.id, "monthly revenue trend for premium subscriptions"
    )
    assert examples == []


def test_examples_are_capped_and_deduplicated(db: Session, demo_connection) -> None:
    sql = "SELECT region, SUM(total_amount) FROM orders GROUP BY region"
    for n in range(6):
        _executed(db, demo_connection, f"revenue by region {n}", sql)

    examples = similar_examples(db, demo_connection.id, "revenue by region", limit=3)
    # Identical SQL, so one lesson - not three copies of it.
    assert len(examples) == 1


def test_examples_are_scoped_to_the_connection(db: Session, demo_connection) -> None:
    _executed(db, demo_connection, "revenue by region", "SELECT 1")
    assert similar_examples(db, "some-other-connection", "revenue by region") == []


# -------------------------------------------------------------- suggestions


def test_suggestions_come_from_the_indexed_schema(db: Session, indexed) -> None:
    suggestions = suggest(db, indexed.id)
    assert suggestions

    text = " ".join(s.question.lower() for s in suggestions)
    # The demo schema's real tables, not hardcoded starters.
    assert "order" in text or "customer" in text or "product" in text
    assert all(s.reason for s in suggestions)


def test_suggestions_are_unique_and_capped(db: Session, indexed) -> None:
    suggestions = suggest(db, indexed.id, limit=4)
    assert len(suggestions) <= 4
    assert len({s.question for s in suggestions}) == len(suggestions)


def test_an_unindexed_connection_offers_nothing(db: Session, demo_connection) -> None:
    """Better no starter than one the schema cannot answer."""
    assert suggest(db, demo_connection.id) == []


# ----------------------------------------------------------------- glossary


def _term(db: Session, connection, term: str, definition: str, sql: str | None = None):
    from app.models.learning import GlossaryTerm

    entry = GlossaryTerm(
        connection_id=connection.id,
        term=term,
        definition=definition,
        sql_expression=sql,
    )
    db.add(entry)
    db.commit()
    return entry


def test_a_defined_term_is_matched_in_a_question(db: Session, demo_connection) -> None:
    _term(
        db,
        demo_connection,
        "active customer",
        "ordered in the last 90 days",
        "o.created_at >= date('now', '-90 days')",
    )
    matched = glossary_service.match(
        db, demo_connection.id, "how many active customers do we have"
    )
    assert [m.term for m in matched] == ["active customer"]


def test_matching_is_case_and_plural_insensitive(db: Session, demo_connection) -> None:
    _term(db, demo_connection, "active customer", "ordered recently")
    assert glossary_service.match(db, demo_connection.id, "Active Customers by region")


def test_an_undefined_term_matches_nothing(db: Session, demo_connection) -> None:
    _term(db, demo_connection, "active customer", "ordered recently")
    assert (
        glossary_service.match(db, demo_connection.id, "total revenue by month") == []
    )


def test_the_more_specific_definition_leads(db: Session, demo_connection) -> None:
    _term(db, demo_connection, "customer", "anyone with an account")
    _term(db, demo_connection, "active customer", "ordered in the last 90 days")

    matched = glossary_service.match(db, demo_connection.id, "count active customers")
    assert matched[0].term == "active customer"


def test_rendered_glossary_tells_the_model_not_to_substitute(
    db: Session, demo_connection
) -> None:
    _term(
        db, demo_connection, "churn", "cancelled within 30 days", "status = 'churned'"
    )
    rendered = glossary_service.render(
        glossary_service.match(db, demo_connection.id, "what is our churn")
    )
    assert "do not substitute your own" in rendered
    assert "status = 'churned'" in rendered


# ----------------------------------------------------------- semantic cache


def test_an_identical_question_is_left_to_the_sql_cache(
    db: Session, demo_connection
) -> None:
    question = "total revenue by region"
    _executed(db, demo_connection, question, "SELECT 1")
    assert (
        semantic_lookup(db, demo_connection.id, question, demo_connection.user_id)
        is None
    )


def test_a_rephrased_question_reuses_the_earlier_sql(
    db: Session, demo_connection
) -> None:
    sql = "SELECT region, SUM(total_amount) FROM orders GROUP BY region"
    _executed(db, demo_connection, "total revenue by region", sql)

    hit = semantic_lookup(
        db, demo_connection.id, "total revenue by region?", demo_connection.user_id
    )
    assert hit is not None
    assert hit.sql == sql
    assert hit.similarity >= SIMILARITY_THRESHOLD


def test_an_unrelated_question_is_not_served(db: Session, demo_connection) -> None:
    _executed(db, demo_connection, "total revenue by region", "SELECT 1")
    assert (
        semantic_lookup(
            db,
            demo_connection.id,
            "list every supplier in Germany",
            demo_connection.user_id,
        )
        is None
    )


def test_negation_blocks_a_hit_however_similar() -> None:
    """The opposite of a question is its nearest neighbour in embedding space."""
    assert not compatible("customers in the north", "customers not in the north")
    assert not compatible("orders excluding refunds", "orders including refunds")


def test_a_different_number_blocks_a_hit() -> None:
    """'top 5' and 'top 50' are different questions."""
    assert not compatible("top 5 products", "top 50 products")
    assert compatible("top 5 products", "top 5 products by price")


def test_the_cache_does_not_cross_users(db: Session, demo_connection) -> None:
    """Reusing a colleague's SQL leaks what they have been asking."""
    _executed(db, demo_connection, "total revenue by region", "SELECT 1")
    assert (
        semantic_lookup(
            db, demo_connection.id, "total revenue by region?", "a-different-user"
        )
        is None
    )
