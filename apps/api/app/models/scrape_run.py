"""ScrapeRun model (Phase 4, ADR-010).

One row = one execution ATTEMPT of one Target within a Job. Retries
(Phase 5) become additional rows with a higher `attempt_number`, never
an overwrite of an earlier attempt.

`id` is intended to be used as `ExecutionContext.execution_id`
(worker/core/execution.py) by whatever builds the context in Phase 5.

What is stored is exactly the classified outcome the engine returned
(`ExecutionResult` / `ExecutionError`, Phase 3) and nothing more:
NO response body, NO scraper configuration, NO credential material, and
only allowlisted response headers (see
app/services/execution_history_service.py). `target_url` is a snapshot
so history stays readable after the Target is edited or deleted
(`target_id` is SET NULL on delete).

RUN_ENGINES and RUN_ERROR_CATEGORIES intentionally DUPLICATE values
from ScraperEngine and worker.core.errors.ErrorCategory — the API must
not import `worker.*` (ADR-008). A unit test fails if they drift.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ScrapeRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


SCRAPE_RUN_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ScrapeRunStatus.RUNNING: {ScrapeRunStatus.SUCCEEDED, ScrapeRunStatus.FAILED},
    ScrapeRunStatus.SUCCEEDED: set(),
    ScrapeRunStatus.FAILED: set(),
}

RUN_ENGINES: tuple[str, ...] = ("HTTP", "BROWSER", "SCRAPY")

RUN_ERROR_CATEGORIES: tuple[str, ...] = (
    "VALIDATION_ERROR",
    "SSRF_BLOCKED",
    "DNS_FAILURE",
    "CONNECTION_TIMEOUT",
    "READ_TIMEOUT",
    "TLS_FAILURE",
    "CONNECTION_FAILURE",
    "HTTP_ERROR",
    "REDIRECT_BLOCKED",
    "RESPONSE_TOO_LARGE",
    "BROWSER_FAILURE",
    "PARSER_FAILURE",
    "ENGINE_UNSUPPORTED",
    "CREDENTIAL_UNAVAILABLE",
)

# Persistence-side length caps (match the column sizes in migration 0004).
MAX_URL_LENGTH = 2048
MAX_CONTENT_TYPE_LENGTH = 255
MAX_ERROR_MESSAGE_LENGTH = 500


class ScrapeRun(TimestampMixin, Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "target_id", "attempt_number", name="uq_scrape_run_job_target_attempt"
        ),
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')", name="ck_scrape_runs_status"),
        CheckConstraint("engine IN ('HTTP','BROWSER','SCRAPY')", name="ck_scrape_runs_engine"),
        CheckConstraint(
            "error_category IS NULL OR error_category IN ("
            "'VALIDATION_ERROR','SSRF_BLOCKED','DNS_FAILURE','CONNECTION_TIMEOUT',"
            "'READ_TIMEOUT','TLS_FAILURE','CONNECTION_FAILURE','HTTP_ERROR',"
            "'REDIRECT_BLOCKED','RESPONSE_TOO_LARGE','BROWSER_FAILURE','PARSER_FAILURE',"
            "'ENGINE_UNSUPPORTED','CREDENTIAL_UNAVAILABLE')",
            name="ck_scrape_runs_error_category",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_scrape_runs_attempt_positive"),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_scrape_runs_http_status_range",
        ),
        CheckConstraint(
            "response_size_bytes IS NULL OR response_size_bytes >= 0",
            name="ck_scrape_runs_size_non_negative",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_scrape_runs_duration_non_negative",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND error_category IS NULL AND error_message IS NULL "
            "AND error_retryable IS NULL AND finished_at IS NULL) "
            "OR (status = 'SUCCEEDED' AND error_category IS NULL AND error_message IS NULL "
            "AND error_retryable IS NULL AND finished_at IS NOT NULL) "
            "OR (status = 'FAILED' AND error_category IS NOT NULL AND error_message IS NOT NULL "
            "AND error_retryable IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_scrape_runs_outcome_consistency",
        ),
        Index("ix_scrape_runs_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_scrape_runs_job_id", "job_id"),
        Index("ix_scrape_runs_target_id", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="SET NULL"), nullable=True
    )
    target_url: Mapped[str] = mapped_column(String(MAX_URL_LENGTH), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ScrapeRunStatus.RUNNING.value
    )
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(MAX_URL_LENGTH), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(MAX_CONTENT_TYPE_LENGTH), nullable=True)
    response_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_response_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(MAX_ERROR_MESSAGE_LENGTH), nullable=True
    )
    error_retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
