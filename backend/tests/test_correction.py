"""The self-correction loop.

Research question 2: can a loop driven by database error messages recover a
meaningful fraction of initially failed queries?

These tests establish the *mechanism* — that failures feed back, that repairs
land, and critically that safety rejections never retry. The recovery *rate*
is an empirical number that needs a real model and a benchmark; it cannot be
measured with scripted responses.
"""

import pytest

from app.models.query import Query, QueryStatus
from app.services.generation.llm import LLMError, ScriptedClient
from app.services.generation.pipeline import run
from app.services.linking.indexer import index_connection


@pytest.fixture
def indexed(db, demo_connection):
    index_connection(db, demo_connection)
    return demo_connection


def _reply(sql: str) -> dict:
    return {
        "sql": sql,
        "confidence": 0.8,
        "explanation": "Test query.",
        "assumptions": [],
    }


def _run(db, connection, client, question="How many customers?", **kwargs):
    return run(
        db, connection, question, user_id=connection.user_id, client=client, **kwargs
    )


def test_first_attempt_success_needs_no_correction(db, indexed) -> None:
    outcome = _run(
        db, indexed, ScriptedClient([_reply("SELECT COUNT(*) FROM customers")])
    )

    assert outcome.succeeded
    assert outcome.correction_attempts == 0
    assert not outcome.recovered_by_correction
    assert len(outcome.attempts) == 1


def test_bad_column_is_repaired_on_the_second_attempt(db, indexed) -> None:
    client = ScriptedClient(
        [
            _reply("SELECT COUNT(*) FROM customers WHERE regoin = 'North'"),
            _reply("SELECT COUNT(*) FROM customers WHERE region = 'North'"),
        ]
    )
    outcome = _run(db, indexed, client)

    assert outcome.succeeded
    assert outcome.correction_attempts == 1
    assert outcome.recovered_by_correction


def test_bad_table_is_repaired(db, indexed) -> None:
    client = ScriptedClient(
        [
            _reply("SELECT COUNT(*) FROM custmers"),
            _reply("SELECT COUNT(*) FROM customers"),
        ]
    )
    outcome = _run(db, indexed, client)

    assert outcome.succeeded
    assert outcome.correction_attempts == 1


def test_the_error_is_fed_back_into_the_repair_prompt(db, indexed) -> None:
    client = ScriptedClient(
        [
            _reply("SELECT COUNT(*) FROM custmers"),
            _reply("SELECT COUNT(*) FROM customers"),
        ]
    )
    _run(db, indexed, client)

    repair_prompt = client.calls[1].user
    assert "previous attempt failed" in repair_prompt
    assert "custmers" in repair_prompt
    # The "did you mean" hint is the part that makes the repair likely.
    assert "customers" in repair_prompt


def test_execution_errors_also_drive_a_repair(db, indexed) -> None:
    # This SQL passes every gate but fails at runtime: SQLite rejects the
    # aggregate in a WHERE clause.
    client = ScriptedClient(
        [
            _reply("SELECT id FROM orders WHERE COUNT(*) > 1"),
            _reply("SELECT id FROM orders LIMIT 1"),
        ]
    )
    outcome = _run(db, indexed, client)

    assert outcome.succeeded
    assert outcome.correction_attempts == 1


def test_the_loop_stops_at_the_attempt_cap(db, indexed) -> None:
    client = ScriptedClient([_reply("SELECT * FROM nope_a") for _ in range(5)])
    outcome = _run(db, indexed, client, max_attempts=3)

    assert not outcome.succeeded
    assert len(outcome.attempts) == 3
    assert len(client.calls) == 3


def test_every_attempt_is_recorded(db, indexed) -> None:
    # The evaluation needs the whole trail, not just the final state.
    client = ScriptedClient(
        [
            _reply("SELECT * FROM nope_a"),
            _reply("SELECT * FROM nope_b"),
            _reply("SELECT COUNT(*) FROM customers"),
        ]
    )
    outcome = _run(db, indexed, client)

    assert [a.number for a in outcome.attempts] == [1, 2, 3]
    assert outcome.attempts[0].error and outcome.attempts[1].error
    assert outcome.attempts[2].succeeded


