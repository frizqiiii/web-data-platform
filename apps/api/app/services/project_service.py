"""Project business logic: CRUD + lifecycle state machine.

RULE (Section 13/tenant isolation): every function here that reads or
writes a project takes organization_id from a CALLER-verified source
(app/api/deps.py::require_membership) — never from raw client input.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import PROJECT_STATUS_TRANSITIONS, Project, ProjectStatus


class SlugAlreadyTaken(Exception):
    pass


class InvalidStatusTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"cannot transition project from {current} to {requested}")


async def create_project(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    slug: str,
    description: str | None,
) -> Project:
    existing = await db.scalar(
        select(Project).where(Project.organization_id == organization_id, Project.slug == slug)
    )
    if existing is not None:
        raise SlugAlreadyTaken(slug)

    project = Project(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name=name,
        slug=slug,
        description=description,
        status=ProjectStatus.DRAFT.value,
        created_by=created_by,
    )
    db.add(project)
    await db.flush()
    return project


async def list_projects_for_organization(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> list[Project]:
    result = await db.scalars(select(Project).where(Project.organization_id == organization_id))
    return list(result.all())


def apply_status_transition(project: Project, new_status: str) -> None:
    """Raises InvalidStatusTransition rather than silently mutating —
    callers (the router) turn that into a 409, not a 422, since the
    request body is syntactically valid, just illegal given the
    project's current state."""
    allowed = PROJECT_STATUS_TRANSITIONS.get(project.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransition(project.status, new_status)
    project.status = new_status


def audit_event_for_transition(new_status: str) -> str:
    """Maps a status transition to a specific audit action name
    (Section 13 plan: PROJECT_ACTIVATED/PAUSED/ARCHIVED are distinct
    events, not a generic PROJECT_UPDATED)."""
    return {
        ProjectStatus.ACTIVE.value: "PROJECT_ACTIVATED",
        ProjectStatus.PAUSED.value: "PROJECT_PAUSED",
        ProjectStatus.ARCHIVED.value: "PROJECT_ARCHIVED",
    }.get(new_status, "PROJECT_UPDATED")
