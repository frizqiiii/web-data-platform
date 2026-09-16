"""Tests for the /health endpoint.

/health has no dependencies (by design — see app/api/router.py), so
this one IS runnable without Postgres/Redis, once `fastapi` and
`httpx` are installed via `uv sync --group api --group dev`.
"""
import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_available_under_versioned_prefix(client) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
