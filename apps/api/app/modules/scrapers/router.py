"""Scraper endpoints.

Two routers in this module: `project_scrapers_router` (nested under
a project, for create/list — mirrors the approved API contract's
`/projects/{project_id}/scrapers`) and `router` (flat `/scrapers/{id}`
for get/update/archive, since a scraper ID alone is enough to resolve
its project/org via require_scraper).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_current_user, require_csrf, require_project_role, require_scraper_role
from app.core.database import get_db
from app.models.organization_member import OrgRole
from app.models.project import Project
from app.models.scraper import Scraper
from app.models.user import User
from app.schemas.scraper import ScraperCreate, ScraperResponse, ScraperUpdate
from app.services.audit_service import record_audit_event
from app.services.scraper_service import (
    InvalidStatusTransition,
    SlugAlreadyTaken,
    apply_configuration_update,
    apply_status_transition,
    audit_event_for_transition,
    create_scraper,
    list_scrapers_for_project,
)

project_scrapers_router = APIRouter(prefix="/projects/{project_id}/scrapers", tags=["scrapers"])
router = APIRouter(prefix="/scrapers", tags=["scrapers"])
logger = get_logger()


def _to_response(scraper: Scraper) -> ScraperResponse:
    return ScraperResponse(
        id=str(scraper.id),
        project_id=str(scraper.project_id),
        name=scraper.name,
        slug=scraper.slug,
        engine=scraper.engine,
        configuration=scraper.configuration,
        credential_reference=scraper.credential_reference,
        status=scraper.status,
        version=scraper.version,
    )


@project_scrapers_router.get("", response_model=list[ScraperResponse])
async def list_scrapers(
    project: Project = Depends(require_project_role(OrgRole.VIEWER.value)),
    db: AsyncSession = Depends(get_db),
) -> list[ScraperResponse]:
    scrapers = await list_scrapers_for_project(db, project_id=project.id)
    return [_to_response(s) for s in scrapers]


@project_scrapers_router.post(
    "",
    response_model=ScraperResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_scraper_endpoint(
    payload: ScraperCreate,
    request: Request,
    project: Project = Depends(require_project_role(OrgRole.MANAGER.value)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScraperResponse:
    configuration_dict = (
        payload.configuration.model_dump(mode="json") if payload.configuration else None
    )
    try:
        scraper = await create_scraper(
            db,
            project_id=project.id,
            created_by=current_user.id,
            name=payload.name,
            slug=payload.slug,
            engine=payload.engine.value,
            configuration=configuration_dict,
            credential_reference=payload.credential_reference,
        )
    except SlugAlreadyTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken") from exc

    # NOTE: credential_reference (a name/identifier only, never a
    # secret) is fine to audit. `configuration` itself is NOT written
    # to the audit metadata — a caller could put something that looks
    # like a secret in an unexpected config field, and this codebase
    # has no way to tell (Decision #2's mitigation: never log/audit
    # configuration payloads wholesale).
    await record_audit_event(
        db,
        action="SCRAPER_CREATED",
        organization_id=project.organization_id,
        resource_type="scraper",
        resource_id=str(scraper.id),
        ip_address=request.client.host if request.client else None,
        metadata={"engine": scraper.engine},
    )
    await db.commit()
    logger.info("scraper_created", scraper_id=str(scraper.id))
    return _to_response(scraper)


@router.get("/{scraper_id}", response_model=ScraperResponse)
async def get_scraper(
    scraper: Scraper = Depends(require_scraper_role(OrgRole.VIEWER.value)),
) -> ScraperResponse:
    return _to_response(scraper)


@router.patch("/{scraper_id}", response_model=ScraperResponse)
async def update_scraper(
    scraper_id: uuid.UUID,
    payload: ScraperUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scraper: Scraper = Depends(require_scraper_role(OrgRole.MANAGER.value)),
    _csrf: None = Depends(require_csrf),
) -> ScraperResponse:
    if payload.name is not None:
        scraper.name = payload.name
    if payload.credential_reference is not None:
        scraper.credential_reference = payload.credential_reference

    audit_action = "SCRAPER_UPDATED"

    if payload.configuration is not None:
        apply_configuration_update(scraper, payload.configuration.model_dump(mode="json"))
        audit_action = "SCRAPER_CONFIGURATION_CHANGED"

    if payload.status is not None:
        try:
            apply_status_transition(scraper, payload.status.value)
        except InvalidStatusTransition as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        audit_action = audit_event_for_transition(payload.status.value)

    await db.flush()
    await record_audit_event(
        db,
        action=audit_action,
        resource_type="scraper",
        resource_id=str(scraper_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_response(scraper)


@router.delete("/{scraper_id}", response_model=ScraperResponse)
async def archive_scraper(
    scraper_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    scraper: Scraper = Depends(require_scraper_role(OrgRole.ADMIN.value)),
    _csrf: None = Depends(require_csrf),
) -> ScraperResponse:
    """Soft delete, same rationale as project archiving."""
    try:
        apply_status_transition(scraper, "ARCHIVED")
    except InvalidStatusTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await db.flush()
    await record_audit_event(
        db,
        action="SCRAPER_ARCHIVED",
        resource_type="scraper",
        resource_id=str(scraper_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_response(scraper)
