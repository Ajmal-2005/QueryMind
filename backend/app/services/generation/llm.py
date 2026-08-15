"""LLM providers for SQL generation.

One interface, three implementations: Anthropic (the proposal's primary), a
deterministic stub so the pipeline and its tests run with no API key, and a
scripted stub for driving specific responses in tests.

Structured output goes through the API's ``output_config.format`` rather than
prefilling the assistant turn with ``{``. Prefill is rejected on current
models, and a schema-constrained response is a stronger guarantee than a
prefix nudge anyway.
"""

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger
from app.services.generation.prompts import BuiltPrompt

log = get_logger(__name__)

# The proposal names Claude Sonnet 5 as the primary model.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

MAX_OUTPUT_TOKENS = 4096

# The response contract. `strict` schema validation means the SQL always
# arrives in a known shape rather than embedded in prose we would have to
# regex out.
SQL_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "A single read-only SELECT statement.",
        },
        "confidence": {
            "type": "number",
            "description": "0.0 to 1.0 — how likely this SQL answers the question.",
        },
        "explanation": {
            "type": "string",
            "description": "Plain-English description of what the query does, "
            "written for someone who does not read SQL.",
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything you had to assume because the question or "
            "schema was ambiguous. Empty when there were none.",
        },
    },
    "required": ["sql", "confidence", "explanation", "assumptions"],
    "additionalProperties": False,
}


@dataclass
class Generation:
    sql: str
    confidence: float
    explanation: str
    assumptions: list[str] = field(default_factory=list)

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMError(RuntimeError):
    """The provider failed or returned something unusable."""


@runtime_checkable
class LLMClient(Protocol):
    name: str

    def generate(self, prompt: BuiltPrompt) -> Generation: ...


def _coerce(payload: dict, model: str) -> Generation:
    """Validate a provider payload into a Generation."""
    sql = (payload.get("sql") or "").strip()
    if not sql:
        raise LLMError("Model returned no SQL")

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    assumptions = payload.get("assumptions") or []
    if not isinstance(assumptions, list):
        assumptions = [str(assumptions)]

    return Generation(
        sql=sql,
        # A model occasionally returns 0-100 rather than 0-1; clamping is
        # kinder than surfacing a confidence of 87.0 in the UI.
        confidence=min(
            max(confidence if confidence <= 1 else confidence / 100, 0.0), 1.0
        ),
        explanation=(payload.get("explanation") or "").strip(),
        assumptions=[str(a) for a in assumptions],
        model=model,
    )


class AnthropicClient:
    """The proposal's primary provider."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: BuiltPrompt) -> Generation:
        import time

        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        started = time.perf_counter()

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                # Schema-constrained output: the response is guaranteed to
                # parse, so there is no regex extraction step to get wrong.
                output_config={
                    "format": {"type": "json_schema", "schema": SQL_RESPONSE_SCHEMA},
                    # SQL generation is a reasoning task, not a lookup; `high`
                    # is the documented floor for intelligence-sensitive work.
                    "effort": "high",
                },
                thinking={"type": "adaptive"},
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API") from exc

        elapsed = (time.perf_counter() - started) * 1000

        # Safety classifiers can decline a request; the call still returns 200.
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to answer this question")

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            raise LLMError("Model returned an empty response")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Model response was not valid JSON") from exc

        generation = _coerce(payload, self.model)
        generation.input_tokens = response.usage.input_tokens
        generation.output_tokens = response.usage.output_tokens
        generation.latency_ms = elapsed
        return generation


class StubClient:
    """Deterministic offline stand-in.

    Emits syntactically valid SQL against the first retrieved table so the
    pipeline, the API, and the UI can be exercised end to end without a key.
    It does not understand the question — every result is marked with a
    confidence of 0 and a loud assumption, and evaluation runs using it must
    be reported as a stub baseline, never as an accuracy figure.
    """

    name = "stub"

    def generate(self, prompt: BuiltPrompt) -> Generation:
        table = prompt.table_names[0] if prompt.table_names else "unknown_table"
        return Generation(
            sql=f"SELECT * FROM {table} LIMIT 10",
            confidence=0.0,
            explanation=(
                f"Placeholder query returning the first ten rows of {table}. "
                "No language model is configured, so the question was not "
                "actually translated."
            ),
            assumptions=[
                "No LLM provider is configured — this is a stub response, "
                "not a real translation of the question."
            ],
            model="stub",
        )


class ScriptedClient:
    """Returns pre-set responses in order. Test double."""

    name = "scripted"

    def __init__(self, responses: list[dict | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[BuiltPrompt] = []

    def generate(self, prompt: BuiltPrompt) -> Generation:
        self.calls.append(prompt)
        if not self.responses:
            raise LLMError("ScriptedClient ran out of responses")

        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _coerce(item, "scripted")


def get_client() -> LLMClient:
    """Pick a provider from configuration."""
    if settings.ANTHROPIC_API_KEY:
        return AnthropicClient(settings.ANTHROPIC_API_KEY)

    # OpenAI is the proposal's secondary provider for A/B comparison and
    # failover. It is not wired up yet; falling back to the stub keeps that
    # visible rather than silently degrading.
    log.warning("using_stub_llm", reason="ANTHROPIC_API_KEY not set")
    return StubClient()
