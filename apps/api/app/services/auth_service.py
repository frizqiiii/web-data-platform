"""Authentication business logic: registration and login.

Deliberately thin — this is where password verification happens, but
session issuance is delegated to app.core.sessions.SessionStore, and
audit writes to app.services.audit_service, so this stays focused on
"is this email/password combination valid" and "is this account
usable".
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User, UserStatus


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    """Deliberately generic — never reveals whether the email exists
    or the password was wrong, to avoid user enumeration."""


async def register_user(db: AsyncSession, *, email: str, password: str, name: str) -> User:
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailAlreadyRegistered(email)

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        name=name,
        status=UserStatus.ACTIVE.value,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or user.status != UserStatus.ACTIVE.value:
        # Run verify_password against a dummy hash even when the user
        # doesn't exist, so response timing doesn't leak whether the
        # email is registered.
        verify_password(password, hash_password("dummy-constant-time-padding"))
        raise InvalidCredentials()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    return user