# ---------------------------------------------------- safety never retries


def test_a_safety_rejection_stops_the_loop_immediately(db, indexed) -> None:
    """The loop's central invariant.

    Retrying a DROP would turn one blocked write into three requests for the
    same forbidden thing.
    """
    client = ScriptedClient(
        [_reply("DROP TABLE orders"), _reply("SELECT COUNT(*) FROM customers")]
    )
    outcome = _run(db, indexed, client)

    assert outcome.rejected
    assert not outcome.succeeded
    assert len(outcome.attempts) == 1
    # The second scripted reply was never requested.
    assert len(client.calls) == 1


def test_a_rejected_query_is_persisted_as_rejected(db, indexed) -> None:
    outcome = _run(db, indexed, ScriptedClient([_reply("DELETE FROM orders")]))

    record = db.get(Query, outcome.query_id)
    assert record.status is QueryStatus.REJECTED
    assert record.final_sql is None


def test_multi_statement_is_rejected_not_retried(db, indexed) -> None:
    client = ScriptedClient(
        [
            _reply("SELECT 1; DROP TABLE orders"),
            _reply("SELECT COUNT(*) FROM customers"),
        ]
    )
    outcome = _run(db, indexed, client)

    assert outcome.rejected
    assert len(client.calls) == 1


# ------------------------------------------------------------ persistence


def test_a_successful_query_stores_its_executed_sql(db, indexed) -> None:
    outcome = _run(
        db, indexed, ScriptedClient([_reply("SELECT COUNT(*) FROM customers")])
    )

    record = db.get(Query, outcome.query_id)
    assert record.status is QueryStatus.EXECUTED
    # final_sql is what actually ran, including the cost gate's LIMIT.
    assert "customers" in record.final_sql


def test_correction_count_is_persisted(db, indexed) -> None:
    outcome = _run(
        db,
        indexed,
        ScriptedClient(
            [_reply("SELECT * FROM nope"), _reply("SELECT COUNT(*) FROM customers")]
        ),
    )

    record = db.get(Query, outcome.query_id)
    assert record.correction_attempts == 1


def test_a_failed_query_stores_no_final_sql(db, indexed) -> None:
    # Only a query that ran should ever become a few-shot example.
    outcome = _run(db, indexed, ScriptedClient([_reply("SELECT * FROM nope")] * 3))

    record = db.get(Query, outcome.query_id)
    assert record.final_sql is None
    assert record.status is QueryStatus.FAILED


def test_provider_failure_ends_the_loop(db, indexed) -> None:
    outcome = _run(db, indexed, ScriptedClient([LLMError("provider down")]))

    assert not outcome.succeeded
    assert "provider down" in outcome.error


# ------------------------------------------------------------- results


def test_a_successful_outcome_carries_rows(db, indexed) -> None:
    outcome = _run(
        db, indexed, ScriptedClient([_reply("SELECT id, email FROM customers LIMIT 3")])
    )

    assert outcome.execution.columns == ["id", "email"]
    assert outcome.execution.row_count == 3


def test_the_cost_gate_limit_reaches_execution(db, indexed) -> None:
    outcome = _run(db, indexed, ScriptedClient([_reply("SELECT id FROM orders")]))

    assert outcome.succeeded
    assert outcome.validation.limit_applied
    # 2,000 rows exist; the cap keeps the result bounded.
    assert outcome.execution.row_count <= outcome.validation.limit_applied


def test_stage_timings_include_execution(db, indexed) -> None:
    outcome = _run(
        db, indexed, ScriptedClient([_reply("SELECT COUNT(*) FROM customers")])
    )
    assert "execution" in outcome.stage_timings
    assert outcome.stage_timings["total"] > 0


def test_an_ambiguous_question_never_reaches_the_model(db, indexed) -> None:
    client = ScriptedClient([_reply("SELECT 1")])
    outcome = _run(db, indexed, client, question="show me something")

    assert outcome.needs_clarification
    assert client.calls == []
