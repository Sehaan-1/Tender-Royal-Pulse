from __future__ import annotations

import re
import unicodedata

_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")
_NON_PRINTABLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE_COLLAPSE_RE.sub(" ", value).strip()


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value)
    cleaned = _NON_PRINTABLE_RE.sub("", normalized)
    result = normalize_whitespace(cleaned)
    return result or None
