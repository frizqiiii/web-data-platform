"""Project model.

Status is a plain String + DB CheckConstraint (Decision #3) — NOT a
native PostgreSQL ENUM — kept in sync with ProjectStatus below by
convention; any change to the valid set requires updating both this
enum and the migration's CheckConstraint together (see migration
0003's docstring)."""

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.scraper import Scraper


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


# Explicit state machine — never inferred from status ordering.
# Kept here (next to the model, not buried in the service) so the
# valid graph is easy to find. Enforcement itself lives in
# app/services/project_service.py.
PROJECT_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ProjectStatus.DRAFT: {ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED},
    ProjectStatus.ACTIVE: {ProjectStatus.PAUSED, ProjectStatus.ARCHIVED},
    ProjectStatus.PAUSED: {ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED},
    ProjectStatus.ARCHIVED: set(),
}


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectStatus.DRAFT.value
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    scrapers: Mapped[list["Scraper"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
