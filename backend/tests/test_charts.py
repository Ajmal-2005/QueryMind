"""Chart selection (F11) and override options (F12)."""

from app.services.analytics.charts import ChartType, options, recommend
from app.services.analytics.profile import profile_result


def _chart(columns: list[str], rows: list[list]) -> object:
    return recommend(profile_result(columns, rows))


def test_single_number_is_a_kpi() -> None:
    chart = _chart(["total_customers"], [[482]])
    assert chart.type is ChartType.KPI
    assert chart.y == ["total_customers"]


def test_date_column_gives_a_line() -> None:
    rows = [["2024-01", 100], ["2024-02", 140], ["2024-03", 180]]
    chart = _chart(["month", "revenue"], rows)

    assert chart.type is ChartType.LINE
    assert chart.x == "month"
    assert chart.y == ["revenue"]


def test_line_carries_a_series_column_when_one_exists() -> None:
    rows = [
        ["2024-01", "north", 10],
        ["2024-01", "south", 20],
        ["2024-02", "north", 30],
        ["2024-02", "south", 40],
    ]
    chart = _chart(["month", "region", "revenue"], rows)

    assert chart.type is ChartType.LINE
    assert chart.series == "region"


def test_one_category_against_a_measure_gives_a_bar() -> None:
    rows = [["north", 10], ["south", 20], ["east", 15]]
    chart = _chart(["region", "revenue"], rows)

    assert chart.type is ChartType.BAR
    assert chart.x == "region"
    assert ChartType.PIE in chart.alternatives


def test_pie_is_withheld_when_a_value_is_negative() -> None:
    """Parts of a whole cannot be negative."""
    rows = [["north", 10], ["south", -20], ["east", 15]]
    assert ChartType.PIE not in _chart(["region", "profit"], rows).alternatives


def test_pie_is_withheld_beyond_a_handful_of_slices() -> None:
    rows = [[f"cat-{n}", n] for n in range(10)]
    chart = _chart(["category", "n"], rows)
    assert chart.type is ChartType.BAR
    assert ChartType.PIE not in chart.alternatives


def test_too_many_categories_falls_back_to_a_table() -> None:
    """A 40-bar chart is a smear; a sortable table is more useful."""
    rows = [[f"customer-{n}", n] for n in range(40)]
    chart = _chart(["customer", "spend"], rows)

    assert chart.type is ChartType.TABLE
    assert "40 distinct values" in chart.reason


def test_two_bare_numerics_give_a_scatter() -> None:
    rows = [[n, n * 2 + 1] for n in range(20)]
    chart = _chart(["price", "quantity"], rows)

    assert chart.type is ChartType.SCATTER
    assert chart.x == "price"
    assert chart.y == ["quantity"]


def test_no_numeric_column_is_a_table() -> None:
    rows = [["a", "x"], ["b", "y"], ["c", "z"]]
    chart = _chart(["code", "label"], rows)

    assert chart.type is ChartType.TABLE
    assert "nothing to measure" in chart.reason


def test_empty_result_is_a_table() -> None:
    assert _chart(["a", "b"], []).type is ChartType.TABLE


def test_single_period_is_not_plotted_as_a_line() -> None:
    """One point is not a series."""
    rows = [["2024-01", 100], ["2024-01", 200], ["2024-01", 300]]
    assert _chart(["month", "revenue"], rows).type is ChartType.TABLE


def test_every_recommendation_states_a_reason() -> None:
    cases = [
        (["total"], [[1]]),
        (["month", "revenue"], [["2024-01", 1], ["2024-02", 2], ["2024-03", 3]]),
        (["region", "revenue"], [["n", 1], ["s", 2]]),
        (["a", "b"], [[1, 2], [3, 4]]),
        (["x"], []),
    ]
    for columns, rows in cases:
        assert _chart(columns, rows).reason


def test_options_expose_columns_per_axis_type() -> None:
    rows = [["2024-01", "north", 10], ["2024-02", "south", 20]]
    available = options(profile_result(["month", "region", "revenue"], rows))

    assert available["temporal"] == ["month"]
    assert available["categorical"] == ["region"]
    assert available["numeric"] == ["revenue"]
    assert available["all"] == ["month", "region", "revenue"]
