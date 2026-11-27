"""Job model (Phase 4, ADR-010).

A `Job` is ONE requested execution of a Scraper — scraper-level, as in
docs/architecture/execution-command-contract.md (the command payload
has `scraper_id`, no `target_id`). The per-target execution attempts
that make it up are `ScrapeRun` rows (app/models/scrape_run.py).

`scraper_version` is a SNAPSHOT of Scraper.version at job-creation
time (the contract's reproducibility rule), never "the current
version".

`organization_id` and `project_id` are denormalized from the scraper's
ownership chain so queries can filter on tenant directly. They are
set by app/services/execution_history_service.py from a
caller-verified organization and the scraper's real project — never
from client input.

Status is String + CheckConstraint (not a native ENUM); the value list
is kept in sync by hand with migration 0004 (a unit test checks it).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


# Explicit state machine, same style as PROJECT_/SCRAPER_STATUS_TRANSITIONS.
# PENDING -> FAILED exists so a job that can never start (e.g. nothing
# to execute) can still be closed out. No CANCELLED / QUEUED states:
# those belong to dispatch (Phase 5) and would be speculative now.
JOB_STATUS_TRANSITIONS: dict[str, set[str]] = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
}


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="ck_jobs_status"
        ),
        CheckConstraint("scraper_version >= 1", name="ck_jobs_scraper_version_positive"),
        Index("ix_jobs_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_jobs_scraper_id", "scraper_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scraper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrapers.id", ondelete="CASCADE"), nullable=False
    )
    scraper_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.PENDING.value)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
