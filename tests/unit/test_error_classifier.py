from __future__ import annotations

from tender_royal_pulse.crawler.retry import ErrorClass, classify_error


class _FakePlaywrightTimeoutError(Exception):
    pass


class _FakePlaywrightError(Exception):
    pass


class _FakeConnectionError(Exception):
    pass


class TestTimeoutErrors:
    def test_playwright_timeouterror_classified_as_timeout(self) -> None:
        exc = _FakePlaywrightTimeoutError("Timeout 30000ms exceeded")
        result = classify_error(exc)
        assert result == ErrorClass.TIMEOUT

    def test_playwright_generic_error_with_timeout_message(self) -> None:
        exc = _FakePlaywrightError("page.waitForSelector: Timeout 30000ms exceeded")
        result = classify_error(exc)
        assert result == ErrorClass.TIMEOUT

    def test_timeout_in_message_triggers_timeout(self) -> None:
        exc = Exception("Request timed out after 30 seconds")
        result = classify_error(exc)
        assert result == ErrorClass.TIMEOUT


class TestSessionExpiredErrors:
    def test_session_has_timed_out(self) -> None:
        exc = Exception("Your session has timed out. Please login again.")
        result = classify_error(exc)
        assert result == ErrorClass.SESSION_EXPIRED

    def test_session_expired_variant(self) -> None:
        exc = Exception("Your session has expired")
        result = classify_error(exc)
        assert result == ErrorClass.SESSION_EXPIRED

    def test_generic_session_invalid_message(self) -> None:
        exc = Exception("Session invalid. Redirecting to login.")
        result = classify_error(exc)
        assert result == ErrorClass.SESSION_EXPIRED

    def test_your_session_message(self) -> None:
        exc = Exception("Your session is no longer valid")
        result = classify_error(exc)
        assert result == ErrorClass.SESSION_EXPIRED


class TestHTTPStatusErrors:
    def test_http_429_too_many_requests(self) -> None:
        exc = Exception("HTTP 429 Too Many Requests")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_429

    def test_http_500_internal_server_error(self) -> None:
        exc = Exception("Server returned 500 Internal Server Error")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_5XX

    def test_http_503_service_unavailable(self) -> None:
        exc = Exception("HTTP 503 Service Unavailable")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_5XX

    def test_http_401_unauthorized(self) -> None:
        exc = Exception("401 Unauthorized")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_4XX

    def test_http_403_forbidden(self) -> None:
        exc = Exception("403 Forbidden")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_4XX

    def test_http_404_not_found(self) -> None:
        exc = Exception("404 Not Found")
        result = classify_error(exc)
        assert result == ErrorClass.HTTP_4XX


class TestSelectorDriftErrors:
    def test_playwright_selector_not_found(self) -> None:
        exc = _FakePlaywrightError("selector 'table.list_table' not found")
        result = classify_error(exc)
        assert result == ErrorClass.SELECTOR_DRIFT

    def test_playwright_element_not_found(self) -> None:
        exc = _FakePlaywrightError("element not found in the page")
        result = classify_error(exc)
        assert result == ErrorClass.SELECTOR_DRIFT

    def test_waiting_for_selector_failed(self) -> None:
        exc = _FakePlaywrightError("waiting for selector 'td.page_content' failed")
        result = classify_error(exc)
        assert result == ErrorClass.SELECTOR_DRIFT


class TestNetworkErrors:
    def test_connection_error(self) -> None:
        exc = ConnectionError("Connection refused")
        result = classify_error(exc)
        assert result == ErrorClass.NETWORK_ERROR

    def test_connection_refused_error(self) -> None:
        exc = ConnectionRefusedError("Connection refused")
        result = classify_error(exc)
        assert result == ErrorClass.NETWORK_ERROR

    def test_connection_reset_error(self) -> None:
        exc = ConnectionResetError("Connection reset by peer")
        result = classify_error(exc)
        assert result == ErrorClass.NETWORK_ERROR

    def test_net_error_in_message(self) -> None:
        exc = Exception("net::ERR_CONNECTION_REFUSED")
        result = classify_error(exc)
        assert result == ErrorClass.NETWORK_ERROR

    def test_connection_in_message(self) -> None:
        exc = Exception("Failed to establish connection")
        result = classify_error(exc)
        assert result == ErrorClass.NETWORK_ERROR


class TestParseFailureErrors:
    def test_attribute_error(self) -> None:
        exc = AttributeError("'NoneType' object has no attribute 'inner_text'")
        result = classify_error(exc)
        assert result == ErrorClass.PARSE_FAILURE

    def test_key_error(self) -> None:
        exc = KeyError("tender_id")
        result = classify_error(exc)
        assert result == ErrorClass.PARSE_FAILURE

    def test_index_error(self) -> None:
        exc = IndexError("list index out of range")
        result = classify_error(exc)
        assert result == ErrorClass.PARSE_FAILURE

    def test_type_error(self) -> None:
        exc = TypeError("unsupported operand type(s)")
        result = classify_error(exc)
        assert result == ErrorClass.PARSE_FAILURE

    def test_parse_in_message(self) -> None:
        exc = Exception("Failed to parse tender data")
        result = classify_error(exc)
        assert result == ErrorClass.PARSE_FAILURE


class TestUnknownFallback:
    def test_generic_runtime_error(self) -> None:
        exc = RuntimeError("Something unexpected happened")
        result = classify_error(exc)
        assert result == ErrorClass.UNKNOWN

    def test_empty_exception(self) -> None:
        exc = Exception("")
        result = classify_error(exc)
        assert result == ErrorClass.UNKNOWN
