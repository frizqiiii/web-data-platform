"""Top-level API router.

Phase 0 scope: /health and /ready only, exposed both at the root
(for infra probes, Section 40) and under /api/v1 (Section 9 contract).
Domain routers (auth, organizations, projects, ...) are mounted here
starting Phase 1 — this file stays this small until then.
"""
from fastapi import APIRouter

from app.core.database import check_database_connection

router = APIRouter()


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness probe: process is up. Deliberately does not check
    dependencies — that's what /ready is for."""
    return {"status": "ok"}


@router.get("/ready", tags=["system"])
async def ready() -> dict[str, object]:
    """Readiness probe: process can actually serve traffic."""
    db_ok = await check_database_connection()
    overall = "ok" if db_ok else "degraded"
    return {"status": overall, "checks": {"database": db_ok}}
