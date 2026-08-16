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

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.services.generation.prompts import BuiltPrompt

log = get_logger(__name__)

# The proposal names Claude Sonnet 5 as the primary model.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

# The proposal's secondary provider. gpt-4.1 is the strongest model this
# project's key has access to; override with OPENAI_MODEL.
DEFAULT_OPENAI_MODEL = "gpt-4.1"

# Gemini's free tier needs no billing, which makes it the practical default
# for a project without a funded account. `gemini-3.5-flash` does not exist —
# the default was wrong and would have failed on the first call.
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

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


class GeminiSQLResponse(BaseModel):
    sql: str = Field(description="A single read-only SELECT statement.")
    confidence: float = Field(
        description="0.0 to 1.0 — how likely this SQL answers the question."
    )
    explanation: str = Field(
        description="Plain-English description of what the query does, "
        "written for someone who does not read SQL."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Anything you had to assume because the question or "
        "schema was ambiguous. Empty when there were none.",
    )


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


class GeminiClient:
    """Google Gemini provider."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: BuiltPrompt) -> Generation:
        import time

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        started = time.perf_counter()

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt.user,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.system,
                    response_mime_type="application/json",
                    response_schema=GeminiSQLResponse,
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            raise LLMError(f"Gemini API error: {exc}") from exc

        elapsed = (time.perf_counter() - started) * 1000

        text = response.text
        if not text:
            raise LLMError("Model returned an empty response")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {exc}") from exc

        generation = _coerce(payload, self.model)
        generation.input_tokens = getattr(
            getattr(response, "usage_metadata", None), "prompt_token_count", 0
        )
        generation.output_tokens = getattr(
            getattr(response, "usage_metadata", None), "candidates_token_count", 0
        )
        generation.latency_ms = elapsed
        return generation


class OpenAIClient:
    """The proposal's secondary provider, for A/B comparison and failover.

    Structured output works the same way as the Anthropic path — a JSON schema
    the response is guaranteed to satisfy — but through `response_format`
    rather than `output_config`. `strict` mode requires every property to be
    required and `additionalProperties` false, which `SQL_RESPONSE_SCHEMA`
    already is.

    Unlike Anthropic, this provider *does* accept `temperature`. It is set to
    0 here, which is worth noting precisely because the proposal claimed that
    for the primary provider and was wrong: determinism is available on this
    path and not on that one.
    """

    name = "openai"

    def __init__(self, api_key: str, model: str = DEFAULT_OPENAI_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: BuiltPrompt) -> Generation:
        import time

        import openai

        # No SDK-level retries: the failure this actually sees is an
        # out-of-quota 429, which no amount of retrying resolves. Retrying it
        # only delays the failover that does work.
        client = openai.OpenAI(api_key=self.api_key, timeout=30.0, max_retries=0)
        started = time.perf_counter()

        try:
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "sql_generation",
                        "strict": True,
                        "schema": SQL_RESPONSE_SCHEMA,
                    },
                },
            )
        except openai.APIStatusError as exc:
            raise LLMError(
                f"OpenAI API error {exc.status_code}: {exc.message}"
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the OpenAI API") from exc

        elapsed = (time.perf_counter() - started) * 1000
        choice = response.choices[0]

        # `length` means the JSON was cut mid-object; parsing it would raise a
        # confusing decode error rather than the truthful reason.
        if choice.finish_reason == "length":
            raise LLMError("Model response was truncated before it completed")
        if getattr(choice.message, "refusal", None):
            raise LLMError("The model declined to answer this question")

        text = choice.message.content or ""
        if not text:
            raise LLMError("Model returned an empty response")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Model response was not valid JSON") from exc

        generation = _coerce(payload, self.model)
        if response.usage:
            generation.input_tokens = response.usage.prompt_tokens
            generation.output_tokens = response.usage.completion_tokens
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


class FailoverClient:
    """Try each configured provider in turn, then the stub.

    The proposal budgets for provider failover, and the reason became concrete
    during Phase 7: a key can be perfectly valid and still return 429 because
    the account has no quota. That is indistinguishable from an outage at the
    call site and equally fatal to a demo.

    So a provider failure moves to the next provider rather than to an error
    banner. `name` reports which one actually answered, and the stub still
    marks itself, so falling all the way through is visible rather than
    silent.
    """

    def __init__(self, clients: list[LLMClient]) -> None:
        if not clients:
            raise ValueError("FailoverClient needs at least one provider")
        self.clients = clients
        self.name = clients[0].name
        self.model = getattr(clients[0], "model", clients[0].name)

    def generate(self, prompt: BuiltPrompt) -> Generation:
        errors: list[str] = []

        for client in self.clients:
            try:
                generation = client.generate(prompt)
            except LLMError as exc:
                errors.append(f"{client.name}: {exc}")
                log.warning(
                    "llm_provider_failed", provider=client.name, error=str(exc)[:160]
                )
                continue

            # Report the provider that actually produced this answer, not the
            # one that was configured first.
            self.name = client.name
            self.model = getattr(client, "model", client.name)
            if errors:
                log.info(
                    "llm_failover_succeeded", provider=client.name, tried=len(errors)
                )
                # The stub's own wording says no provider is configured, which
                # is wrong here — one was, and it failed. Say what happened.
                if client.name == "stub":
                    generation.assumptions = [
                        "The configured language model could not be reached "
                        f"({errors[0]}), so this is a placeholder query, not a "
                        "real translation of the question."
                    ]
            return generation

        raise LLMError("Every provider failed — " + "; ".join(errors))


def get_client() -> LLMClient:
    """Pick a provider from configuration.

    Anthropic leads because the proposal names it as primary; OpenAI and
    Gemini follow as the secondary providers the proposal budgets for A/B
    comparison and failover. Whichever answers, its name travels on every
    `Generation`, so no result can be misattributed.

    The stub is the last resort and logs at warning level: it does not read
    the question, so anything measured against it is a baseline, not accuracy.
    """
    chain: list[LLMClient] = []

    if settings.ANTHROPIC_API_KEY:
        chain.append(AnthropicClient(settings.ANTHROPIC_API_KEY))
    if settings.OPENAI_API_KEY:
        chain.append(OpenAIClient(settings.OPENAI_API_KEY, settings.OPENAI_MODEL))
    if settings.GEMINI_API_KEY:
        chain.append(GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL))

    if not chain:
        log.warning("using_stub_llm", reason="no LLM provider key configured")
        return StubClient()

    # The stub anchors the chain so a provider outage degrades the answer
    # rather than removing it. It is loud about being a stub.
    chain.append(StubClient())
    log.info("llm_provider_chain", providers=[c.name for c in chain])
    return FailoverClient(chain)
