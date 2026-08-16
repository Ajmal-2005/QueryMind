"""PII masking before data leaves the deployment.

This is the security boundary for F13: the narrative feature is the first
point where row values, not just schema names, are sent to a third party.
"""

from app.services.analytics.masking import classify_column, mask_rows, mask_value


def test_email_is_replaced_with_a_type_token() -> None:
    masked, detected = mask_value("contact ada@example.com today")
    assert detected == "email"
    assert "ada@example.com" not in masked
    assert "<email>" in masked
    # The surrounding sentence survives, so the value stays useful as context.
    assert masked.startswith("contact ")


def test_a_real_card_number_is_masked() -> None:
    masked, detected = mask_value("4111 1111 1111 1111")
    assert detected == "card"
    assert masked == "<payment-card>"


def test_a_long_number_that_fails_luhn_is_left_alone() -> None:
    """Order references and timestamps must not become 'payment cards'."""
    masked, detected = mask_value("1234567890123456")
    assert detected is None
    assert masked == "1234567890123456"


def test_a_grouped_phone_number_is_masked() -> None:
    assert mask_value("+44 7700 900123")[1] == "phone"
    assert mask_value("555-123-4567")[1] == "phone"


def test_a_date_is_not_mistaken_for_a_phone_number() -> None:
    """`2024-01-15` is grouped exactly like a phone number.

    Masking it would hide the axis of every trend this product draws.
    """
    masked, detected = mask_value("2024-01-15")
    assert detected is None
    assert masked == "2024-01-15"


def test_national_id_and_ip_are_masked() -> None:
    assert mask_value("123-45-6789")[1] == "ssn"
    assert mask_value("192.168.1.44")[1] == "ip"


def test_column_names_flag_data_with_no_distinctive_format() -> None:
    """A person's name looks like any other short string."""
    assert classify_column("full_name") == "name"
    assert classify_column("customer_email") == "email"
    assert classify_column("shipping_address") == "address"
    assert classify_column("api_key") == "credential"
    assert classify_column("DateOfBirth") == "date of birth"


def test_foreign_keys_are_not_treated_as_personal() -> None:
    """Masking `address_id` would break the narrator's grasp of the joins."""
    assert classify_column("address_id") is None
    assert classify_column("email_count") is None
    assert classify_column("address_type") is None


def test_ordinary_columns_are_not_flagged() -> None:
    for name in ("revenue", "order_date", "region", "quantity", "product"):
        assert classify_column(name) is None


def test_name_flagged_columns_are_masked_in_full() -> None:
    columns = ["full_name", "region", "revenue"]
    rows = [["Ada Lovelace", "north", 1200], ["Grace Hopper", "south", 900]]
    masked, report = mask_rows(columns, rows)

    assert masked[0] == ["<name>", "north", 1200]
    assert masked[1][0] == "<name>"
    assert report.column_names == ["full_name"]
    assert report.values_masked == 2


def test_numbers_and_categories_pass_through_untouched() -> None:
    """Masking the measures would leave the narrator nothing to summarise."""
    columns = ["region", "revenue", "orders"]
    rows = [["north", 1200.5, 42], ["south", 900.0, 31]]
    masked, report = mask_rows(columns, rows)

    assert masked == rows
    assert not report.any_masked


def test_pii_hiding_in_an_innocently_named_column_is_caught() -> None:
    columns = ["reference", "amount"]
    rows = [["ping ada@example.com", 10], ["clean", 20]]
    masked, report = mask_rows(columns, rows)

    assert "<email>" in masked[0][0]
    assert masked[1][0] == "clean"
    assert report.columns[0].rule == "value pattern"
    assert report.columns[0].values_masked == 1


def test_nulls_stay_null_rather_than_becoming_a_token() -> None:
    masked, _ = mask_rows(["email"], [[None], ["a@b.com"]])
    assert masked[0][0] is None
    assert masked[1][0] == "<email>"


def test_report_names_every_masked_column_and_its_rule() -> None:
    columns = ["full_name", "notes", "revenue"]
    rows = [["Ada", "call +44 7700 900123", 10]]
    _, report = mask_rows(columns, rows)

    rules = {c.column: c.rule for c in report.columns}
    assert rules["full_name"] == "column name"
    assert rules["notes"] == "value pattern"
    assert "revenue" not in rules
