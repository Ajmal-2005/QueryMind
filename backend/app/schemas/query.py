from pydantic import BaseModel, Field

from app.services.generation.intent import QuestionType


class QueryRequest(BaseModel):
    connection_id: str
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


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


class QueryResponse(BaseModel):
    """The result of translating one question.

    A clarification response carries no SQL: `needs_clarification` is true and
    `clarification` holds the question to put back to the user.
    """

    query_id: str | None
    question: str
    resolved_question: str
    question_type: QuestionType

    needs_clarification: bool = False
    clarification: str | None = None

    generation: GenerationRead | None = None
    retrieved_tables: list[RetrievedTableRead] = []
    embedder: str | None = None

    error: str | None = None
    timings_ms: dict[str, float] = {}
