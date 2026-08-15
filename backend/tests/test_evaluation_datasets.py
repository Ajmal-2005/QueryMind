"""The custom benchmark set ships in the repo, so CI can always load it."""

import pytest

from evaluation import datasets
from evaluation.runner import run


def test_custom_set_loads() -> None:
    examples = datasets.load_custom_set()
    assert len(examples) >= 10


def test_custom_examples_are_well_formed() -> None:
    for example in datasets.load_custom_set():
        assert example.question.strip()
        assert example.gold_sql.upper().startswith(("SELECT", "WITH"))
        assert example.db_id


def test_question_ids_are_unique() -> None:
    ids = [e.question_id for e in datasets.load_custom_set()]
    assert len(ids) == len(set(ids))


def test_limit_is_respected() -> None:
    assert len(datasets.load_custom_set(limit=3)) == 3


def test_missing_benchmark_explains_where_to_put_it() -> None:
    if datasets.available()["spider"]:
        pytest.skip("Spider is present locally")

    with pytest.raises(datasets.DatasetNotAvailable, match="yale-lily"):
        datasets.load_spider_dev()


def test_harness_runs_end_to_end_with_the_stub_predictor() -> None:
    # Phase 0 baseline: the harness completes and honestly reports 0%.
    records, summary = run("custom", limit=5)

    assert summary.total == 5
    assert summary.execution_accuracy == 0.0
    assert all(r.error_category == "not_implemented" for r in records)
