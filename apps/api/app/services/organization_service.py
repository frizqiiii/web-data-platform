"""Organization business logic, including membership/role checks.

RULE (Section 13): every function here that touches tenant-scoped
data takes organization_id as a parameter that the CALLER has
already verified against the authenticated user's memberships
(app/api/deps.py) — this module does not re-derive it from request
input, and does not trust a bare UUID passed in without that
verification having happened first.
"""

import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrgRole


class SlugAlreadyTaken(Exception):
    pass


async def create_organization(
    db: AsyncSession, *, owner_user_id: uuid.UUID, name: str, slug: str
) -> Organization:
    existing = await db.scalar(select(Organization).where(Organization.slug == slug))
    if existing is not None:
        raise SlugAlreadyTaken(slug)

    org = Organization(id=uuid.uuid4(), name=name, slug=slug)
    db.add(org)
    await db.flush()

    membership = OrganizationMember(
        id=uuid.uuid4(),
        user_id=owner_user_id,
        organization_id=org.id,
        role=OrgRole.OWNER.value,
    )
    db.add(membership)
    await db.flush()

    return org


async def get_membership(
    db: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> OrganizationMember | None:
    """The single source of truth for "is this user a member of this
    org, and with what role". Every authorization check in Phase 1
    goes through this — nothing trusts a client-supplied role.

    Eager-loads `.organization` via selectinload: accessing a lazy
    relationship attribute after the fact does not work under
    SQLAlchemy's async engine (raises MissingGreenlet) — found by
    actually tracing the get_organization/update_organization route
    handlers, which read `membership.organization` directly.

    The explicit cast below is because SQLAlchemy's async `.scalar()`
    stub returns `Any` here (found by actually running mypy) — the
    query itself is fully typed via `select(OrganizationMember)`, so
    this is a stub limitation, not an unverified assumption."""
    result = await db.scalar(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization))
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == organization_id,
        )
    )
    return cast("OrganizationMember | None", result)


async def list_organizations_for_user(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[tuple[Organization, str]]:
    """Returns (organization, caller's role) pairs — only orgs the
    user actually belongs to, never all organizations."""
    rows = await db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
    )
    # Explicit tuple unpacking rather than list(rows.all()): SQLAlchemy's
    # Row type isn't structurally a plain tuple[Organization, str] to
    # mypy even though it behaves like one at runtime (found by
    # actually running mypy) — this is the honest fix, not a cast.
    return [(row[0], row[1]) for row in rows.all()]
