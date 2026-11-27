"""Execution history persistence (Phase 4, ADR-010).

Records Jobs (one requested execution of a scraper) and ScrapeRuns
(one attempt against one target) and the classified outcome the
engine returned. This module does NOT dispatch, retry, schedule or
execute anything — see ADR-010 "Out of scope".

TENANT RULE (ADR-004): every function takes `organization_id` from a
caller-verified source and every query filters on it. A job/run/
scraper/target that exists but belongs to another organization is
indistinguishable from one that does not exist (the same "not found"
exception / `None`), mirroring the 404-not-403 IDOR pattern in
app/api/deps.py. `project_id` is never accepted from the caller: it is
derived from the scraper's real project.

The API must not import `worker.*` (ADR-008), so `record_result`
accepts any object with the shape of worker.core.execution.
ExecutionResult via the structural Protocols below. The real worker
dataclasses satisfy them; the unit tests prove it.

WHAT IS PERSISTED: only the classified outcome fields. Never a
response body, scraper configuration, or credential material; response
headers are re-filtered here against the same 4-name allowlist the
HTTP engine uses (defense in depth). URLs / messages are length-capped
(truncated) to the column sizes. NOTE (ADR-010): target_url/final_url
are stored as-is, so a token placed in a URL query string would be
stored in plaintext.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import JOB_STATUS_TRANSITIONS, Job, JobStatus
from app.models.project import Project
from app.models.scrape_run import (
    MAX_CONTENT_TYPE_LENGTH,
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_URL_LENGTH,
    RUN_ERROR_CATEGORIES,
    SCRAPE_RUN_STATUS_TRANSITIONS,
    ScrapeRun,
    ScrapeRunStatus,
)
from app.models.scraper import Scraper
from app.models.target import Target

# Same allowlist as worker/engines/http/engine.py::_SAFE_RESPONSE_HEADERS.
# Duplicated on purpose (API must not import worker.*); a unit test
# asserts the two stay equal.
SAFE_RESPONSE_HEADER_NAMES = frozenset({"content-type", "content-length", "last-modified", "etag"})
MAX_HEADER_VALUE_LENGTH = 500
MAX_LIST_LIMIT = 200


class ScraperNotFound(Exception):
    pass


class TargetNotFound(Exception):
    pass


class JobNotFound(Exception):
    pass


class RunNotFound(Exception):
    pass


class DuplicateAttempt(Exception):
    pass


class JobNotRunning(Exception):
    pass


class JobHasUnfinishedRuns(Exception):
    pass


class InvalidExecutionResult(Exception):
    pass


class InvalidStatusTransition(Exception):
    def __init__(self, entity: str, current: str, requested: str) -> None:
        self.entity = entity
        self.current = current
        self.requested = requested
        super().__init__(f"cannot transition {entity} from {current} to {requested}")


class ExecutionErrorLike(Protocol):
    @property
    def category(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def retryable(self) -> bool: ...


class ExecutionResultLike(Protocol):
    @property
    def success(self) -> bool: ...
    @property
    def final_url(self) -> str | None: ...
    @property
    def http_status(self) -> int | None: ...
    @property
    def content_type(self) -> str | None: ...
    @property
    def response_size_bytes(self) -> int | None: ...
    @property
    def duration_ms(self) -> int: ...
    @property
    def safe_response_headers(self) -> Mapping[str, str]: ...
    @property
    def error(self) -> ExecutionErrorLike | None: ...


@dataclass(frozen=True)
class RunSummary:
    """Minimal view of a run used to derive a job's final status."""

    run_id: uuid.UUID
    target_id: uuid.UUID | None
    attempt_number: int
    status: str


def _now() -> datetime:
    return datetime.now(UTC)


def _cap(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def _require_transition(
    transitions: dict[str, set[str]], entity: str, current: str, requested: str
) -> None:
    if requested not in transitions.get(current, set()):
        raise InvalidStatusTransition(entity, current, requested)


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name.lower(): _cap(value, MAX_HEADER_VALUE_LENGTH)
        for name, value in headers.items()
        if name.lower() in SAFE_RESPONSE_HEADER_NAMES
    }


