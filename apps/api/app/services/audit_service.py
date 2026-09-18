"""Audit logging service (Section 44 / Decision G).

RULE, enforced here at the one place all audit writes go through:
`metadata` must never contain a password, token, or secret. This
module doesn't attempt to scrub arbitrary dicts (that's unreliable);
instead every call site in this codebase is reviewed to only pass
already-safe metadata, and this module's own docstring is the
checklist reviewers use.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record_audit_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    entry = AuditLog(
        action=action,
        user_id=user_id,
        organization_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_=metadata,
    )
    db.add(entry)
    await db.flush()
