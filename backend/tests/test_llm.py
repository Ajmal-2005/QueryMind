"""The LLM provider layer."""

import pytest

from app.services.generation.llm import (
    LLMError,
    ScriptedClient,
    StubClient,
    _coerce,
    get_client,
)
from app.services.generation.prompts import BuiltPrompt

PROMPT = BuiltPrompt(system="s", user="u", table_names=["orders"])


def test_coerce_reads_a_well_formed_payload() -> None:
    generation = _coerce(
        {
            "sql": "SELECT 1",
            "confidence": 0.9,
            "explanation": "Returns one.",
            "assumptions": ["none"],
        },
        "test-model",
    )
    assert generation.sql == "SELECT 1"
    assert generation.confidence == 0.9
    assert generation.assumptions == ["none"]


def test_coerce_rejects_an_empty_sql_field() -> None:
    with pytest.raises(LLMError, match="no SQL"):
        _coerce({"sql": "   ", "confidence": 1.0}, "m")


def test_coerce_rescales_percentage_confidence() -> None:
    # Models occasionally answer 0-100 despite the schema saying 0-1.
    assert _coerce({"sql": "SELECT 1", "confidence": 87}, "m").confidence == 0.87


def test_coerce_clamps_confidence_to_the_unit_range() -> None:
    assert _coerce({"sql": "SELECT 1", "confidence": -5}, "m").confidence == 0.0


def test_coerce_survives_a_non_numeric_confidence() -> None:
    assert _coerce({"sql": "SELECT 1", "confidence": "high"}, "m").confidence == 0.0


def test_coerce_wraps_a_scalar_assumption_in_a_list() -> None:
    generation = _coerce(
        {"sql": "SELECT 1", "confidence": 1, "assumptions": "just one"}, "m"
    )
    assert generation.assumptions == ["just one"]


def test_coerce_defaults_missing_assumptions_to_empty() -> None:
    assert _coerce({"sql": "SELECT 1", "confidence": 1}, "m").assumptions == []


def test_stub_returns_runnable_sql_for_the_retrieved_table() -> None:
    generation = StubClient().generate(PROMPT)
    assert generation.sql == "SELECT * FROM orders LIMIT 10"


def test_stub_is_explicit_that_it_is_not_a_real_translation() -> None:
    # A stub result must never be mistaken for a measured one.
    generation = StubClient().generate(PROMPT)
    assert generation.confidence == 0.0
    assert any("stub" in a.lower() for a in generation.assumptions)


def test_scripted_client_returns_responses_in_order() -> None:
    client = ScriptedClient(
        [
            {"sql": "SELECT 1", "confidence": 0.5},
            {"sql": "SELECT 2", "confidence": 0.9},
        ]
    )
    assert client.generate(PROMPT).sql == "SELECT 1"
    assert client.generate(PROMPT).sql == "SELECT 2"


def test_scripted_client_can_raise() -> None:
    client = ScriptedClient([LLMError("provider exploded")])
    with pytest.raises(LLMError, match="exploded"):
        client.generate(PROMPT)


def test_scripted_client_records_the_prompts_it_saw() -> None:
    client = ScriptedClient([{"sql": "SELECT 1", "confidence": 1}])
    client.generate(PROMPT)
    assert client.calls == [PROMPT]


def test_get_client_falls_back_to_the_stub_without_a_key() -> None:
    # No ANTHROPIC_API_KEY is configured in the test environment.
    assert get_client().name == "stub"