def derive_job_status(runs: Sequence[RunSummary]) -> str:
    """SUCCEEDED iff there is at least one run and the LATEST attempt of
    every target succeeded; otherwise FAILED. A job that executed
    nothing did not succeed. Raises ValueError if any run is still
    RUNNING (callers must not finalize a job with unfinished runs).
    """
    if any(r.status == ScrapeRunStatus.RUNNING.value for r in runs):
        raise ValueError("cannot derive a job status while runs are still RUNNING")
    if not runs:
        return JobStatus.FAILED.value
    latest: dict[uuid.UUID, RunSummary] = {}
    for run in runs:
        # A run whose target was deleted (target_id NULL) can't be
        # grouped with its siblings; treat it as its own group.
        key = run.target_id if run.target_id is not None else run.run_id
        current = latest.get(key)
        if current is None or run.attempt_number > current.attempt_number:
            latest[key] = run
    if all(r.status == ScrapeRunStatus.SUCCEEDED.value for r in latest.values()):
        return JobStatus.SUCCEEDED.value
    return JobStatus.FAILED.value


# --- writes -------------------------------------------------------------


async def create_job(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    scraper_id: uuid.UUID,
    requested_by: uuid.UUID | None,
) -> Job:
    result = await db.execute(
        select(Scraper)
        .join(Project, Project.id == Scraper.project_id)
        .where(Scraper.id == scraper_id, Project.organization_id == organization_id)
    )
    scraper = result.scalar_one_or_none()
    if scraper is None:
        raise ScraperNotFound(str(scraper_id))

    job = Job(
        id=uuid.uuid4(),
        organization_id=organization_id,
        project_id=scraper.project_id,
        scraper_id=scraper.id,
        scraper_version=scraper.version,
        status=JobStatus.PENDING.value,
        requested_by=requested_by,
    )
    db.add(job)
    await db.flush()
    return job


