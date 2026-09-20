"""Target business logic: CRUD + SSRF-safe URL validation.

RULE: every URL passed to create_target/update_target_url MUST go
through app.core.url_safety.validate_target_url before being
persisted (Decision #4 / ADR-006). This is Phase 2's mitigation only
— Phase 3 must re-validate at fetch time and is not entitled to trust
that a URL stored here is still safe later.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_safety import validate_target_url
from app.models.target import Target


async def create_target(
    db: AsyncSession,
    *,
    scraper_id: uuid.UUID,
    url: str,
    name: str | None,
    enabled: bool,
    priority: int,
) -> Target:
    safe_url = validate_target_url(url)  # raises UnsafeURLError -> 422 at the router
    target = Target(
        id=uuid.uuid4(),
        scraper_id=scraper_id,
        url=safe_url,
        name=name,
        enabled=enabled,
        priority=priority,
    )
    db.add(target)
    await db.flush()
    return target


async def list_targets_for_scraper(db: AsyncSession, *, scraper_id: uuid.UUID) -> list[Target]:
    result = await db.scalars(select(Target).where(Target.scraper_id == scraper_id))
    return list(result.all())


def apply_url_update(target: Target, new_url: str) -> None:
    target.url = validate_target_url(new_url)
