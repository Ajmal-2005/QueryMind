"""Narrative insight generation (F13).

The model is given the *profile* — counts, ranges, quartiles, the trend, the
flagged outliers — and only a small masked sample of rows. Two reasons, in
order of importance:

1. The statistics are computed here, exactly, from the whole result. A model
   handed 10,000 raw rows would have to add them up itself, and would
   sometimes get it wrong while sounding equally confident. Everything
   numeric in the summary traces to arithmetic this process did.
2. Twenty masked rows cost a fraction of the tokens the full set would, and
   nothing personal leaves the deployment.

Three narrators mirror the SQL layer's three clients, with one difference
that matters: the offline fallback here is not a stub. Statistical narration
is a template problem, so `TemplateNarrator` writes a real, accurate summary
from the profile with no API key at all — it is labelled `template` so no
report can mistake it for model output, but the product's promise that every
query comes back with a written summary holds offline.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger
from app.services.analytics.analyze import Analysis
from app.services.analytics.masking import (
    MaskingReport,
    classify_column,
    mask_rows,
    mask_value,
)
from app.services.analytics.profile import ColumnKind

log = get_logger(__name__)

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
MAX_OUTPUT_TOKENS = 1024

# Enough rows for the model to see the shape of a record; far short of enough
# to re-derive a statistic the profile already states exactly.
SAMPLE_ROWS = 20

NARRATIVE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One short sentence — the single most important "
            "thing this result shows. No preamble.",
        },
        "summary": {
            "type": "string",
            "description": "Two to three sentences describing what the numbers "
            "show, written for a business reader who did not write the query.",
        },
        "findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Zero to four specific observations, each one line. "
            "Only include a finding the data actually supports.",
        },
    },
    "required": ["headline", "summary", "findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write short, factual summaries of query results for \
business readers.

You are given exact statistics computed from the complete result set, plus a \
small sample of rows for context. The sample has had personal data replaced \
with tokens like <email> — never comment on those tokens or speculate about \
what they contained.

Rules:

1. Every number you state must come from the statistics given to you. Do not \
compute new figures from the sample rows — the sample is partial and any \
total you derive from it will be wrong.
2. Describe what the data shows. Do not recommend actions, do not speculate \
about causes, and do not invent business context you were not given.
3. If a trend or outliers are reported, say so plainly and quantitatively. If \
they are not, do not imply movement the data does not show.
4. No preamble. Do not open with "This query returns" or "The data shows" — \
start with the finding itself.
5. Say when the result is limited: an empty result, a single row, or a \
truncated one is worth stating rather than dressing up."""


@dataclass
class Narrative:
    headline: str
    summary: str
    findings: list[str] = field(default_factory=list)

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    masking: MaskingReport = field(default_factory=MaskingReport)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class NarrativeError(RuntimeError):
    """The narrator failed or returned something unusable."""


@runtime_checkable
class Narrator(Protocol):
    name: str

    def narrate(self, question: str, sql: str, analysis: Analysis) -> Narrative: ...


# ----------------------------------------------------------------- prompt


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.2f}"


def describe_profile(analysis: Analysis) -> str:
    """Render the computed statistics as the model's factual ground truth.

    The profile carries *values* as well as counts — the most common entries
    in a categorical column, the range of a temporal one — and those are row
    data every bit as much as the sample is. They go through the same masking
    on the way out; masking only the sample rows would have leaked exactly the
    columns the masking exists to protect.
    """
    profile = analysis.profile
    lines = [
        f"Rows: {profile.row_count:,}"
        + (" (capped — more rows exist)" if profile.truncated else ""),
        f"Columns: {profile.column_count}",
        "",
        "Column statistics:",
    ]

    for column in profile.columns:
        parts = [f"- {column.name} ({column.kind.value})"]
        if column.null_count:
            parts.append(f"{column.null_count} null of {profile.row_count}")

        sensitive = classify_column(column.name)

        if column.kind is ColumnKind.NUMERIC:
            # Aggregates over a numeric column are the point of the product
            # and are not identifying on their own.
            parts.append(
                f"min {_format_number(column.minimum)}, "
                f"max {_format_number(column.maximum)}, "
                f"mean {_format_number(column.mean)}, "
                f"median {_format_number(column.median)}, "
                f"sd {_format_number(column.stddev)}"
            )
        elif sensitive:
            # A date range is harmless until the column is a date of birth.
            parts.append(
                f"{column.distinct_count} distinct; values withheld ({sensitive})"
            )
        elif column.kind is ColumnKind.TEMPORAL:
            parts.append(f"{column.earliest} to {column.latest}")
        elif column.top_values:
            top = ", ".join(
                f"{mask_value(t.value)[0]} ({t.count})" for t in column.top_values[:5]
            )
            parts.append(f"{column.distinct_count} distinct; most common: {top}")

        lines.append("; ".join(parts))

    trend = analysis.trend.trend
    if trend:
        lines += [
            "",
            "Trend:",
            f"- {trend.summary}",
            f"- Highest at {trend.best_period}, lowest at {trend.worst_period}.",
        ]
        if trend.average_growth_rate is not None:
            lines.append(
                f"- Average period-over-period change: "
                f"{trend.average_growth_rate:+.1%}."
            )

    report = analysis.outliers
    if report.any_found:
        lines += ["", f"Outliers: {report.total} value(s) flagged."]
        for outlier in report.outliers[:5]:
            agreement = (
                "both methods agree"
                if len(outlier.methods) == 2
                else f"{outlier.methods[0]} only"
            )
            lines.append(
                f"- {outlier.column} = {_format_number(outlier.value)} "
                f"in row {outlier.row_index + 1} ({agreement})"
            )

    return "\n".join(lines)


