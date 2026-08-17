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


# --------------------------------------------------- provider failover


def test_failover_moves_to_the_next_provider_on_failure() -> None:
    """A valid key with no quota returns 429 - indistinguishable from an
    outage at the call site, and equally fatal to a demo."""
    from app.services.generation.llm import FailoverClient, LLMError

    broken = ScriptedClient([LLMError("429 insufficient_quota")])
    working = ScriptedClient([{"sql": "SELECT 1", "confidence": 0.9}])

    generation = FailoverClient([broken, working]).generate(PROMPT)
    assert generation.sql == "SELECT 1"


def test_failover_reports_the_provider_that_actually_answered() -> None:
    from app.services.generation.llm import FailoverClient, LLMError, StubClient

    client = FailoverClient([ScriptedClient([LLMError("down")]), StubClient()])
    client.generate(PROMPT)
    assert client.name == "stub"


def test_falling_through_to_the_stub_says_why() -> None:
    """The stub's own wording blames a missing key. Here one was configured
    and failed, and the assumption must say so."""
    from app.services.generation.llm import FailoverClient, LLMError, StubClient

    generation = FailoverClient(
        [ScriptedClient([LLMError("429 insufficient_quota")]), StubClient()]
    ).generate(PROMPT)

    assumption = " ".join(generation.assumptions)
    assert "No language model could be reached" in assumption
    assert "not a real translation" in assumption
    # Every provider's failure is quoted, not just the first - with a chain,
    # the first error is rarely the interesting one.
    assert "insufficient_quota" in assumption


def test_every_provider_failing_raises() -> None:
    from app.services.generation.llm import FailoverClient, LLMError

    client = FailoverClient(
        [ScriptedClient([LLMError("a")]), ScriptedClient([LLMError("b")])]
    )
    with pytest.raises(LLMError, match="Every provider failed"):
        client.generate(PROMPT)


def test_a_healthy_first_provider_is_not_bypassed() -> None:
    from app.services.generation.llm import FailoverClient

    second = ScriptedClient([{"sql": "SELECT 2", "confidence": 1}])
    client = FailoverClient(
        [ScriptedClient([{"sql": "SELECT 1", "confidence": 1}]), second]
    )

    assert client.generate(PROMPT).sql == "SELECT 1"
    assert second.calls == []  # never consulted


def test_all_provider_failures_are_reported_not_just_the_first() -> None:
    from app.services.generation.llm import FailoverClient, LLMError, StubClient

    generation = FailoverClient(
        [
            ScriptedClient([LLMError("openai: insufficient_quota")]),
            ScriptedClient([LLMError("gemini: 503 unavailable")]),
            StubClient(),
        ]
    ).generate(PROMPT)

    assumption = " ".join(generation.assumptions)
    assert "insufficient_quota" in assumption
    assert "503 unavailable" in assumption


def test_transient_errors_are_distinguished_from_permanent_ones() -> None:
    """A 503 recovers on retry; an exhausted quota never does."""
    from app.services.generation.llm import _is_transient

    assert _is_transient(Exception("503 Service Unavailable"))
    assert _is_transient(Exception("deadline exceeded"))
    assert not _is_transient(Exception("insufficient_quota"))
    assert not _is_transient(Exception("API key not valid"))
