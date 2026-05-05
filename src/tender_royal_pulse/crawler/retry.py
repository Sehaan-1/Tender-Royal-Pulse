from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ErrorClass(StrEnum):
    TIMEOUT = "TIMEOUT"
    HTTP_429 = "HTTP_429"
    HTTP_5XX = "HTTP_5XX"
    HTTP_4XX = "HTTP_4XX"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PARSE_FAILURE = "PARSE_FAILURE"
    SELECTOR_DRIFT = "SELECTOR_DRIFT"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class RetryConfig:
    max_attempts: int
    backoff_seconds: list[float]


RETRY_POLICY: dict[ErrorClass, RetryConfig] = {
    ErrorClass.TIMEOUT: RetryConfig(max_attempts=3, backoff_seconds=[1.0, 2.0, 4.0]),
    ErrorClass.HTTP_429: RetryConfig(max_attempts=3, backoff_seconds=[5.0, 10.0, 20.0]),
    ErrorClass.HTTP_5XX: RetryConfig(max_attempts=3, backoff_seconds=[1.0, 2.0, 4.0]),
    ErrorClass.SESSION_EXPIRED: RetryConfig(max_attempts=2, backoff_seconds=[3.0, 6.0]),
    ErrorClass.PARSE_FAILURE: RetryConfig(max_attempts=2, backoff_seconds=[0.5, 1.0]),
    ErrorClass.NETWORK_ERROR: RetryConfig(max_attempts=3, backoff_seconds=[1.0, 2.0, 4.0]),
    ErrorClass.HTTP_4XX: RetryConfig(max_attempts=1, backoff_seconds=[]),
    ErrorClass.SELECTOR_DRIFT: RetryConfig(max_attempts=1, backoff_seconds=[]),
    ErrorClass.UNKNOWN: RetryConfig(max_attempts=2, backoff_seconds=[1.0, 2.0]),
}

_SESSION_EXPIRED_PATTERNS = [
    r"your\s+session\s+has\s+timed?\s*out",
    r"session\s+(has\s+)?(timed?\s*out|expired)",
    r"your\s+session\s+is\s+(no\s+longer\s+)?valid",
    r"session\s+invalid",
    r"session\s+has\s+expired",
]

_TIMEOUT_PATTERNS = [
    r"timeout",
    r"timed?\s*out",
]

_SELECTOR_DRIFT_PATTERNS = [
    r"selector.*not found",
    r"element.*not found",
    r"waiting for.*failed",
]


def classify_error(exception: BaseException) -> ErrorClass:
    exc_type = type(exception).__name__
    exc_msg = str(exception)

    if "TimeoutError" in exc_type:
        return ErrorClass.TIMEOUT

    if _match_any(exc_msg, _SESSION_EXPIRED_PATTERNS):
        return ErrorClass.SESSION_EXPIRED

    if _match_any(exc_msg, _SELECTOR_DRIFT_PATTERNS):
        return ErrorClass.SELECTOR_DRIFT

    if _match_any(exc_msg, _TIMEOUT_PATTERNS):
        return ErrorClass.TIMEOUT

    status = _extract_http_status(exc_msg)
    if status is not None:
        if status == 429:
            return ErrorClass.HTTP_429
        if 500 <= status < 600:
            return ErrorClass.HTTP_5XX
        if 400 <= status < 500:
            return ErrorClass.HTTP_4XX

    if exc_type in ("ConnectionError", "ConnectionRefusedError", "ConnectionResetError"):
        return ErrorClass.NETWORK_ERROR

    if "net::" in exc_msg.lower() or "connection" in exc_msg.lower():
        return ErrorClass.NETWORK_ERROR

    if "parse" in exc_msg.lower() or "attribute" in exc_msg.lower() or "keyerror" in exc_msg.lower():
        return ErrorClass.PARSE_FAILURE
    if exc_type in ("AttributeError", "KeyError", "IndexError", "TypeError"):
        return ErrorClass.PARSE_FAILURE

    return ErrorClass.UNKNOWN


def get_retry_config(exception: BaseException) -> RetryConfig:
    error_class = classify_error(exception)
    return RETRY_POLICY.get(error_class, RETRY_POLICY[ErrorClass.UNKNOWN])


def is_retryable(exception: BaseException, attempt_count: int) -> bool:
    config = get_retry_config(exception)
    return attempt_count < config.max_attempts


def get_backoff_delay(exception: BaseException, attempt_count: int) -> float:
    config = get_retry_config(exception)
    idx = attempt_count - 1
    if 0 <= idx < len(config.backoff_seconds):
        return config.backoff_seconds[idx]
    return 0.0


def _match_any(message: str, patterns: list[str]) -> bool:
    msg_lower = message.lower()
    return any(re.search(p, msg_lower, re.IGNORECASE) for p in patterns)


def _extract_http_status(message: str) -> int | None:
    m = re.search(r"\b(4\d\d|5\d\d|429)\b", message)
    if m:
        return int(m.group(1))
    return None
