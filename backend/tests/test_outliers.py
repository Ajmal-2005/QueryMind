"""Outlier detection (F15)."""

from app.services.analytics.outliers import MIN_ROWS_FOR_DETECTION, detect
from app.services.analytics.profile import profile_result


def _detect(columns: list[str], rows: list[list]):
    return detect(profile_result(columns, rows), rows)


def test_a_clear_outlier_is_flagged_by_both_methods() -> None:
    rows = [[v] for v in [10, 11, 12, 10, 11, 13, 12, 11, 10, 12, 5000]]
    report = _detect(["amount"], rows)

    assert report.total == 1
    outlier = report.outliers[0]
    assert outlier.value == 5000
    assert outlier.row_index == 10
    assert set(outlier.methods) == {"iqr", "zscore"}


def test_iqr_catches_what_the_zscore_misses_on_skewed_data() -> None:
    """The point of running two detectors.

    One large value inflates the standard deviation enough to keep its own
    z-score under 3. Quartiles are unmoved by it, so the IQR rule still fires.
    """
    rows = [[v] for v in [1, 1, 2, 2, 2, 3, 3, 3, 4, 60]]
    report = _detect(["v"], rows)

    flagged = next(o for o in report.outliers if o.value == 60)
    assert "iqr" in flagged.methods
    assert "zscore" not in flagged.methods


def test_uniform_data_produces_no_outliers() -> None:
    report = _detect(["v"], [[5] for _ in range(20)])
    assert report.total == 0
    assert report.columns[0].checked is False
    assert "identical" in report.columns[0].reason


def test_short_results_are_declined_rather_than_guessed_at() -> None:
    rows = [[v] for v in [1, 2, 3, 400]]
    report = _detect(["v"], rows)

    assert report.total == 0
    assert report.columns[0].checked is False
    assert str(MIN_ROWS_FOR_DETECTION) in report.columns[0].reason


def test_non_numeric_columns_are_not_checked() -> None:
    rows = [["north", 1] for _ in range(10)]
    report = _detect(["region", "n"], rows)
    assert [c.column for c in report.columns] == ["n"]


def test_fences_are_reported_so_a_flag_can_be_justified() -> None:
    rows = [[v] for v in [10, 11, 12, 10, 11, 13, 12, 11, 10, 12, 5000]]
    summary = _detect(["amount"], rows).columns[0]

    assert summary.lower_fence is not None
    assert summary.upper_fence is not None
    assert summary.upper_fence < 5000


def test_outliers_are_ordered_most_extreme_first() -> None:
    rows = [[v] for v in [10, 11, 12, 10, 11, 13, 12, 11, 100, 5000]]
    report = _detect(["v"], rows)

    values = [o.value for o in report.outliers]
    assert values == sorted(values, reverse=True)


def test_row_indexes_point_back_at_the_original_rows() -> None:
    rows = [[v] for v in [10, 11, 5000, 10, 11, 13, 12, 11, 10, 12]]
    outlier = _detect(["v"], rows).outliers[0]

    assert outlier.row_index == 2
    assert rows[outlier.row_index][0] == 5000


def test_nulls_do_not_break_detection() -> None:
    rows = [[v] for v in [10, None, 11, 12, None, 10, 11, 13, 12, 11, 5000]]
    report = _detect(["v"], rows)
    assert report.total == 1
    assert report.outliers[0].value == 5000
