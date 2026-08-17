"""Statistical profiling (F14).

The arithmetic is the standard library's and is not re-tested here. What is
tested is type inference, because every downstream decision - chart, outlier,
trend - is made from `kind`, and because SQLite hands back dates as strings
which is exactly the case naive inference gets wrong.
"""

from datetime import date, datetime
from decimal import Decimal

from app.services.analytics.profile import ColumnKind, profile_result


def test_numeric_column_is_detected_and_described() -> None:
    profile = profile_result(["revenue"], [[10], [20], [30], [40]])
    column = profile.columns[0]

    assert column.kind is ColumnKind.NUMERIC
    assert (column.minimum, column.maximum) == (10.0, 40.0)
    assert column.mean == 25.0
    assert column.median == 25.0


def test_iso_date_strings_are_temporal_not_categorical() -> None:
    """SQLite has no date type - a DATE column arrives as `str`."""
    profile = profile_result(
        ["ordered_on"], [["2024-01-15"], ["2024-02-20"], ["2024-03-11"]]
    )

    assert profile.columns[0].kind is ColumnKind.TEMPORAL
    assert profile.columns[0].earliest == "2024-01-15"
    assert profile.columns[0].latest == "2024-03-11"


def test_period_and_year_strings_are_temporal() -> None:
    """strftime('%Y-%m', ...) and EXTRACT(YEAR ...) output."""
    months = profile_result(["month"], [["2024-01"], ["2024-02"], ["2024-03"]])
    years = profile_result(["yr"], [["2022"], ["2023"], ["2024"]])

    assert months.columns[0].kind is ColumnKind.TEMPORAL
    assert years.columns[0].kind is ColumnKind.TEMPORAL


def test_native_date_objects_are_temporal() -> None:
    profile = profile_result(
        ["d"], [[date(2024, 1, 1)], [datetime(2024, 2, 1)], [date(2024, 3, 1)]]
    )
    assert profile.columns[0].kind is ColumnKind.TEMPORAL
    assert profile.columns[0].inferred_from == "values are dates"


def test_decimal_is_numeric() -> None:
    """Postgres NUMERIC comes back as Decimal, not float."""
    profile = profile_result(["amount"], [[Decimal("1.5")], [Decimal("2.5")]])
    assert profile.columns[0].kind is ColumnKind.NUMERIC
    assert profile.columns[0].mean == 2.0


def test_booleans_are_not_averaged_as_numbers() -> None:
    """`bool` subclasses `int`; a mean of a flag column is meaningless."""
    profile = profile_result(["is_active"], [[True], [False], [True], [True]])
    column = profile.columns[0]

    assert column.kind is ColumnKind.BOOLEAN
    assert column.mean is None
    assert column.top_values[0].value == "True"
    assert column.top_values[0].count == 3


def test_low_cardinality_strings_are_categorical() -> None:
    rows = [["north"], ["south"], ["north"], ["east"], ["north"], ["south"]]
    column = profile_result(["region"], rows).columns[0]

    assert column.kind is ColumnKind.CATEGORICAL
    assert column.distinct_count == 3
    assert column.top_values[0].value == "north"
    assert column.top_values[0].fraction == 0.5


def test_high_cardinality_strings_are_text_not_categorical() -> None:
    """An identifier column must not become a bar chart axis."""
    rows = [[f"order-{n}"] for n in range(80)]
    assert profile_result(["reference"], rows).columns[0].kind is ColumnKind.TEXT


def test_group_by_keys_stay_categorical_despite_being_all_distinct() -> None:
    """The shape this product produces most often.

    Every GROUP BY gives one row per key, so distinct == row_count. A ratio
    test would call the grouping column free text and refuse to chart it.
    """
    rows = [["north", 10], ["south", 20], ["east", 15], ["west", 5]]
    assert profile_result(["region", "revenue"], rows).columns[0].kind is (
        ColumnKind.CATEGORICAL
    )


def test_long_values_are_free_text_however_few_there_are() -> None:
    rows = [["a" * 200], ["b" * 200], ["c" * 200]]
    column = profile_result(["comment"], rows).columns[0]
    assert column.kind is ColumnKind.TEXT
    assert "free text" in column.inferred_from


def test_nulls_are_counted_and_excluded_from_statistics() -> None:
    profile = profile_result(["v"], [[10], [None], [30], [None]])
    column = profile.columns[0]

    assert column.null_count == 2
    assert column.null_fraction == 0.5
    assert column.count == 2
    assert column.mean == 20.0


def test_blank_strings_count_as_missing() -> None:
    column = profile_result(["note"], [["a"], ["   "], [""], ["b"]]).columns[0]
    assert column.null_count == 2


def test_all_null_column_is_empty_kind() -> None:
    column = profile_result(["v"], [[None], [None]]).columns[0]
    assert column.kind is ColumnKind.EMPTY
    assert column.inferred_from == "every value is null"


def test_one_bad_row_does_not_reclassify_a_date_column() -> None:
    rows = [["2024-01-01"], ["2024-01-02"], ["2024-01-03"], ["n/a"]]
    # 3 of 4 parse: 0.75, below the 0.9 threshold, so this one does *not*
    # stay temporal. The guard exists for larger columns.
    assert profile_result(["d"], rows).columns[0].kind is not ColumnKind.TEMPORAL

    many = [[f"2024-01-{n:02d}"] for n in range(1, 20)] + [["n/a"]]
    assert profile_result(["d"], many).columns[0].kind is ColumnKind.TEMPORAL


def test_quartiles_bracket_the_median() -> None:
    column = profile_result(["v"], [[n] for n in range(1, 101)]).columns[0]
    assert column.q1 < column.median < column.q3
    assert column.iqr == column.q3 - column.q1


def test_ragged_rows_do_not_shift_columns() -> None:
    """A short row pads rather than silently misaligning every later column."""
    profile = profile_result(["a", "b"], [[1, 2], [3]])
    assert profile.columns[1].count == 1
    assert profile.columns[1].null_count == 1


def test_scalar_result_is_recognised() -> None:
    assert profile_result(["total"], [[42]]).is_scalar
    assert not profile_result(["a", "b"], [[1, 2]]).is_scalar


def test_empty_result_profiles_without_error() -> None:
    profile = profile_result(["a", "b"], [])
    assert profile.row_count == 0
    assert all(c.kind is ColumnKind.EMPTY for c in profile.columns)
