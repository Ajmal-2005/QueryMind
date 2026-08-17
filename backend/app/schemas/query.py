from typing import Any

from pydantic import BaseModel, Field

from app.schemas.analytics import AnalysisRead
from app.schemas.learning import (
    ExampleRead,
    ExplanationRead,
    GlossaryMatchRead,
    SemanticHitRead,
)
from app.services.generation.intent import QuestionType


class QueryRequest(BaseModel):
    connection_id: str
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class ExecuteRequest(BaseModel):
    """Run user-edited SQL against a connection.

    Hand-written SQL goes through exactly the same gates as generated SQL -
    the validation engine does not trust the client any more than it trusts
    the model.
    """

    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)


class RetrievedTableRead(BaseModel):
    table_name: str
    score: float
    via_expansion: bool
    dense_rank: int | None = None
    sparse_rank: int | None = None


class GenerationRead(BaseModel):
    sql: str
    confidence: float
    explanation: str
    assumptions: list[str]
    model: str
    input_tokens: int
    output_tokens: int


class ValidationRead(BaseModel):
    ok: bool
    sql: str
    gate: str | None = None
    message: str | None = None
    retryable: bool | None = None
    warnings: list[str] = []
    limit_applied: int | None = None


class ResultRead(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: float
    cached: bool = False
    """Served from a recent identical run. `duration_ms` is then the cache
    lookup rather than the query."""


class AttemptRead(BaseModel):
    number: int
    sql: str
    error: str | None = None
    gate: str | None = None
    succeeded: bool


class QueryResponse(BaseModel):
    """The result of answering one question.

    Three terminal shapes: a clarification (no SQL), a rejection (SQL that a
    safety gate refused), or an answer (SQL plus rows).
    """

    query_id: str | None
    question: str
    resolved_question: str
    question_type: QuestionType

    needs_clarification: bool = False
    clarification: str | None = None
    clarification_options: list[str] = []
    """Concrete rewrites the user can pick instead of retyping (F20)."""
    rejected: bool = False

    generation: GenerationRead | None = None
    validation: ValidationRead | None = None
    result: ResultRead | None = None
    analysis: AnalysisRead | None = None
    """Profile, recommended chart, outliers and trend. Present whenever rows
    came back; the written summary is fetched separately from /query/insight."""

    explanation: ExplanationRead | None = None
    """Clause-by-clause reading of the SQL, parsed rather than narrated (F21)."""

    is_follow_up: bool = False
    semantic_hit: SemanticHitRead | None = None
    """Set when an earlier, differently-worded question answered this one and
    generation was skipped entirely (F25)."""

    examples_used: list[ExampleRead] = []
    """Which past corrections and successes shaped this answer (F22)."""

    glossary_terms: list[GlossaryMatchRead] = []
    """Business definitions applied to this question (F24)."""

    attempts: list[AttemptRead] = []
    correction_attempts: int = 0
    recovered_by_correction: bool = False

    retrieved_tables: list[RetrievedTableRead] = []
    embedder: str | None = None

    error: str | None = None
    timings_ms: dict[str, float] = {}
