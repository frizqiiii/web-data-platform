"""Target model.

`url` MUST pass app.core.url_safety.validate_target_url before being
persisted (enforced in app/services/target_service.py, not at the DB
layer — Postgres has no SSRF concept). This is Phase 2's SSRF
mitigation; Phase 3 must re-validate at fetch time regardless (ADR-006
— a URL safe at creation is not guaranteed safe at execution time).
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.scraper import Scraper


class Target(TimestampMixin, Base):
    __tablename__ = "targets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scraper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrapers.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text(), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    scraper: Mapped[Scraper] = relationship(back_populates="targets")
