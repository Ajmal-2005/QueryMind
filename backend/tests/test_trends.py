"""Trend analysis (F16)."""

import pytest

from app.services.analytics.profile import profile_result
from app.services.analytics.trends import analyze


def _trend(columns: list[str], rows: list[list]):
    return analyze(profile_result(columns, rows), rows)


def test_a_rising_series_is_described_as_rising() -> None:
    rows = [["2024-01", 100], ["2024-02", 120], ["2024-03", 150], ["2024-04", 190]]
    trend = _trend(["month", "revenue"], rows).trend

    assert trend is not None
    assert trend.direction == "rising"
    assert trend.first_value == 100
    assert trend.last_value == 190
    assert trend.total_change == 90
    assert trend.total_growth_rate == pytest.approx(0.9)


def test_a_falling_series_is_described_as_falling() -> None:
    rows = [["2024-01", 200], ["2024-02", 150], ["2024-03", 100]]
    assert _trend(["month", "v"], rows).trend.direction == "falling"


def test_noise_around_a_level_reads_as_flat() -> None:
    rows = [["2024-01", 100], ["2024-02", 101], ["2024-03", 99], ["2024-04", 100]]
    assert _trend(["month", "v"], rows).trend.direction == "flat"


def test_a_final_uptick_does_not_by_itself_declare_growth() -> None:
    """First-to-last comparison would call this rising; the slope does not.

    Four declining months and one small recovery. Every period votes, so the
    last one cannot outweigh the rest. A *large* final spike would still move
    the verdict - least squares is not robust to outliers, and a series that
    genuinely spiked should be reported as having done so.
    """
    rows = [
        ["2024-01", 100],
        ["2024-02", 98],
        ["2024-03", 95],
        ["2024-04", 92],
        ["2024-05", 105],
    ]
    trend = _trend(["month", "v"], rows).trend

    assert trend.last_value > trend.first_value  # first-to-last says "rising"
    assert trend.direction == "flat"


def test_period_over_period_deltas_and_rates() -> None:
    rows = [["2024-01", 100], ["2024-02", 150], ["2024-03", 75]]
    points = _trend(["month", "v"], rows).trend.points

    assert points[0].delta is None
    assert points[1].delta == 50
    assert points[1].growth_rate == pytest.approx(0.5)
    assert points[2].growth_rate == pytest.approx(-0.5)


def test_growth_off_a_zero_base_is_undefined_not_infinite() -> None:
    rows = [["2024-01", 0], ["2024-02", 50], ["2024-03", 80]]
    trend = _trend(["month", "v"], rows).trend

    assert trend.points[1].growth_rate is None
    assert trend.points[1].delta == 50
    assert trend.total_growth_rate is None


def test_moving_average_uses_a_trailing_window() -> None:
    rows = [["2024-0" + str(n), n * 10] for n in range(1, 6)]
    points = _trend(["month", "v"], rows).trend.points

    assert points[0].moving_average is None
    assert points[1].moving_average is None
    assert points[2].moving_average == pytest.approx((10 + 20 + 30) / 3)
    assert points[4].moving_average == pytest.approx((30 + 40 + 50) / 3)


def test_out_of_order_rows_are_sorted_chronologically() -> None:
    rows = [["2024-03", 300], ["2024-01", 100], ["2024-02", 200]]
    points = _trend(["month", "v"], rows).trend.points

    assert [p.period for p in points] == ["2024-01", "2024-02", "2024-03"]
    assert points[0].value == 100


def test_best_and_worst_periods_are_identified() -> None:
    rows = [["2024-01", 100], ["2024-02", 500], ["2024-03", 50]]
    trend = _trend(["month", "v"], rows).trend

    assert trend.best_period == "2024-02"
    assert trend.worst_period == "2024-03"


def test_repeated_periods_are_declined_not_averaged() -> None:
    """A detail listing is not a time series."""
    rows = [["2024-01", 10], ["2024-01", 20], ["2024-02", 30], ["2024-02", 40]]
    result = _trend(["month", "v"], rows)

    assert result.trend is None
    assert "repeats" in result.reason


def test_no_date_column_declines_with_a_reason() -> None:
    result = _trend(["region", "v"], [["n", 1], ["s", 2], ["e", 3]])
    assert result.trend is None
    assert result.reason == "no date column in the result"


def test_too_few_periods_declines_with_a_reason() -> None:
    result = _trend(["month", "v"], [["2024-01", 1], ["2024-02", 2]])
    assert result.trend is None
    assert "need at least 3" in result.reason


def test_summary_reads_as_a_sentence() -> None:
    rows = [["2024-01", 100], ["2024-02", 120], ["2024-03", 150], ["2024-04", 190]]
    summary = _trend(["month", "revenue"], rows).trend.summary

    assert "revenue" in summary
    assert "rising" in summary
    assert "+90.0%" in summary
