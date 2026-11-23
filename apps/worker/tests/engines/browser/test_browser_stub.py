from datetime import UTC, datetime
from uuid import uuid4

import pytest
from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionContext
from worker.engines.browser.engine import BrowserEngineAdapter


def _context() -> ExecutionContext:
    return ExecutionContext(
        execution_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        scraper_id=uuid4(),
        target_id=uuid4(),
        scraper_version=1,
        engine="BROWSER",
        configuration={},
        url="https://example.com/",
        requested_at=datetime.now(UTC),
        timeout_seconds=60,
    )


@pytest.mark.asyncio
async def test_browser_adapter_returns_engine_unsupported() -> None:
    adapter = BrowserEngineAdapter()
    result = await adapter.execute(_context())
    assert result.success is False
    assert result.error is not None
    assert result.error.category == ErrorCategory.ENGINE_UNSUPPORTED
    assert result.error.retryable is False
    assert result.engine == "BROWSER"


@pytest.mark.asyncio
async def test_browser_adapter_never_raises() -> None:
    adapter = BrowserEngineAdapter()
    # Should complete normally, not raise, regardless of context contents.
    result = await adapter.execute(_context())
    assert result is not None
