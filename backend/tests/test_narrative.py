"""Narrative insight generation (F13).

No live model has ever been called. What is tested here is everything around
the call: that the prompt carries exact statistics rather than asking the
model to add up rows, that masking runs on the way out, that the offline
narrator produces a correct summary, and that a provider failure degrades to
that narrator instead of losing the answer.
"""

import pytest

from app.services.analytics.analyze import analyze
from app.services.analytics.narrative import (
    SAMPLE_ROWS,
    NarrativeError,
    ScriptedNarrator,
    TemplateNarrator,
    build_prompt,
    describe_profile,
    narrate,
)

COLUMNS = ["month", "revenue"]
ROWS = [["2024-01", 100], ["2024-02", 140], ["2024-03", 180], ["2024-04", 220]]


def _analysis(columns=COLUMNS, rows=ROWS):
    return analyze(columns, rows)


# ------------------------------------------------------------------ prompt


def test_prompt_states_computed_statistics_not_just_rows() -> None:
    """The model must not be left to derive totals from a partial sample."""
    described = describe_profile(_analysis())

    assert "Rows: 4" in described
    assert "revenue (numeric)" in described
    assert "min 100" in described
    assert "max 220" in described
    assert "mean 160" in described


def test_prompt_includes_the_trend_when_there_is_one() -> None:
    described = describe_profile(_analysis())
    assert "Trend:" in described
    assert "rising" in described
    assert "Highest at 2024-04" in described


def test_prompt_reports_outliers_with_which_methods_agreed() -> None:
    values = [10, 11, 12, 10, 11, 13, 12, 11, 10, 12, 9000]
    rows = [[f"2024-{n:02d}", v] for n, v in enumerate(values, start=1)]
    described = describe_profile(_analysis(COLUMNS, rows))

    assert "Outliers: 1" in described
    assert "both methods agree" in described


def test_profile_values_are_masked_as_well_as_the_sample() -> None:
    """The profile carries row data too — the most common values.

    Masking the sample alone would have leaked precisely the columns the
    masking exists to protect.
    """
    columns = ["full_name", "revenue"]
    rows = [["Ada Lovelace", 100], ["Grace Hopper", 200]]
    described = describe_profile(analyze(columns, rows))

    assert "Ada Lovelace" not in described
    assert "Grace Hopper" not in described
    assert "values withheld (name)" in described
    # The measure is untouched — there would be nothing to summarise otherwise.
    assert "min 100" in described


def test_pii_in_an_unflagged_column_is_masked_in_the_profile_too() -> None:
    columns = ["reference", "revenue"]
    rows = [["ada@example.com", 100], ["bob@example.com", 200]]
    described = describe_profile(analyze(columns, rows))

    assert "ada@example.com" not in described
    assert "<email>" in described


def test_sample_is_capped() -> None:
    rows = [[f"2024-{n % 12 + 1:02d}-01", n] for n in range(200)]
    user, _ = build_prompt("q", "SELECT 1", _analysis(COLUMNS, rows), rows)
    assert f"Sample of {SAMPLE_ROWS} row(s)" in user


def test_sample_is_masked_before_it_reaches_the_prompt() -> None:
    columns = ["full_name", "email", "revenue"]
    rows = [["Ada Lovelace", "ada@example.com", 100]]
    user, masking = build_prompt("q", "SELECT 1", analyze(columns, rows), rows)

    assert "Ada Lovelace" not in user
    assert "ada@example.com" not in user
    assert "<name>" in user
    assert masking.any_masked
    # The prompt tells the model the tokens are placeholders, so it does not
    # try to describe them.
    assert "replaced with tokens" in user


def test_measures_survive_masking_into_the_prompt() -> None:
    columns = ["full_name", "revenue"]
    rows = [["Ada Lovelace", 12345]]
    user, _ = build_prompt("q", "SELECT 1", analyze(columns, rows), rows)
    assert "12345" in user


# ---------------------------------------------------------------- narrators


def test_template_narrator_states_real_figures() -> None:
    narrative = TemplateNarrator().narrate("How is revenue?", "SELECT 1", _analysis())

    assert narrative.model == "template"
    assert "rising" in narrative.headline
    assert any("100" in f and "220" in f for f in narrative.findings)


def test_template_narrator_labels_itself_as_not_a_model() -> None:
    """No report should be able to mistake this for model output."""
    narrative = TemplateNarrator().narrate("q", "SELECT 1", _analysis())
    assert narrative.model == "template"
    assert "without a language model" in narrative.summary


def test_template_narrator_handles_an_empty_result() -> None:
    narrative = TemplateNarrator().narrate("q", "SELECT 1", analyze(COLUMNS, []))
    assert "matched nothing" in narrative.headline


def test_template_narrator_reports_truncation() -> None:
    rows = [[f"2024-{n:02d}", n] for n in range(1, 13)]
    analysis = analyze(COLUMNS, rows, truncated=True)
    narrative = TemplateNarrator().narrate("q", "SELECT 1", analysis)
    assert any("capped" in f for f in narrative.findings)


def test_template_narrator_flags_sparse_columns() -> None:
    rows = [["2024-01", None], ["2024-02", None], ["2024-03", 5], ["2024-04", 6]]
    narrative = TemplateNarrator().narrate("q", "SELECT 1", analyze(COLUMNS, rows))
    assert any("null" in f for f in narrative.findings)


def test_scripted_narrator_returns_its_script() -> None:
    narrator = ScriptedNarrator(
        [{"headline": "Revenue doubled.", "summary": "It went up.", "findings": ["a"]}]
    )
    narrative = narrate("q", "SELECT 1", _analysis(), ROWS, narrator=narrator)

    assert narrative.headline == "Revenue doubled."
    assert narrative.findings == ["a"]
    assert len(narrator.prompts) == 1


def test_provider_failure_falls_back_rather_than_losing_the_answer() -> None:
    """A narrative is a garnish on a result the user already has."""
    narrator = ScriptedNarrator([NarrativeError("provider exploded")])
    narrative = narrate("q", "SELECT 1", _analysis(), ROWS, narrator=narrator)

    assert narrative.model == "template"
    assert "provider exploded" in narrative.summary
    assert narrative.headline


def test_masking_report_travels_with_the_narrative() -> None:
    """The audit log needs evidence that masking ran, not that it was configured."""
    columns = ["email", "revenue"]
    rows = [["ada@example.com", 100]]
    narrator = ScriptedNarrator([{"headline": "h", "summary": "s", "findings": []}])
    narrative = narrate(
        "q", "SELECT 1", analyze(columns, rows), rows, narrator=narrator
    )

    assert narrative.masking.column_names == ["email"]
    assert narrative.masking.values_masked == 1


@pytest.mark.parametrize(
    "columns,rows",
    [
        (["a"], []),
        (["a"], [[None]]),
        (["a", "b"], [[1, "x"]]),
        (["month", "revenue"], ROWS),
    ],
)
def test_template_narrator_never_raises(columns, rows) -> None:
    narrative = TemplateNarrator().narrate("q", "SELECT 1", analyze(columns, rows))
    assert narrative.headline
    assert narrative.summary
