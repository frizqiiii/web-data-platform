"""One real, non-mocked integration test: fetch https://example.com/
through the full HTTP engine pipeline (real DNS, real TLS, real
IP-pinning), proving the whole thing actually works end to end, not
just against MockTransport.

Marked `integration` per the project's existing pytest marker
convention (see apps/api/tests/integration/*) — skipped in unit-only
runs, requires real network. Could not be run in the sandbox this was
authored in (no network access). Report this as:

    UNVERIFIED — network unavailable

not PASS, until it is actually run somewhere with network access
(e.g. CI).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from worker.core.execution import ExecutionContext
from worker.engines.http.engine import HttpEngineAdapter


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetches_example_com_end_to_end() -> None:
    adapter = HttpEngineAdapter()
    context = ExecutionContext(
        execution_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        scraper_id=uuid4(),
        target_id=uuid4(),
        scraper_version=1,
        engine="HTTP",
        configuration={},
        url="https://example.com/",
        requested_at=datetime.now(UTC),
        timeout_seconds=30,
    )

    result = await adapter.execute(context)

    assert result.success is True
    assert result.http_status == 200
    assert result.response_size_bytes is not None and result.response_size_bytes > 0
    assert result.safe_response_headers.get("content-type", "").startswith("text/html")
