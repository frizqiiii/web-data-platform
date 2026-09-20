"""Scraper model.

`configuration` is JSONB (ADR-005): engine-specific settings
(timeout, concurrency, headers, ...) validated by a Pydantic
discriminated-union schema at the API boundary (app/schemas/
scraper_configuration.py), not by database constraints. `engine` is
domain metadata only in Phase 2 — no engine adapter exists yet
(that's Phase 3); it only determines which configuration schema
applies.

`credential_reference` is NOT a secret store (Decision #2) — it is a
plain string identifier meaning "look up a credential named this,
elsewhere, once that elsewhere exists". A scraper with a
credential_reference set is not yet a fully executable authenticated
scraper; nothing in this codebase resolves this reference to an
actual credential.
"""

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.target import Target


class ScraperEngine(StrEnum):
    HTTP = "HTTP"
    BROWSER = "BROWSER"
    SCRAPY = "SCRAPY"


class ScraperStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


# Deliberately simpler than Project's — no PAUSED state (Phase 2
# scope note: distinguishing "manually disabled" from "paused by a
# scheduler" is a Phase 6 concept that doesn't exist yet; adding it
# now would be speculative).
SCRAPER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ScraperStatus.DRAFT: {ScraperStatus.ACTIVE, ScraperStatus.ARCHIVED},
    ScraperStatus.ACTIVE: {ScraperStatus.DISABLED, ScraperStatus.ARCHIVED},
    ScraperStatus.DISABLED: {ScraperStatus.ACTIVE, ScraperStatus.ARCHIVED},
    ScraperStatus.ARCHIVED: set(),
}


class Scraper(TimestampMixin, Base):
    __tablename__ = "scrapers"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_scraper_project_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    credential_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ScraperStatus.DRAFT.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="scrapers")
    targets: Mapped[list["Target"]] = relationship(
        back_populates="scraper", cascade="all, delete-orphan"
    )
