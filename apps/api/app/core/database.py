"""Database engine and session management.

Phase 0 scope: connection plumbing and a health check only. No
domain models/tables exist yet — those start in Phase 1.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    str(settings.database_url),
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Not wired into any route yet (no domain
    routes exist in Phase 0) but present so Phase 1 modules have a
    consistent session pattern from day one."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_connection() -> bool:
    """Used by /ready. Returns False rather than raising so the
    readiness endpoint can report degraded status instead of the
    process crashing on a transient DB blip."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
