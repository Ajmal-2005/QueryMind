"""PII masking for data leaving the deployment.

The narrative feature (F13) is the first point in this system where actual
row values — not schema names, not aggregates — are sent to a third-party
API. The proposal puts PII handling in the security model, so this runs
between the result set and the prompt, and there is no path to the narrator
that skips it.

Two independent detectors, because either alone is insufficient:

- **Column names.** A column called `email` is PII regardless of what its
  values happen to look like, and this catches the fields whose contents have
  no distinctive format at all — `full_name`, `street_address`, `notes`.
- **Value patterns.** Catches PII sitting in a column nobody thought to name
  suspiciously: an email in `contact`, a card number in `reference`.

Masking replaces a value with a type token — `<email>`, not `j***@x.com`.
Partial masking leaks the domain, the last four digits, the name length; and
for the narrator's purpose, knowing the *shape* of the data is the entire
requirement. It never needs the value.

What is deliberately **not** masked: numbers the query aggregated, dates,
categories, and anything in a column the detectors do not flag. A summary of
revenue by region is the point of the product, and masking it would leave
nothing to summarise.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.analytics.profile import stringify

# Column names whose contents are personal by definition, whatever they hold.
# Matched as substrings against a lowercased, separator-stripped name, so
# `customer_email`, `CustomerEMail` and `email2` all hit `email`.
SENSITIVE_NAME_PARTS: dict[str, str] = {
    "email": "email",
    "mail": "email",
    "phone": "phone",
    "mobile": "phone",
    "telephone": "phone",
    "address": "address",
    "street": "address",
    "postcode": "address",
    "zipcode": "address",
    "ssn": "national id",
    "socialsecurity": "national id",
    "nationalid": "national id",
    "passport": "national id",
    "taxid": "national id",
    "creditcard": "payment card",
    "cardnumber": "payment card",
    "iban": "bank account",
    "accountnumber": "bank account",
    "sortcode": "bank account",
    "password": "credential",
    "passwd": "credential",
    "secret": "credential",
    "apikey": "credential",
    "token": "credential",
    "firstname": "name",
    "lastname": "name",
    "surname": "name",
    "fullname": "name",
    "customername": "name",
    "dateofbirth": "date of birth",
    "birthdate": "date of birth",
    "dob": "date of birth",
    "latitude": "location",
    "longitude": "location",
    "ipaddress": "ip address",
}

# Names that contain a sensitive substring but are not themselves personal.
# `order_address_id` is a foreign key; masking it would break the narrator's
# ability to talk about joins, and it carries no personal data itself.
NAME_EXCEPTIONS = re.compile(r"(^|_)(id|count|total|type|status|flag)($|_)", re.I)

_VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # 13-19 digits in card-like grouping. Luhn-checked below to keep long
    # order references and timestamps out of the payment-card bucket.
    ("card", re.compile(r"\b(?:\d[ -]?){12,18}\d\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # A phone number is a *grouped* run of digits, or an international one
    # with a leading +. A bare 5551234567 is indistinguishable from an order
    # id, so it is left to the column-name rule; matching it here would mask
    # every large integer in the database.
    (
        "phone",
        re.compile(
            r"(?<![\w.])"
            r"(?:\+\d[\d\s().-]{7,16}\d|\(?\d{2,4}\)?[\s.-]\d{2,4}[\s.-]?\d{2,6})"
            r"(?![\w.])"
        ),
    ),
]

_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")

PHONE_DIGIT_RANGE = (9, 15)

TOKENS = {
    "email": "<email>",
    "card": "<payment-card>",
    "ssn": "<national-id>",
    "iban": "<bank-account>",
    "ip": "<ip-address>",
    "phone": "<phone>",
}


@dataclass
class MaskedColumn:
    column: str
    rule: str
    """'column name' or 'value pattern'."""

    detected_as: str
    values_masked: int = 0


@dataclass
class MaskingReport:
    columns: list[MaskedColumn] = field(default_factory=list)
    values_masked: int = 0

    @property
    def any_masked(self) -> bool:
        return bool(self.columns)

    @property
    def column_names(self) -> list[str]:
        return [c.column for c in self.columns]


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def classify_column(name: str) -> str | None:
    """Return what a column name says it holds, or None if nothing personal."""
    if NAME_EXCEPTIONS.search(name):
        return None

    normalised = _normalise(name)
    # Longest part first so `creditcard` wins over `card`, and `dateofbirth`
    # over the shorter entries it contains.
    for part in sorted(SENSITIVE_NAME_PARTS, key=len, reverse=True):
        if part in normalised:
            return SENSITIVE_NAME_PARTS[part]
    return None


def _luhn(digits: str) -> bool:
    """Standard checksum every real payment card satisfies."""
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _plausible(kind: str, matched: str) -> bool:
    """Second check on a pattern hit.

    The regexes are deliberately loose — a tight one misses real PII — so the
    expensive-to-be-wrong cases get a cheap confirmation here. A false
    positive is not harmless: masking `order_reference` or `order_date` would
    hide the very columns the summary is about.
    """
    digits = re.sub(r"\D", "", matched)

    if kind == "card":
        return 13 <= len(digits) <= 19 and _luhn(digits)

    if kind == "phone":
        low, high = PHONE_DIGIT_RANGE
        if not low <= len(digits) <= high:
            return False
        # `2024-01-15` is grouped exactly like a phone number and is not one.
        return not _ISO_DATE.match(matched.strip())

    return True


def mask_value(value: Any) -> tuple[str, str | None]:
    """Mask any PII inside one value.

    Returns the value and which pattern fired, or None when it was clean.
    Substitution is in place rather than wholesale replacement so a sentence
    keeps its meaning: "call <phone> about order 4471" is still useful.
    """
    if value is None or not isinstance(value, str | int | float):
        return stringify(value) if value is not None else "", None

    text = stringify(value)
    detected: str | None = None

    for kind, pattern in _VALUE_PATTERNS:

        def _replace(match: re.Match[str], kind: str = kind) -> str:
            return TOKENS[kind] if _plausible(kind, match.group()) else match.group()

        replaced = pattern.sub(_replace, text)
        if replaced != text:
            detected = detected or kind
            text = replaced

    return text, detected


def mask_rows(
    columns: list[str], rows: list[list[Any]]
) -> tuple[list[list[Any]], MaskingReport]:
    """Mask personal data in a result set before it is sent anywhere.

    Non-sensitive values pass through with their original Python type, so the
    numbers the narrator reasons about stay numbers.
    """
    report = MaskingReport()
    by_name: dict[str, MaskedColumn] = {}

    # A column flagged by name is masked in full, including values that match
    # no pattern — that is the entire point of the name rule.
    name_flagged: dict[int, str] = {}
    for index, name in enumerate(columns):
        detected = classify_column(name)
        if detected:
            name_flagged[index] = detected
            entry = MaskedColumn(column=name, rule="column name", detected_as=detected)
            by_name[name] = entry
            report.columns.append(entry)

    masked_rows: list[list[Any]] = []
    for row in rows:
        masked_row: list[Any] = []
        for index, value in enumerate(row):
            name = columns[index] if index < len(columns) else f"column_{index}"

            if index in name_flagged:
                if value is None:
                    masked_row.append(None)
                else:
                    masked_row.append(f"<{name_flagged[index]}>")
                    by_name[name].values_masked += 1
                    report.values_masked += 1
                continue

            replaced, detected = mask_value(value)
            if detected is None:
                masked_row.append(value)
                continue

            masked_row.append(replaced)
            entry = by_name.get(name)
            if entry is None:
                entry = MaskedColumn(
                    column=name, rule="value pattern", detected_as=detected
                )
                by_name[name] = entry
                report.columns.append(entry)
            entry.values_masked += 1
            report.values_masked += 1

        masked_rows.append(masked_row)

    return masked_rows, report


__all__ = [
    "MaskedColumn",
    "MaskingReport",
    "classify_column",
    "mask_rows",
    "mask_value",
]
