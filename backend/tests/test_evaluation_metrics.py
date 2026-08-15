"""Tests for the evaluation harness.

The metrics decide whether the project's headline numbers are believable, so
they are tested directly rather than trusted.
"""

from evaluation.metrics import (
    EvalRecord,
    execution_match,
    schema_linking_recall,
    summarize,
)


def test_identical_result_sets_match() -> None:
    assert execution_match([(1, "a"), (2, "b")], [(1, "a"), (2, "b")])


def test_row_order_is_ignored_by_default() -> None:
    # Without an ORDER BY, row order is not part of the answer.
    assert execution_match([(2, "b"), (1, "a")], [(1, "a"), (2, "b")])


def test_row_order_is_enforced_when_requested() -> None:
    assert not execution_match(
        [(2, "b"), (1, "a")], [(1, "a"), (2, "b")], order_matters=True
    )


def test_numeric_types_compare_across_dialects() -> None:
    # MySQL returning 3 and Postgres returning Decimal('3.0') is the same answer.
    assert execution_match([(3.0,)], [(3,)])


def test_differing_row_counts_do_not_match() -> None:
    assert not execution_match([(1,)], [(1,), (2,)])


def test_none_result_never_matches() -> None:
    assert not execution_match(None, [(1,)])
    assert not execution_match([(1,)], None)


def test_nulls_are_distinguished_from_empty_string() -> None:
    assert not execution_match([(None,)], [("",)])


def test_schema_linking_recall_is_fraction_of_gold_tables_found() -> None:
    assert schema_linking_recall(["orders", "products"], ["orders", "customers"]) == 0.5


def test_schema_linking_recall_ignores_case() -> None:
    assert schema_linking_recall(["Orders"], ["orders"]) == 1.0


def test_schema_linking_recall_is_unharmed_by_extra_tables() -> None:
    # Over-retrieval costs tokens, not recall.
    assert schema_linking_recall(["orders", "noise", "more_noise"], ["orders"]) == 1.0


def _record(**kwargs) -> EvalRecord:
    base = {"question_id": "q", "question": "?", "db_id": "db", "gold_sql": "SELECT 1"}
    base.update(kwargs)
    return EvalRecord(**base)


def test_summary_of_empty_run_is_all_zero() -> None:
    summary = summarize([])
    assert summary.total == 0
    assert summary.execution_accuracy == 0.0


def test_execution_accuracy_counts_correct_over_total() -> None:
    records = [_record(correct=True), _record(correct=False), _record(correct=True)]
    assert summarize(records).execution_accuracy == 2 / 3


def test_valid_sql_rate_is_independent_of_correctness() -> None:
    # Ran fine, wrong answer: valid but not correct.
    records = [_record(executed=True, correct=False), _record(executed=False)]
    summary = summarize(records)
    assert summary.valid_sql_rate == 0.5
    assert summary.execution_accuracy == 0.0


def test_recovery_rate_is_over_queries_that_needed_correction() -> None:
    records = [
        _record(correction_attempts=1, recovered_by_correction=True),
        _record(correction_attempts=2, recovered_by_correction=False),
        _record(correction_attempts=0),  # never failed; must not dilute the rate
    ]
    assert summarize(records).correction_recovery_rate == 0.5


def test_latency_percentiles_are_reported() -> None:
    records = [_record(latency_ms=float(ms)) for ms in range(1, 101)]
    summary = summarize(records)
    assert summary.latency_p50_ms == 50
    assert summary.latency_p95_ms == 95


def test_tokens_are_totalled() -> None:
    assert (
        summarize([_record(tokens_used=100), _record(tokens_used=250)]).total_tokens
        == 350
    )
