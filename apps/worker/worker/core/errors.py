"""Execution error taxonomy (Phase 3).

`ErrorCategory` is the closed set of ways an engine execution can
fail. Retryability is a property OF the category, not something each
call site decides ad hoc — see `is_retryable`. This is deliberately
NOT retry orchestration (no backoff, no attempt counting, no queue
requeue logic): that is Phase 4/5's job. This module only answers
"if something retries this later, would that be a reasonable thing
to do for this specific failure" — a classification, not a policy.
"""

from enum import StrEnum


class ErrorCategory(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    DNS_FAILURE = "DNS_FAILURE"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    READ_TIMEOUT = "READ_TIMEOUT"
    TLS_FAILURE = "TLS_FAILURE"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    HTTP_ERROR = "HTTP_ERROR"
    REDIRECT_BLOCKED = "REDIRECT_BLOCKED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    BROWSER_FAILURE = "BROWSER_FAILURE"
    PARSER_FAILURE = "PARSER_FAILURE"
    ENGINE_UNSUPPORTED = "ENGINE_UNSUPPORTED"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"


# Categories that are never retryable regardless of any HTTP status
# involved — the failure is about the request itself (bad input, a
# security boundary, a policy decision), not a transient condition.
_NEVER_RETRYABLE = {
    ErrorCategory.VALIDATION_ERROR,
    ErrorCategory.SSRF_BLOCKED,
    ErrorCategory.TLS_FAILURE,
    ErrorCategory.REDIRECT_BLOCKED,
    ErrorCategory.RESPONSE_TOO_LARGE,
    ErrorCategory.BROWSER_FAILURE,
    ErrorCategory.PARSER_FAILURE,
    ErrorCategory.ENGINE_UNSUPPORTED,
    ErrorCategory.CREDENTIAL_UNAVAILABLE,
}

# Categories that are always retryable — transient network/DNS
# conditions where a later attempt might succeed.
_ALWAYS_RETRYABLE = {
    ErrorCategory.DNS_FAILURE,
    ErrorCategory.CONNECTION_TIMEOUT,
    ErrorCategory.READ_TIMEOUT,
    ErrorCategory.CONNECTION_FAILURE,
}

# HTTP_ERROR's retryability depends on the actual status code (4xx vs
# 5xx), so it is intentionally excluded from both sets above — see
# `is_retryable_http_error`.


def is_retryable(category: ErrorCategory) -> bool:
    """Whether a failure in this category is, in principle, worth
    retrying later. Does not apply to HTTP_ERROR — use
    `is_retryable_http_error` for that one, since its retryability
    depends on the specific status code, not just the category.
    """
    if category == ErrorCategory.HTTP_ERROR:
        raise ValueError(
            "HTTP_ERROR retryability depends on the status code — "
            "use is_retryable_http_error(status_code) instead"
        )
    if category in _ALWAYS_RETRYABLE:
        return True
    if category in _NEVER_RETRYABLE:
        return False
    raise AssertionError(f"unclassified ErrorCategory: {category!r}")  # pragma: no cover


def is_retryable_http_error(status_code: int) -> bool:
    """HTTP_ERROR retryability: 5xx (server-side) is retryable, 4xx
    (client-side — the request itself was rejected) is not. Anything
    outside 400-599 reaching here would be a caller bug, not a valid
    HTTP_ERROR classification."""
    if 400 <= status_code < 500:
        return False
    if 500 <= status_code < 600:
        return True
    raise ValueError(f"not a 4xx/5xx status code: {status_code}")
