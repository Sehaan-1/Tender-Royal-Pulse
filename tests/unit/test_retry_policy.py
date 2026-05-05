from __future__ import annotations

from tender_royal_pulse.crawler.retry import (
    RETRY_POLICY,
    ErrorClass,
    RetryConfig,
    classify_error,
    get_backoff_delay,
    get_retry_config,
    is_retryable,
)


class TestRetryPolicyMap:
    def test_all_error_classes_have_policy(self) -> None:
        for ec in ErrorClass:
            assert ec in RETRY_POLICY, f"Missing policy for {ec}"

    def test_timeout_policy(self) -> None:
        config = RETRY_POLICY[ErrorClass.TIMEOUT]
        assert config.max_attempts == 3
        assert len(config.backoff_seconds) == 3
        assert config.backoff_seconds == [1.0, 2.0, 4.0]

    def test_http_429_policy_has_longer_backoff(self) -> None:
        config = RETRY_POLICY[ErrorClass.HTTP_429]
        assert config.max_attempts == 3
        assert config.backoff_seconds[0] >= 5.0

    def test_http_4xx_is_not_retryable(self) -> None:
        config = RETRY_POLICY[ErrorClass.HTTP_4XX]
        assert config.max_attempts == 1

    def test_selector_drift_is_not_retryable(self) -> None:
        config = RETRY_POLICY[ErrorClass.SELECTOR_DRIFT]
        assert config.max_attempts == 1

    def test_session_expired_has_limited_retries(self) -> None:
        config = RETRY_POLICY[ErrorClass.SESSION_EXPIRED]
        assert config.max_attempts == 2

    def test_parse_failure_has_limited_retries(self) -> None:
        config = RETRY_POLICY[ErrorClass.PARSE_FAILURE]
        assert config.max_attempts == 2


class TestIsRetryable:
    def test_timeout_is_retryable_on_first_attempt(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        assert is_retryable(exc, 1) is True

    def test_timeout_not_retryable_on_third_attempt(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        assert is_retryable(exc, 3) is False

    def test_http_4xx_not_retryable(self) -> None:
        exc = Exception("401 Unauthorized")
        assert is_retryable(exc, 1) is False

    def test_selector_drift_not_retryable(self) -> None:
        exc = Exception("selector not found")
        assert is_retryable(exc, 1) is False

    def test_session_expired_retryable_on_first(self) -> None:
        exc = Exception("Your session has timed out")
        assert is_retryable(exc, 1) is True

    def test_session_expired_not_retryable_on_second(self) -> None:
        exc = Exception("Your session has timed out")
        assert is_retryable(exc, 2) is False


class TestGetRetryConfig:
    def test_returns_config_for_timeout(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        config = get_retry_config(exc)
        assert isinstance(config, RetryConfig)
        assert config.max_attempts == 3

    def test_returns_config_for_unknown(self) -> None:
        exc = Exception("Something strange happened")
        config = get_retry_config(exc)
        assert isinstance(config, RetryConfig)
        assert config.max_attempts == 2


class TestGetBackoffDelay:
    def test_timeout_first_attempt_backoff(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        delay = get_backoff_delay(exc, 1)
        assert delay == 1.0

    def test_timeout_second_attempt_backoff(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        delay = get_backoff_delay(exc, 2)
        assert delay == 2.0

    def test_timeout_third_attempt_backoff(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        delay = get_backoff_delay(exc, 3)
        assert delay == 4.0

    def test_http_429_first_attempt_backoff_longer(self) -> None:
        exc = Exception("429 Too Many Requests")
        delay = get_backoff_delay(exc, 1)
        assert delay == 5.0

    def test_non_retryable_returns_zero(self) -> None:
        exc = Exception("401 Unauthorized")
        delay = get_backoff_delay(exc, 1)
        assert delay == 0.0

    def test_out_of_range_attempt_returns_zero(self) -> None:
        exc = Exception("Timeout 30000ms exceeded")
        delay = get_backoff_delay(exc, 10)
        assert delay == 0.0


class TestSessionExpiredRetryThroughClassifier:
    def test_session_expired_page_triggers_correct_class(self) -> None:
        exc = Exception("Your session has timed out. Please login again.")
        assert classify_error(exc) == ErrorClass.SESSION_EXPIRED

    def test_session_expired_is_retryable_once(self) -> None:
        exc = Exception("Your session has timed out. Please login again.")
        assert is_retryable(exc, 1) is True
        assert is_retryable(exc, 2) is False
