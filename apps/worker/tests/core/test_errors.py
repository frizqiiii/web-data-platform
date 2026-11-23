import pytest
from worker.core.errors import ErrorCategory, is_retryable, is_retryable_http_error


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.DNS_FAILURE,
        ErrorCategory.CONNECTION_TIMEOUT,
        ErrorCategory.READ_TIMEOUT,
        ErrorCategory.CONNECTION_FAILURE,
    ],
)
def test_transient_categories_are_retryable(category: ErrorCategory) -> None:
    assert is_retryable(category) is True


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.VALIDATION_ERROR,
        ErrorCategory.SSRF_BLOCKED,
        ErrorCategory.TLS_FAILURE,
        ErrorCategory.REDIRECT_BLOCKED,
        ErrorCategory.RESPONSE_TOO_LARGE,
        ErrorCategory.BROWSER_FAILURE,
        ErrorCategory.PARSER_FAILURE,
        ErrorCategory.ENGINE_UNSUPPORTED,
        ErrorCategory.CREDENTIAL_UNAVAILABLE,
    ],
)
def test_permanent_categories_are_not_retryable(category: ErrorCategory) -> None:
    assert is_retryable(category) is False


def test_http_error_is_not_classifiable_without_a_status_code() -> None:
    with pytest.raises(ValueError):
        is_retryable(ErrorCategory.HTTP_ERROR)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422, 499])
def test_4xx_http_errors_are_not_retryable(status_code: int) -> None:
    assert is_retryable_http_error(status_code) is False


@pytest.mark.parametrize("status_code", [500, 502, 503, 504, 599])
def test_5xx_http_errors_are_retryable(status_code: int) -> None:
    assert is_retryable_http_error(status_code) is True


@pytest.mark.parametrize("status_code", [100, 200, 301, 600])
def test_non_error_status_codes_are_rejected(status_code: int) -> None:
    with pytest.raises(ValueError):
        is_retryable_http_error(status_code)


def test_every_category_except_http_error_is_classified() -> None:
    """Guards against a future ErrorCategory being added without also
    updating the retryability tables — is_retryable would otherwise
    silently AssertionError only at call time, not at review time."""
    for category in ErrorCategory:
        if category is ErrorCategory.HTTP_ERROR:
            continue
        is_retryable(category)  # must not raise
