"""Intent classification, coreference resolution, and ambiguity detection."""

from app.services.generation.intent import QuestionType, analyze


def test_counting_question_is_aggregation() -> None:
    assert analyze("How many customers do we have?").question_type is (
        QuestionType.AGGREGATION
    )


def test_top_n_question_is_ranking() -> None:
    assert analyze("List the top 5 products by revenue").question_type is (
        QuestionType.RANKING
    )


def test_ranking_beats_trend_when_both_match() -> None:
    # "top 5 ... by month" is a ranking question that happens to mention a
    # period; ordering the patterns wrong would classify it as a trend.
    intent = analyze("Top 5 products by revenue each month")
    assert intent.question_type is QuestionType.RANKING


def test_comparison_question_is_detected() -> None:
    intent = analyze("How did revenue grow compared to last quarter?")
    assert intent.question_type is QuestionType.COMPARISON


def test_trend_question_is_detected() -> None:
    assert analyze("Show orders by month over time").question_type is QuestionType.TREND


def test_plain_lookup_is_a_filter() -> None:
    assert analyze("Which customers are in the North region?").question_type is (
        QuestionType.FILTER
    )


def test_explicit_limit_is_extracted() -> None:
    assert analyze("Show the top 7 categories").limit_hint == 7


def test_no_limit_when_none_is_stated() -> None:
    assert analyze("Show revenue by category").limit_hint is None


def test_relative_dates_are_spelled_out() -> None:
    # Left implicit, models pick inconsistent boundaries for "last quarter".
    intent = analyze("What was revenue last quarter?")
    assert any("previous complete calendar quarter" in w for w in intent.time_windows)


def test_multiple_time_windows_are_captured() -> None:
    intent = analyze("Compare this month to last month")
    assert len(intent.time_windows) == 2


def test_vague_question_asks_for_clarification() -> None:
    intent = analyze("show me something")
    assert intent.question_type is QuestionType.AMBIGUOUS
    assert intent.needs_clarification
    assert intent.clarification


def test_very_short_question_asks_for_clarification() -> None:
    assert analyze("data?").needs_clarification


def test_specific_question_does_not_ask_for_clarification() -> None:
    assert not analyze("How many orders were placed last month?").needs_clarification


def test_follow_up_resolves_against_previous_question() -> None:
    intent = analyze(
        "break that down by region",
        history=["What was total revenue last quarter?"],
    )
    assert intent.is_follow_up
    assert "total revenue" in intent.resolved_question
    assert "by region" in intent.resolved_question


def test_follow_up_is_not_treated_as_vague() -> None:
    # "break that down" is too short to stand alone, but it is not ambiguous
    # given the previous turn.
    intent = analyze("break that down", history=["What was revenue by category?"])
    assert not intent.needs_clarification


def test_standalone_question_is_not_a_follow_up() -> None:
    intent = analyze(
        "How many suppliers are there?", history=["What was revenue last quarter?"]
    )
    assert not intent.is_follow_up
    assert intent.resolved_question == "How many suppliers are there?"


def test_follow_up_without_history_is_not_resolved() -> None:
    assert not analyze("break that down by region").is_follow_up


def test_ranking_and_trend_want_ordering() -> None:
    assert analyze("Top 5 products").wants_ordering
    assert analyze("Revenue by month").wants_ordering
    assert not analyze("How many customers?").wants_ordering