async def start_job(db: AsyncSession, *, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await _get_job_or_raise(db, organization_id, job_id)
    _require_transition(JOB_STATUS_TRANSITIONS, "job", job.status, JobStatus.RUNNING.value)
    job.status = JobStatus.RUNNING.value
    job.started_at = _now()
    await db.flush()
    return job


async def start_run(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    target_id: uuid.UUID,
    attempt_number: int = 1,
) -> ScrapeRun:
    if attempt_number < 1:
        raise ValueError("attempt_number must be >= 1")
    job = await _get_job_or_raise(db, organization_id, job_id)
    if job.status != JobStatus.RUNNING.value:
        raise JobNotRunning(str(job_id))

    # The target must belong to THIS job's scraper (which is itself
    # already verified to belong to the organization via the job).
    target = await db.scalar(
        select(Target).where(Target.id == target_id, Target.scraper_id == job.scraper_id)
    )
    if target is None:
        raise TargetNotFound(str(target_id))
    scraper = await db.scalar(select(Scraper).where(Scraper.id == job.scraper_id))
    if scraper is None:  # pragma: no cover - FK guarantees this exists
        raise ScraperNotFound(str(job.scraper_id))

    existing = await db.scalar(
        select(ScrapeRun.id).where(
            ScrapeRun.job_id == job.id,
            ScrapeRun.target_id == target.id,
            ScrapeRun.attempt_number == attempt_number,
        )
    )
    if existing is not None:
        raise DuplicateAttempt(f"job={job_id} target={target_id} attempt={attempt_number}")

    run = ScrapeRun(
        id=uuid.uuid4(),
        job_id=job.id,
        organization_id=organization_id,
        target_id=target.id,
        target_url=_cap(target.url, MAX_URL_LENGTH),
        attempt_number=attempt_number,
        status=ScrapeRunStatus.RUNNING.value,
        engine=scraper.engine,
        started_at=_now(),
    )
    db.add(run)
    await db.flush()
    return run


async def record_result(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    run_id: uuid.UUID,
    result: ExecutionResultLike,
) -> ScrapeRun:
    run = await _get_run_or_raise(db, organization_id, run_id)
    new_status = ScrapeRunStatus.SUCCEEDED.value if result.success else ScrapeRunStatus.FAILED.value
    _require_transition(SCRAPE_RUN_STATUS_TRANSITIONS, "run", run.status, new_status)

    # Same invariant as ExecutionResult.__post_init__, re-checked here
    # because this function accepts a structural type, not the class.
    error = result.error
    if result.success and error is not None:
        raise InvalidExecutionResult("a successful result must not carry an error")
    if not result.success and error is None:
        raise InvalidExecutionResult("a failed result must carry an error")

    # Validate EVERYTHING before mutating anything, so a rejected
    # result leaves the run untouched.
    category: str | None = None
    if error is not None:
        category = str(getattr(error.category, "value", error.category))
        if category not in RUN_ERROR_CATEGORIES:
            raise InvalidExecutionResult(f"unknown error category: {category!r}")

    run.status = new_status
    run.final_url = _cap(result.final_url, MAX_URL_LENGTH) if result.final_url else None
    run.http_status = result.http_status
    run.content_type = (
        _cap(result.content_type, MAX_CONTENT_TYPE_LENGTH) if result.content_type else None
    )
    run.response_size_bytes = result.response_size_bytes
    run.duration_ms = result.duration_ms
    run.safe_response_headers = sanitize_headers(result.safe_response_headers)
    if error is not None:
        run.error_category = category
        run.error_message = _cap(error.message, MAX_ERROR_MESSAGE_LENGTH)
        run.error_retryable = error.retryable
    run.finished_at = _now()
    await db.flush()
    return run


async def finalize_job(db: AsyncSession, *, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await _get_job_or_raise(db, organization_id, job_id)
    if job.status != JobStatus.RUNNING.value:
        raise InvalidStatusTransition("job", job.status, "FINALIZED")

    rows = await db.execute(
        select(ScrapeRun.id, ScrapeRun.target_id, ScrapeRun.attempt_number, ScrapeRun.status).where(
            ScrapeRun.job_id == job.id, ScrapeRun.organization_id == organization_id
        )
    )
    summaries = [
        RunSummary(
            run_id=r.id, target_id=r.target_id, attempt_number=r.attempt_number, status=r.status
        )
        for r in rows
    ]
    if any(s.status == ScrapeRunStatus.RUNNING.value for s in summaries):
        raise JobHasUnfinishedRuns(str(job_id))

    new_status = derive_job_status(summaries)
    _require_transition(JOB_STATUS_TRANSITIONS, "job", job.status, new_status)
    job.status = new_status
    job.finished_at = _now()
    await db.flush()
    return job


# --- reads (always organization-scoped) ----------------------------------


async def get_job(db: AsyncSession, *, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    job: Job | None = await db.scalar(
        select(Job).where(Job.id == job_id, Job.organization_id == organization_id)
    )
    return job


async def list_jobs_for_scraper(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    scraper_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)
    result = await db.scalars(
        select(Job)
        .where(Job.scraper_id == scraper_id, Job.organization_id == organization_id)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def get_run(
    db: AsyncSession, *, organization_id: uuid.UUID, run_id: uuid.UUID
) -> ScrapeRun | None:
    run: ScrapeRun | None = await db.scalar(
        select(ScrapeRun).where(
            ScrapeRun.id == run_id, ScrapeRun.organization_id == organization_id
        )
    )
    return run


async def list_runs_for_job(
    db: AsyncSession, *, organization_id: uuid.UUID, job_id: uuid.UUID
) -> list[ScrapeRun]:
    result = await db.scalars(
        select(ScrapeRun)
        .where(ScrapeRun.job_id == job_id, ScrapeRun.organization_id == organization_id)
        .order_by(ScrapeRun.started_at, ScrapeRun.attempt_number, ScrapeRun.id)
    )
    return list(result.all())


# --- internals -------------------------------------------------------------


async def _get_job_or_raise(db: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await get_job(db, organization_id=organization_id, job_id=job_id)
    if job is None:
        raise JobNotFound(str(job_id))
    return job


async def _get_run_or_raise(
    db: AsyncSession, organization_id: uuid.UUID, run_id: uuid.UUID
) -> ScrapeRun:
    run = await get_run(db, organization_id=organization_id, run_id=run_id)
    if run is None:
        raise RunNotFound(str(run_id))
    return run
