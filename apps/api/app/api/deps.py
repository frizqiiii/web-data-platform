"""Shared FastAPI dependencies: authentication, CSRF, and RBAC/tenant
enforcement.

This is where the authorization flow required by Decision D/E lives,
in this exact order, for every protected endpoint:

    Authenticated User
    -> Verified Session
    -> Verified Organization Membership
    -> Verified Permission / Role
    -> Verified Resource Ownership
    -> Operation

`organization_id` in a URL path is NEVER trusted for authorization by
itself — `require_membership` below always re-derives the caller's
role from a verified DB lookup keyed by (current_user.id,
organization_id), never from anything the client asserts.
"""

import uuid
from typing import cast

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import CSRF_HEADER_NAME
from app.core.database import get_db
from app.core.rbac import role_satisfies
from app.core.redis_client import get_redis_client
from app.core.sessions import AsyncKeyValueStore, SessionStore
from app.models.organization_member import OrganizationMember
from app.models.user import User, UserStatus
from app.services.organization_service import get_membership

ACCESS_COOKIE_NAME = "session_token"
REFRESH_COOKIE_NAME = "refresh_token"


def get_session_store() -> SessionStore:
    # redis.asyncio.Redis genuinely has async get/set/delete/sadd/
    # smembers/expire methods and behaves correctly for every call
    # SessionStore makes — verified by reading redis-py's source, not
    # by mypy's structural check, which is stricter than necessary
    # here (its stubs model overload/pipeline variants and broader
    # key/value types — e.g. bytes|str|memoryview — that this minimal
    # Protocol deliberately doesn't need to represent, Section 1.6).
    # Found by actually running mypy; this cast is the documented,
    # reviewed alternative to inflating the Protocol to match redis-py's
    # full stub surface for no functional benefit.
    return SessionStore(cast(AsyncKeyValueStore, get_redis_client()))


async def get_current_user(
    session_store: SessionStore = Depends(get_session_store),
    db: AsyncSession = Depends(get_db),
    session_token_cookie: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
    authorization: str | None = Header(default=None),
) -> User:
    """Resolves the caller from EITHER the httpOnly session cookie
    (browser/dashboard, Decision C) OR a Bearer token (non-browser API
    consumers) — both are the exact same opaque access token under
    the hood, just carried differently."""
    token = session_token_cookie
    if token is None and authorization is not None and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user_id = await session_store.get_user_id_for_access_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active or user.status != UserStatus.ACTIVE.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is not active")

    return user


async def require_csrf(
    session_store: SessionStore = Depends(get_session_store),
    session_token_cookie: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER_NAME),
    csrf_cookie: str | None = Cookie(default=None, alias="csrf_token"),
) -> None:
    """Applied to every state-changing (POST/PATCH/DELETE) endpoint
    reachable via cookie auth. A Bearer-token-only request (no
    session cookie present) is exempt — CSRF is a cookie-specific
    threat (Decision C's rationale)."""
    if session_token_cookie is None:
        return  # Bearer-token API consumer, not a cookie-based browser session

    expected = await session_store.get_csrf_token_for_access_token(session_token_cookie)
    if not expected or not csrf_cookie or not csrf_header:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
    if csrf_cookie != csrf_header or csrf_cookie != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


async def require_membership(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationMember:
    """Step 2-3 of the authorization flow: is the authenticated user
    actually a member of this organization? Returns the verified
    membership row (with its DB-sourced role) — never trust a role
    the client claims to have."""
    membership = await get_membership(db, user_id=current_user.id, organization_id=organization_id)
    if membership is None:
        # 404, not 403: don't reveal whether the org exists to a
        # non-member (Section 12/IDOR mitigation).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return membership


def require_role(minimum_role: str):
    """Dependency factory: require_role(OrgRole.ADMIN.value) etc."""

    async def _check(
        membership: OrganizationMember = Depends(require_membership),
    ) -> OrganizationMember:
        if not role_satisfies(membership.role, minimum_role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return membership

    return _check
