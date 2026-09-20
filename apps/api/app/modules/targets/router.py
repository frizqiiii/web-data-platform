"""Target endpoints.

`POST/GET /scrapers/{scraper_id}/targets` (nested) and
`PATCH/DELETE /targets/{id}` (flat) — same two-router pattern as
scrapers. `url` is SSRF-validated in the service layer
(app/services/target_service.py) — a rejected URL surfaces here as
422, via UnsafeURLError.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import require_csrf, require_scraper_role, require_target_role
from app.core.database import get_db
from app.core.url_safety import UnsafeURLError
from app.models.organization_member import OrgRole
from app.models.scraper import Scraper
from app.models.target import Target
from app.schemas.target import TargetCreate, TargetResponse, TargetUpdate
from app.services.audit_service import record_audit_event
from app.services.target_service import (
    apply_url_update,
    create_target,
    list_targets_for_scraper,
)

scraper_targets_router = APIRouter(prefix="/scrapers/{scraper_id}/targets", tags=["targets"])
router = APIRouter(prefix="/targets", tags=["targets"])
logger = get_logger()


def _to_response(target: Target) -> TargetResponse:
    return TargetResponse(
        id=str(target.id),
        scraper_id=str(target.scraper_id),
        url=target.url,
        name=target.name,
        enabled=target.enabled,
        priority=target.priority,
    )


@scraper_targets_router.get("", response_model=list[TargetResponse])
async def list_targets(
    scraper: Scraper = Depends(require_scraper_role(OrgRole.VIEWER.value)),
    db: AsyncSession = Depends(get_db),
) -> list[TargetResponse]:
    targets = await list_targets_for_scraper(db, scraper_id=scraper.id)
    return [_to_response(t) for t in targets]


@scraper_targets_router.post(
    "",
    response_model=TargetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_target_endpoint(
    payload: TargetCreate,
    request: Request,
    scraper: Scraper = Depends(require_scraper_role(OrgRole.MANAGER.value)),
    db: AsyncSession = Depends(get_db),
) -> TargetResponse:
    try:
        target = await create_target(
            db,
            scraper_id=scraper.id,
            url=payload.url,
            name=payload.name,
            enabled=payload.enabled,
            priority=payload.priority,
        )
    except UnsafeURLError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    await record_audit_event(
        db,
        action="TARGET_CREATED",
        resource_type="target",
        resource_id=str(target.id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    logger.info("target_created", target_id=str(target.id))
    return _to_response(target)


@router.patch("/{target_id}", response_model=TargetResponse)
async def update_target(
    target_id: uuid.UUID,
    payload: TargetUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    target: Target = Depends(require_target_role(OrgRole.MANAGER.value)),
    _csrf: None = Depends(require_csrf),
) -> TargetResponse:
    if payload.url is not None:
        try:
            apply_url_update(target, payload.url)
        except UnsafeURLError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if payload.name is not None:
        target.name = payload.name
    if payload.enabled is not None:
        target.enabled = payload.enabled
    if payload.priority is not None:
        target.priority = payload.priority

    await db.flush()
    await record_audit_event(
        db,
        action="TARGET_UPDATED",
        resource_type="target",
        resource_id=str(target_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_response(target)


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    target: Target = Depends(require_target_role(OrgRole.MANAGER.value)),
    _csrf: None = Depends(require_csrf),
) -> None:
    """Hard delete — unlike Project/Scraper, a Target has no
    independent audit-trail significance once removed (per the Phase
    2 plan: targets follow their parent scraper, no separate
    lifecycle state machine)."""
    await record_audit_event(
        db,
        action="TARGET_DELETED",
        resource_type="target",
        resource_id=str(target_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.delete(target)
    await db.commit()
