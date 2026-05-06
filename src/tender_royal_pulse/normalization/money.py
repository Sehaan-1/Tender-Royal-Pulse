from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

INDIAN_DIGIT_GROUP_RE = re.compile(r"(\d{1,2}),(\d{2}),(\d{2}),(\d{3})")
INDIAN_DIGIT_GROUP_SIMPLE_RE = re.compile(r"(\d+),(\d{2}),(\d{3})")
INDIAN_DIGIT_GROUP_BASIC_RE = re.compile(r"(\d+),(\d{3})")
INDIAN_DIGIT_GROUP_LAKH_CRORE_RE = re.compile(r"(\d+),(\d+)")
CURRENCY_SYMBOL_RE = re.compile(r"^(?:₹|Rs\.?|INR|₹)\s*", re.IGNORECASE)
NON_NUMERIC_STRIP_RE = re.compile(r"[^\d.,\-]")


class MoneyParseError(ValueError):
    pass


def _parse_indian_grouping(value: str) -> str:
    m = INDIAN_DIGIT_GROUP_RE.fullmatch(value)
    if m:
        return m.group(1) + m.group(2) + m.group(3) + m.group(4)

    m = INDIAN_DIGIT_GROUP_SIMPLE_RE.fullmatch(value)
    if m:
        return m.group(1) + m.group(2) + m.group(3)

    m = INDIAN_DIGIT_GROUP_BASIC_RE.fullmatch(value)
    if m:
        return m.group(1) + m.group(2)

    m = INDIAN_DIGIT_GROUP_LAKH_CRORE_RE.fullmatch(value)
    if m:
        return m.group(1) + m.group(2)

    return value.replace(",", "")


def parse_indian_money(raw: str | None) -> tuple[Decimal, str] | None:
    if raw is None:
        return None

    value = raw.strip()
    if not value:
        return None

    currency = "INR"
    currency_match = CURRENCY_SYMBOL_RE.match(value)
    if currency_match:
        value = value[currency_match.end():].strip()

    value = NON_NUMERIC_STRIP_RE.sub("", value)

    if not value:
        return None

    value = _parse_indian_grouping(value)

    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise MoneyParseError(f"Cannot parse amount '{raw}' after cleanup to '{value}'") from None

    return amount, currency
