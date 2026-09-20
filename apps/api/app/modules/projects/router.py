"""Project endpoints.

`organization_id` is a required QUERY parameter on `POST`/`GET
/projects` (not a body field) — this lets `require_role`/
`require_membership` (from Phase 1, unmodified) be reused directly:
FastAPI treats a dependency's plain-typed parameter as a query
parameter automatically when it doesn't appear in the route's path
template. No new tenant-check code was needed for these two routes.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import require_csrf, require_membership, require_project_role
from app.core.database import get_db
from app.core.rbac import role_satisfies
from app.models.organization_member import OrganizationMember, OrgRole
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.audit_service import record_audit_event
from app.services.project_service import (
    InvalidStatusTransition,
    SlugAlreadyTaken,
    apply_status_transition,
    audit_event_for_transition,
    create_project,
    list_projects_for_organization,
)

router = APIRouter(prefix="/projects", tags=["projects"])
logger = get_logger()


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=str(project.id),
        organization_id=str(project.organization_id),
        name=project.name,
        slug=project.slug,
        description=project.description,
        status=project.status,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    membership: OrganizationMember = Depends(require_membership),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    projects = await list_projects_for_organization(db, organization_id=membership.organization_id)
    return [_to_response(p) for p in projects]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_project_endpoint(
    payload: ProjectCreate,
    request: Request,
    membership: OrganizationMember = Depends(require_membership),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    if not role_satisfies(membership.role, OrgRole.MANAGER.value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")

    try:
        project = await create_project(
            db,
            organization_id=membership.organization_id,
            created_by=membership.user_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
        )
    except SlugAlreadyTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken") from exc

    await record_audit_event(
        db,
        action="PROJECT_CREATED",
        user_id=membership.user_id,
        organization_id=project.organization_id,
        resource_type="project",
        resource_id=str(project.id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    logger.info("project_created", project_id=str(project.id))
    return _to_response(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project: Project = Depends(require_project_role(OrgRole.VIEWER.value)),
) -> ProjectResponse:
    return _to_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(require_project_role(OrgRole.MANAGER.value)),
    _csrf: None = Depends(require_csrf),
) -> ProjectResponse:
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description

    audit_action = "PROJECT_UPDATED"
    if payload.status is not None:
        try:
            apply_status_transition(project, payload.status.value)
        except InvalidStatusTransition as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        audit_action = audit_event_for_transition(payload.status.value)

    await db.flush()
    await record_audit_event(
        db,
        action=audit_action,
        organization_id=project.organization_id,
        resource_type="project",
        resource_id=str(project_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_response(project)


@router.delete("/{project_id}", response_model=ProjectResponse)
async def archive_project(
    project_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(require_project_role(OrgRole.ADMIN.value)),
    _csrf: None = Depends(require_csrf),
) -> ProjectResponse:
    """Soft delete: transitions to ARCHIVED, never removes the row
    (Decision recorded in the Phase 2 plan — archiving preserves audit
    trail integrity; a real DELETE would orphan audit_logs rows that
    reference this project)."""
    try:
        apply_status_transition(project, "ARCHIVED")
    except InvalidStatusTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await db.flush()
    await record_audit_event(
        db,
        action="PROJECT_ARCHIVED",
        organization_id=project.organization_id,
        resource_type="project",
        resource_id=str(project_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_response(project)
