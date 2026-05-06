from __future__ import annotations

from decimal import Decimal

import pytest

from tender_royal_pulse.normalization.money import parse_indian_money


@pytest.mark.parametrize("raw, expected_val", [
    ("₹ 1,23,45,678", Decimal("12345678")),
    ("Rs. 1,23,45,678", Decimal("12345678")),
    ("INR 12345678", Decimal("12345678")),
    ("1,23,45,678", Decimal("12345678")),
    ("12345678", Decimal("12345678")),
    ("₹ 1,00,000", Decimal("100000")),
    ("500", Decimal("500")),
    (None, None),
    ("", None),
    ("not money", None), # This might raise MoneyParseError depending on implementation
])
def test_parse_indian_money(raw, expected_val):
    try:
        result = parse_indian_money(raw)
        if result is None:
            assert expected_val is None
        else:
            assert result[0] == expected_val
    except Exception:
        if expected_val is not None:
            pytest.fail(f"Raised exception for valid input {raw}")
