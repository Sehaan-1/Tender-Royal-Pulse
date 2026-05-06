from __future__ import annotations

import re
from datetime import UTC, date, datetime, timezone

_DATETIME_FORMATS: list[tuple[str, bool]] = [
    ("%d-%b-%Y %I:%M %p", True),
    ("%d-%b-%Y %I:%M:%S %p", True),
    ("%d-%b-%Y %H:%M", False),
    ("%d-%b-%Y %H:%M:%S", False),
    ("%d-%m-%Y %I:%M %p", True),
    ("%d/%m/%Y %I:%M %p", True),
    ("%Y-%m-%dT%H:%M:%S%z", False),
    ("%Y-%m-%dT%H:%M:%S", False),
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %I:%M %p", True),
    ("%d/%m/%Y", False),
    ("%d-%m-%Y", False),
    ("%Y-%m-%d", False),
    ("%d-%b-%Y", False),
    ("%d %B %Y", False),
    ("%B %d, %Y", False),
]

_MONTH_ABBR_MAP: dict[str, str] = {
    "jan": "Jan",
    "feb": "Feb",
    "mar": "Mar",
    "apr": "Apr",
    "may": "May",
    "jun": "Jun",
    "jul": "Jul",
    "aug": "Aug",
    "sep": "Sep",
    "oct": "Oct",
    "nov": "Nov",
    "dec": "Dec",
}

_MONTH_FULL_MAP: dict[str, str] = {
    "january": "January",
    "february": "February",
    "march": "March",
    "april": "April",
    "may": "May",
    "june": "June",
    "july": "July",
    "august": "August",
    "september": "September",
    "october": "October",
    "november": "November",
    "december": "December",
}

_LOCAL_TZ = UTC


class DateParseError(ValueError):
    pass


def _normalize_month_abbr(value: str) -> str:
    tokens = re.split(r"([^a-zA-Z0-9])", value)
    result: list[str] = []
    for t in tokens:
        lowered = t.lower()
        if lowered in _MONTH_ABBR_MAP:
            result.append(_MONTH_ABBR_MAP[lowered])
        elif lowered in _MONTH_FULL_MAP:
            result.append(_MONTH_FULL_MAP[lowered])
        else:
            result.append(t)
    return "".join(result)


def _clean_datetime_input(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"\s+", " ", value)
    value = _normalize_month_abbr(value)
    value = value.replace("\u202f", " ").replace("\xa0", " ")
    return value


def parse_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None

    value = _clean_datetime_input(raw)
    if not value:
        return None

    for fmt, _ in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt
        except ValueError:
            continue

    iso_value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass

    try:
        import dateutil.parser

        return dateutil.parser.parse(value)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass

    return None


def parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None

    value = _clean_datetime_input(raw)
    if not value:
        return None

    for fmt, _ in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass

    try:
        import dateutil.parser

        return dateutil.parser.parse(value).date()
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass

    return None


def _set_local_tz(tz: timezone) -> None:
    global _LOCAL_TZ
    _LOCAL_TZ = tz