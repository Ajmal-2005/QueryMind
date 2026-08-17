"""API contracts for conversation and learning (F21-F25)."""

from datetime import datetime

from pydantic import BaseModel, Field


class StepRead(BaseModel):
    order: int
    clause: str
    title: str
    detail: str
    sql: str = ""


class ExplanationRead(BaseModel):
    """A reading of the SQL derived from the parsed statement (F21).

    Independent of the model's own `explanation`: where the two disagree,
    something is wrong and the reader can see it.
    """

    parsed: bool
    summary: str
    steps: list[StepRead] = []
    tables: list[str] = []
    aggregates: list[str] = []
    row_limit: int | None = None
    is_aggregate: bool = False


class ExampleRead(BaseModel):
    question: str
    sql: str
    score: float
    source: str
    """'correction' or 'history' - provenance stays visible."""


class GlossaryMatchRead(BaseModel):
    term: str
    definition: str
    sql_expression: str | None = None


class SemanticHitRead(BaseModel):
    question: str
    similarity: float
    embedder: str


class SuggestionRead(BaseModel):
    question: str
    reason: str


class CorrectionCreate(BaseModel):
    """Save SQL a user fixed by hand (F22)."""

    connection_id: str
    question: str = Field(min_length=1, max_length=2000)
    corrected_sql: str = Field(min_length=1, max_length=20000)
    original_sql: str | None = Field(default=None, max_length=20000)
    query_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class CorrectionRead(BaseModel):
    id: str
    question: str
    original_sql: str | None
    corrected_sql: str
    note: str | None
    verified: bool
    created_at: datetime


class GlossaryTermCreate(BaseModel):
    connection_id: str
    term: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=4000)
    sql_expression: str | None = Field(default=None, max_length=4000)


class GlossaryTermRead(BaseModel):
    id: str
    term: str
    definition: str
    sql_expression: str | None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "CorrectionCreate",
    "CorrectionRead",
    "ExampleRead",
    "ExplanationRead",
    "GlossaryMatchRead",
    "GlossaryTermCreate",
    "GlossaryTermRead",
    "SemanticHitRead",
    "StepRead",
    "SuggestionRead",
]
