import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionContext, ExecutionError, ExecutionResult


def _make_context(**overrides: object) -> ExecutionContext:
    defaults: dict = dict(
        execution_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        scraper_id=uuid4(),
        target_id=uuid4(),
        scraper_version=1,
        engine="HTTP",
        configuration={"timeout_seconds": 30},
        url="https://example.com/",
        requested_at=datetime.now(UTC),
        timeout_seconds=30,
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def test_execution_context_is_frozen() -> None:
    context = _make_context()
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.engine = "BROWSER"  # type: ignore[misc]


def test_execution_context_credential_reference_defaults_to_none() -> None:
    context = _make_context()
    assert context.credential_reference is None


def test_execution_context_accepts_credential_reference() -> None:
    context = _make_context(credential_reference="vault://some-secret")
    assert context.credential_reference == "vault://some-secret"


def test_execution_result_rejects_success_with_error() -> None:
    with pytest.raises(ValueError):
        ExecutionResult(
            success=True,
            engine="HTTP",
            final_url=None,
            http_status=200,
            content_type=None,
            response_size_bytes=0,
            duration_ms=1,
            safe_response_headers={},
            error=ExecutionError(ErrorCategory.HTTP_ERROR, "x", False),
        )


def test_execution_result_rejects_failure_without_error() -> None:
    with pytest.raises(ValueError):
        ExecutionResult(
            success=False,
            engine="HTTP",
            final_url=None,
            http_status=None,
            content_type=None,
            response_size_bytes=None,
            duration_ms=1,
            safe_response_headers={},
            error=None,
        )


def test_execution_result_accepts_consistent_success() -> None:
    result = ExecutionResult(
        success=True,
        engine="HTTP",
        final_url="https://example.com/",
        http_status=200,
        content_type="text/html",
        response_size_bytes=10,
        duration_ms=5,
        safe_response_headers={"content-type": "text/html"},
        error=None,
    )
    assert result.success is True


def test_execution_result_accepts_consistent_failure() -> None:
    result = ExecutionResult(
        success=False,
        engine="HTTP",
        final_url=None,
        http_status=None,
        content_type=None,
        response_size_bytes=None,
        duration_ms=5,
        safe_response_headers={},
        error=ExecutionError(ErrorCategory.SSRF_BLOCKED, "blocked", False),
    )
    assert result.error is not None
    assert result.error.category == ErrorCategory.SSRF_BLOCKED
