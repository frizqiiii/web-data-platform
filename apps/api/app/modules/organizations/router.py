"""Organization endpoints (Decision I).

Every route here follows the required authorization flow (see
app/api/deps.py's module docstring): authenticated user -> verified
membership -> role check -> the organization row itself is only ever
loaded via that verified membership, never via a bare path parameter.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_current_user, require_csrf, require_membership, require_role
from app.core.database import get_db
from app.models.organization_member import OrganizationMember, OrgRole
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationResponse, OrganizationUpdate
from app.services.audit_service import record_audit_event
from app.services.organization_service import (
    SlugAlreadyTaken,
    create_organization,
    list_organizations_for_user,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])
logger = get_logger()


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationResponse]:
    """Only organizations the caller is actually a member of —
    NEVER all organizations in the system (Section 13)."""
    rows = await list_organizations_for_user(db, user_id=current_user.id)
    return [
        OrganizationResponse(
            id=str(org.id), name=org.name, slug=org.slug, status=org.status, role=role
        )
        for org, role in rows
    ]


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_org(
    payload: OrganizationCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    try:
        org = await create_organization(
            db, owner_user_id=current_user.id, name=payload.name, slug=payload.slug
        )
    except SlugAlreadyTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken") from exc

    await record_audit_event(
        db,
        action="ORGANIZATION_CREATED",
        user_id=current_user.id,
        organization_id=org.id,
        resource_type="organization",
        resource_id=str(org.id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    logger.info("organization_created", organization_id=str(org.id))
    return OrganizationResponse(
        id=str(org.id), name=org.name, slug=org.slug, status=org.status, role=OrgRole.OWNER.value
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    membership: OrganizationMember = Depends(require_membership),
) -> OrganizationResponse:
    """require_membership already returns 404 for non-members
    (Section 12 IDOR mitigation) — by the time we're here, the
    caller's membership is verified."""
    org = membership.organization
    return OrganizationResponse(
        id=str(org.id), name=org.name, slug=org.slug, status=org.status, role=membership.role
    )


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    membership: OrganizationMember = Depends(require_role(OrgRole.ADMIN.value)),
    _csrf: None = Depends(require_csrf),
) -> OrganizationResponse:
    org = membership.organization
    if payload.name is not None:
        org.name = payload.name
    await db.flush()

    await record_audit_event(
        db,
        action="ORGANIZATION_UPDATED",
        user_id=membership.user_id,
        organization_id=organization_id,
        resource_type="organization",
        resource_id=str(organization_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return OrganizationResponse(
        id=str(org.id), name=org.name, slug=org.slug, status=org.status, role=membership.role
    )