def build_prompt(
    question: str, sql: str, analysis: Analysis, rows: list[list]
) -> tuple[str, MaskingReport]:
    """Assemble the user turn, masking the sample on the way out."""
    columns = [c.name for c in analysis.profile.columns]
    sample, masking = mask_rows(columns, rows[:SAMPLE_ROWS])

    sections = [
        f"Question asked:\n{question}",
        f"SQL that ran:\n{sql}",
        "Computed statistics (exact, over the whole result):\n"
        + describe_profile(analysis),
    ]

    if sample:
        rendered = [" | ".join(columns)]
        rendered += [
            " | ".join("" if v is None else str(v) for v in row) for row in sample
        ]
        note = (
            f"Sample of {len(sample)} row(s)"
            + (
                f" — personal data in {', '.join(masking.column_names)} "
                "has been replaced with tokens"
                if masking.any_masked
                else ""
            )
            + ":"
        )
        sections.append(note + "\n" + "\n".join(rendered))

    return "\n\n".join(sections), masking


# ---------------------------------------------------------------- narrators


class AnthropicNarrator:
    """The proposal's primary provider."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        self.api_key = api_key
        self.model = model
        self.rows: list[list] = []

    def narrate(self, question: str, sql: str, analysis: Analysis) -> Narrative:
        import anthropic

        user, masking = build_prompt(question, sql, analysis, self.rows)
        client = anthropic.Anthropic(api_key=self.api_key)
        started = time.perf_counter()

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "format": {"type": "json_schema", "schema": NARRATIVE_SCHEMA},
                    # Summarising supplied statistics is a describing task, not
                    # a reasoning one — unlike SQL generation, which asks for
                    # `high`. Low effort keeps this call cheap and quick.
                    "effort": "low",
                },
            )
        except anthropic.APIStatusError as exc:
            raise NarrativeError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise NarrativeError("Could not reach the Anthropic API") from exc

        if response.stop_reason == "refusal":
            raise NarrativeError("The model declined to summarise this result")

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            raise NarrativeError("Model returned an empty response")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NarrativeError("Model response was not valid JSON") from exc

        findings = payload.get("findings") or []
        return Narrative(
            headline=(payload.get("headline") or "").strip(),
            summary=(payload.get("summary") or "").strip(),
            findings=[str(f) for f in findings],
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
            masking=masking,
        )


class TemplateNarrator:
    """Deterministic summary computed from the profile.

    Not a stub in the sense the SQL layer's is — that one cannot answer the
    question and says so. This one produces a genuinely correct summary; it
    is only less fluent than a model's, and never draws a conclusion the
    arithmetic does not already contain.
    """

    name = "template"

    def narrate(self, question: str, sql: str, analysis: Analysis) -> Narrative:
        started = time.perf_counter()
        profile = analysis.profile
        numeric = profile.by_kind(ColumnKind.NUMERIC)
        findings: list[str] = []

        if profile.row_count == 0:
            return Narrative(
                headline="The query ran and matched nothing.",
                summary=(
                    "No rows satisfied the conditions in this query. That is a "
                    "valid answer — it may mean the filters are narrower than "
                    "intended, or that there genuinely is no matching data."
                ),
                model=self.name,
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        if profile.is_scalar and numeric:
            column = numeric[0]
            headline = f"{column.name} is {_format_number(column.maximum)}."
        elif (trend := analysis.trend.trend) is not None:
            headline = trend.summary
        else:
            headline = (
                f"{profile.row_count:,} row"
                f"{'' if profile.row_count == 1 else 's'} across "
                f"{profile.column_count} column"
                f"{'' if profile.column_count == 1 else 's'}."
            )

        for column in numeric[:3]:
            findings.append(
                f"{column.name} ranges from {_format_number(column.minimum)} to "
                f"{_format_number(column.maximum)}, averaging "
                f"{_format_number(column.mean)} (median "
                f"{_format_number(column.median)})."
            )

        for column in profile.by_kind(ColumnKind.CATEGORICAL)[:2]:
            if column.top_values:
                top = column.top_values[0]
                findings.append(
                    f"{column.name} has {column.distinct_count} distinct values; "
                    f"the most common is {top.value} at {top.fraction:.0%} of rows."
                )

        sparse = [c for c in profile.columns if c.null_fraction >= 0.2]
        if sparse:
            findings.append(
                "Sparse column"
                + ("s: " if len(sparse) > 1 else ": ")
                + ", ".join(f"{c.name} ({c.null_fraction:.0%} null)" for c in sparse)
                + "."
            )

        if analysis.outliers.any_found:
            agreed = sum(1 for o in analysis.outliers.outliers if len(o.methods) == 2)
            findings.append(
                f"{analysis.outliers.total} outlying value"
                f"{'' if analysis.outliers.total == 1 else 's'} flagged"
                + (f", {agreed} by both the IQR and z-score tests." if agreed else ".")
            )

        if profile.truncated:
            findings.append(
                f"The result was capped at {profile.row_count:,} rows — more exist, "
                "so these figures describe the capped set only."
            )

        summary_parts = [headline]
        if trend := analysis.trend.trend:
            if trend.average_growth_rate is not None:
                summary_parts.append(
                    f"The typical move between periods is "
                    f"{trend.average_growth_rate:+.1%}, peaking at "
                    f"{trend.best_period}."
                )
        elif analysis.trend.reason:
            summary_parts.append(f"No trend was computed: {analysis.trend.reason}.")

        summary_parts.append(
            "Written from the computed statistics without a language model, so "
            "it reports the numbers rather than interpreting them."
        )

        return Narrative(
            headline=headline,
            summary=" ".join(summary_parts),
            findings=findings,
            model=self.name,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


class ScriptedNarrator:
    """Returns pre-set responses in order. Test double."""

    name = "scripted"

    def __init__(self, responses: list[dict | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.rows: list[list] = []

    def narrate(self, question: str, sql: str, analysis: Analysis) -> Narrative:
        user, masking = build_prompt(question, sql, analysis, self.rows)
        self.prompts.append(user)

        if not self.responses:
            raise NarrativeError("ScriptedNarrator ran out of responses")

        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item

        return Narrative(
            headline=item.get("headline", ""),
            summary=item.get("summary", ""),
            findings=list(item.get("findings", [])),
            model=self.name,
            masking=masking,
        )


def get_narrator() -> Narrator:
    """Pick a narrator from configuration."""
    if settings.ANTHROPIC_API_KEY:
        return AnthropicNarrator(settings.ANTHROPIC_API_KEY)

    log.warning("using_template_narrator", reason="ANTHROPIC_API_KEY not set")
    return TemplateNarrator()


def narrate(
    question: str,
    sql: str,
    analysis: Analysis,
    rows: list[list],
    narrator: Narrator | None = None,
) -> Narrative:
    """Summarise a result set, falling back rather than failing.

    A narrative is a garnish on an answer the user already has. If the
    provider is down, a template summary is far better than an error banner
    over a table that is sitting there working perfectly.
    """
    narrator = narrator or get_narrator()
    # The rows travel on the narrator rather than through `narrate` so the
    # Protocol stays a three-argument call for any future provider.
    if hasattr(narrator, "rows"):
        narrator.rows = rows

    try:
        return narrator.narrate(question, sql, analysis)
    except NarrativeError as exc:
        log.warning("narrative_failed", narrator=narrator.name, error=str(exc)[:200])
        fallback = TemplateNarrator().narrate(question, sql, analysis)
        fallback.summary = (
            f"{fallback.summary} (The language model was unavailable: {exc})"
        )
        return fallback


__all__ = [
    "AnthropicNarrator",
    "Narrative",
    "NarrativeError",
    "Narrator",
    "ScriptedNarrator",
    "TemplateNarrator",
    "build_prompt",
    "describe_profile",
    "get_narrator",
    "narrate",
]
