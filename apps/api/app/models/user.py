"""User model.

Password is NEVER stored or exposed as plaintext (Decision B) — only
`password_hash` (Argon2id, see app/core/security.py) exists on this
model. There is deliberately no `password` attribute at all, so it
cannot be accidentally serialized or logged.
"""

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Import-time cycle guard: organization_member.py imports back
    # from this module for its own relationship() type. Only needed
    # for type checkers (Mapped[...] string forward-refs) — never
    # actually imported at runtime, so no circular import happens.
    from app.models.organization_member import OrganizationMember


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    # Declared explicitly (not unique=True/index=True) so the model matches
    # migration 0002 exactly: a named unique CONSTRAINT plus a separate
    # non-unique index. See PHASE_4_5_REPORT.md.
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
