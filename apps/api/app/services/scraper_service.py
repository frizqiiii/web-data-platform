"""Scraper business logic: CRUD + lifecycle state machine.

RULE: every function here takes project_id from a caller-verified
source (app/api/deps.py::require_project) — tenant ownership of a
scraper is always via its parent project, never a column checked
directly against client input.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scraper import SCRAPER_STATUS_TRANSITIONS, Scraper, ScraperStatus
from app.schemas.scraper_configuration import default_configuration_for_engine


class SlugAlreadyTaken(Exception):
    pass


class InvalidStatusTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"cannot transition scraper from {current} to {requested}")


async def create_scraper(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    slug: str,
    engine: str,
    configuration: dict | None,
    credential_reference: str | None,
) -> Scraper:
    existing = await db.scalar(
        select(Scraper).where(Scraper.project_id == project_id, Scraper.slug == slug)
    )
    if existing is not None:
        raise SlugAlreadyTaken(slug)

    scraper = Scraper(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        slug=slug,
        engine=engine,
        configuration=configuration or default_configuration_for_engine(engine),
        credential_reference=credential_reference,
        status=ScraperStatus.DRAFT.value,
        version=1,
        created_by=created_by,
    )
    db.add(scraper)
    await db.flush()
    return scraper


async def list_scrapers_for_project(db: AsyncSession, *, project_id: uuid.UUID) -> list[Scraper]:
    result = await db.scalars(select(Scraper).where(Scraper.project_id == project_id))
    return list(result.all())


def apply_configuration_update(scraper: Scraper, new_configuration: dict) -> None:
    """Any configuration change bumps `version` (optimistic
    concurrency marker, not a full history — see ADR-005)."""
    scraper.configuration = new_configuration
    scraper.version += 1


def apply_status_transition(scraper: Scraper, new_status: str) -> None:
    allowed = SCRAPER_STATUS_TRANSITIONS.get(scraper.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransition(scraper.status, new_status)
    scraper.status = new_status


def audit_event_for_transition(new_status: str) -> str:
    return {
        ScraperStatus.ACTIVE.value: "SCRAPER_ENABLED",
        ScraperStatus.DISABLED.value: "SCRAPER_DISABLED",
        ScraperStatus.ARCHIVED.value: "SCRAPER_ARCHIVED",
    }.get(new_status, "SCRAPER_UPDATED")
