"""Shared SQLAlchemy declarative base.

All Phase 1+ models inherit from this. Kept separate from
core/database.py (which owns the engine/session) so models can be
imported without pulling in engine creation (needed by Alembic
autogenerate, which now becomes usable for the first time).
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at/updated_at, timezone-aware (Section 8: timestamps
    must be timezone-aware), server-side defaults so they're correct
    even for rows inserted outside the ORM."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
