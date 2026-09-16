"""Integration test — requires a REAL PostgreSQL instance.

Status in this repository as authored: BLOCKED (environment). The
sandbox this code was written in has no Docker daemon, no live
Postgres, and no network access — this test could not be executed
here, and that is stated rather than hidden.

Run it for real via:

    docker compose up -d postgres
    export DATABASE_URL=postgresql+asyncpg://platform:platform@localhost:5432/platform
    export REDIS_URL=redis://localhost:6379/0
    uv run pytest apps/api/tests/integration -m integration -v
"""
import pytest

from app.core.database import check_database_connection

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_database_connection_succeeds() -> None:
    assert await check_database_connection() is True
