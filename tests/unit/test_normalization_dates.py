from __future__ import annotations

from datetime import date, datetime

import pytest

from tender_royal_pulse.normalization.dates import parse_date, parse_datetime


@pytest.mark.parametrize("raw, expected", [
    ("09-Feb-2026 09:30 AM", datetime(2026, 2, 9, 9, 30)),
    ("09-02-2026 09:30 AM", datetime(2026, 2, 9, 9, 30)),
    ("2026-02-09T09:30:00", datetime(2026, 2, 9, 9, 30)),
    ("09-Feb-2026", datetime(2026, 2, 9, 0, 0)),
    ("  09-Feb-2026  ", datetime(2026, 2, 9, 0, 0)),
    (None, None),
    ("", None),
    ("invalid date", None),
])
def test_parse_datetime(raw, expected):
    result = parse_datetime(raw)
    if expected is None:
        assert result is None
    else:
        assert result == expected

@pytest.mark.parametrize("raw, expected", [
    ("09-Feb-2026", date(2026, 2, 9)),
    ("09/02/2026", date(2026, 2, 9)),
    ("2026-02-09", date(2026, 2, 9)),
    (None, None),
    ("invalid", None),
])
def test_parse_date(raw, expected):
    result = parse_date(raw)
    if expected is None:
        assert result is None
    else:
        assert result == expected
