"""The NL→SQL pipeline, end to end."""

import pytest

from app.models.query import Query, QueryStatus
from app.services.generation import generator
from app.services.generation.intent import QuestionType
from app.services.generation.llm import LLMError, ScriptedClient
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


def test_pipeline_produces_sql(db, indexed) -> None:
    result = generator.run(
        db,
        indexed,
        "How many customers do we have?",
        user_id=indexed.user_id,
        client=_client(),
    )

    assert result.succeeded
    assert result.generation.sql == "SELECT COUNT(*) FROM customers"
    assert result.generation.confidence == 0.9


def test_pipeline_classifies_intent(db, indexed) -> None:
    result = generator.run(
        db, indexed, "How many customers?", user_id=indexed.user_id, client=_client()
    )
    assert result.intent.question_type is QuestionType.AGGREGATION


def test_pipeline_retrieves_the_relevant_tables(db, indexed) -> None:
    result = generator.run(
        db, indexed, "How many customers?", user_id=indexed.user_id, client=_client()
    )

    assert result.retrieval is not None
    assert "customers" in result.retrieval.table_names
    # Directly retrieved tables are capped at top_k; anything beyond that came
    # from foreign-key expansion and is flagged as such.
    direct = [t for t in result.retrieval.tables if not t.via_expansion]
    assert len(direct) <= 6


def test_prompt_carries_the_schema(db, indexed) -> None:
    client = _client()
    generator.run(
        db, indexed, "How many customers?", user_id=indexed.user_id, client=client
    )

    prompt = client.calls[0]
    assert "CREATE TABLE customers" in prompt.user


def test_ambiguous_question_asks_instead_of_guessing(db, indexed) -> None:
    client = _client()
    result = generator.run(
        db, indexed, "show me something", user_id=indexed.user_id, client=client
    )

    assert result.needs_clarification
    assert result.intent.clarification
    assert result.generation is None
    # The model must not be called at all — guessing costs tokens and misleads.
    assert client.calls == []


def test_provider_failure_is_reported_not_raised(db, indexed) -> None:
    result = generator.run(
        db,
        indexed,
        "How many customers?",
        user_id=indexed.user_id,
        client=ScriptedClient([LLMError("provider is down")]),
    )

    assert not result.succeeded
    assert "provider is down" in result.error


def test_unindexed_connection_is_reported_clearly(db, demo_connection) -> None:
    result = generator.run(
        db,
        demo_connection,
        "How many customers?",
        user_id=demo_connection.user_id,
        client=_client(),
    )
    assert not result.succeeded
    assert "index" in result.error.lower()


def test_stage_timings_are_recorded(db, indexed) -> None:
    result = generator.run(
        db, indexed, "How many customers?", user_id=indexed.user_id, client=_client()
    )
    assert set(result.stage_timings) == {"intent", "retrieval", "generation", "total"}
    assert result.stage_timings["total"] > 0


def test_successful_query_is_persisted(db, indexed) -> None:
    result = generator.run(
        db, indexed, "How many customers?", user_id=indexed.user_id, client=_client()
    )

    record = db.get(Query, result.query_id)
    assert record.status is QueryStatus.GENERATED
    assert record.generated_sql == "SELECT COUNT(*) FROM customers"
    assert record.question == "How many customers?"


def test_failed_query_is_persisted_with_its_error(db, indexed) -> None:
    result = generator.run(
        db,
        indexed,
        "How many customers?",
        user_id=indexed.user_id,
        client=ScriptedClient([LLMError("boom")]),
    )

    record = db.get(Query, result.query_id)
    assert record.status is QueryStatus.FAILED
    assert "boom" in record.error_message


def test_persistence_can_be_disabled(db, indexed) -> None:
    result = generator.run(
        db,
        indexed,
        "How many customers?",
        user_id=indexed.user_id,
        client=_client(),
        persist=False,
    )
    assert result.query_id is None


def test_follow_up_resolves_against_the_session(db, indexed) -> None:
    generator.run(
        db,
        indexed,
        "What was total revenue by category?",
        user_id=indexed.user_id,
        session_id="s1",
        client=_client(),
    )

    client = _client()
    result = generator.run(
        db,
        indexed,
        "break that down by region",
        user_id=indexed.user_id,
        session_id="s1",
        client=client,
    )

    assert result.intent.is_follow_up
    assert "total revenue by category" in result.intent.resolved_question
    assert "by region" in client.calls[0].user


def test_history_does_not_leak_across_sessions(db, indexed) -> None:
    generator.run(
        db,
        indexed,
        "What was total revenue?",
        user_id=indexed.user_id,
        session_id="session-a",
        client=_client(),
    )

    result = generator.run(
        db,
        indexed,
        "break that down by region",
        user_id=indexed.user_id,
        session_id="session-b",
        client=_client(),
    )
    assert not result.intent.is_follow_up
