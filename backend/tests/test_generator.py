"""Generation-stage behaviour: intent, retrieval, prompt, and session context.

Exercised through the full pipeline, since that is the only entry point.
The correction loop itself is covered in `test_correction.py`.
"""

import pytest

from app.services.generation.intent import QuestionType
from app.services.generation.llm import LLMError, ScriptedClient
from app.services.generation.pipeline import run
from app.services.linking.indexer import index_connection


@pytest.fixture
def indexed(db, demo_connection):
    index_connection(db, demo_connection)
    return demo_connection


def _client(sql: str = "SELECT COUNT(*) FROM customers", **overrides):
    payload = {
        "sql": sql,
        "confidence": 0.9,
        "explanation": "Counts the rows in customers.",
        "assumptions": [],
    }
    payload.update(overrides)
    return ScriptedClient([payload])


def _run(db, connection, client, question="How many customers?", **kwargs):
    return run(
        db, connection, question, user_id=connection.user_id, client=client, **kwargs
    )


def test_pipeline_produces_sql(db, indexed) -> None:
    outcome = _run(db, indexed, _client())

    assert outcome.succeeded
    assert outcome.generation.sql == "SELECT COUNT(*) FROM customers"
    assert outcome.generation.confidence == 0.9


def test_pipeline_classifies_intent(db, indexed) -> None:
    outcome = _run(db, indexed, _client())
    assert outcome.intent.question_type is QuestionType.AGGREGATION


def test_pipeline_retrieves_the_relevant_tables(db, indexed) -> None:
    outcome = _run(db, indexed, _client())

    assert outcome.retrieval is not None
    assert "customers" in outcome.retrieval.table_names
    # Directly retrieved tables are capped at top_k; anything beyond that
    # arrived via foreign-key expansion and is flagged as such.
    direct = [t for t in outcome.retrieval.tables if not t.via_expansion]
    assert len(direct) <= 6


def test_prompt_carries_the_schema(db, indexed) -> None:
    client = _client()
    _run(db, indexed, client)

    assert "CREATE TABLE customers" in client.calls[0].user


def test_prompt_carries_the_dialect_rules(db, indexed) -> None:
    client = _client()
    _run(db, indexed, client)

    assert "SQLite" in client.calls[0].user


def test_unindexed_connection_is_reported_clearly(db, demo_connection) -> None:
    outcome = _run(db, demo_connection, _client())

    assert not outcome.succeeded
    assert "index" in outcome.error.lower()


def test_provider_failure_is_reported_not_raised(db, indexed) -> None:
    outcome = _run(db, indexed, ScriptedClient([LLMError("provider is down")]))

    assert not outcome.succeeded
    assert "provider is down" in outcome.error


def test_persistence_can_be_disabled(db, indexed) -> None:
    outcome = _run(db, indexed, _client(), persist=False)
    assert outcome.query_id is None


# --------------------------------------------------------- session context


def test_follow_up_resolves_against_the_session(db, indexed) -> None:
    _run(
        db,
        indexed,
        _client(),
        question="What was total revenue by category?",
        session_id="s1",
    )

    client = _client()
    outcome = _run(
        db, indexed, client, question="break that down by region", session_id="s1"
    )

    assert outcome.intent.is_follow_up
    assert "total revenue by category" in outcome.intent.resolved_question
    assert "by region" in client.calls[0].user


def test_history_does_not_leak_across_sessions(db, indexed) -> None:
    _run(db, indexed, _client(), question="What was total revenue?", session_id="a")

    outcome = _run(
        db, indexed, _client(), question="break that down by region", session_id="b"
    )
    assert not outcome.intent.is_follow_up


def test_a_successful_query_becomes_a_few_shot_example(db, indexed) -> None:
    # Only executed queries qualify — the wiring Phase 5 replaces with
    # similarity selection.
    _run(db, indexed, _client(), question="How many customers?")

    client = _client()
    _run(db, indexed, client, question="How many orders?")

    assert "Examples of correct SQL" in client.calls[0].user


def test_a_failed_query_does_not_become_an_example(db, indexed) -> None:
    _run(db, indexed, ScriptedClient([_client("SELECT * FROM nope").responses[0]] * 3))

    client = _client()
    _run(db, indexed, client, question="How many orders?")

    assert "Examples of correct SQL" not in client.calls[0].user
