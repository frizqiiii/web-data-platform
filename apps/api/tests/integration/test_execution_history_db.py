"""Integration tests for Phase 4 execution history — real PostgreSQL.

Status as authored: BLOCKED in the authoring sandbox (no Postgres).
Run via CI or:

    docker compose up -d postgres redis
    uv run alembic -c migrations/alembic.ini upgrade head
    uv run pytest apps/api/tests/integration/test_execution_history_db.py -m integration -v

There are no HTTP endpoints in Phase 4 (ADR-010), so tenant isolation
is proven at the service layer: org B can never read or mutate org A's
jobs/runs, and a scraper/target/job/run id from another tenant behaves
exactly like a nonexistent one (cross-tenant-denied + IDOR-denied).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from app.core.database import AsyncSessionLocal
from app.models.organization import Organization
from app.models.project import Project
from app.models.scrape_run import ScrapeRun
from app.models.scraper import Scraper
from app.models.target import Target
from app.models.user import User
from app.services import execution_history_service as svc
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionError, ExecutionResult

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Tenant:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    scraper_id: uuid.UUID
    target_ids: tuple[uuid.UUID, uuid.UUID]


async def _seed_tenant(db: AsyncSession) -> Tenant:
    suffix = uuid.uuid4().hex[:12]
    user = User(
        id=uuid.uuid4(),
        email=f"hist-{suffix}@wdp-test-mail.com",
        password_hash="not-a-real-hash",
        name="History Test",
    )
    org = Organization(id=uuid.uuid4(), name="History Org", slug=f"hist-org-{suffix}")
    db.add_all([user, org])
    await db.flush()

    project = Project(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="P",
        slug=f"hist-proj-{suffix}",
        created_by=user.id,
    )
    db.add(project)
    await db.flush()

    scraper = Scraper(
        id=uuid.uuid4(),
        project_id=project.id,
        name="S",
        slug=f"hist-scraper-{suffix}",
        engine="HTTP",
        configuration={},
        status="ACTIVE",
        version=1,
        created_by=user.id,
    )
    db.add(scraper)
    await db.flush()

    targets = (
        Target(id=uuid.uuid4(), scraper_id=scraper.id, url="https://example.com/a"),
        Target(id=uuid.uuid4(), scraper_id=scraper.id, url="https://example.com/b"),
    )
    db.add_all(targets)
    await db.flush()
    return Tenant(
        user_id=user.id,
        organization_id=org.id,
        project_id=project.id,
        scraper_id=scraper.id,
        target_ids=(targets[0].id, targets[1].id),
    )


async def _new_tenant() -> Tenant:
    async with AsyncSessionLocal() as db:
        tenant = await _seed_tenant(db)
        await db.commit()
    return tenant


def _ok() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        engine="HTTP",
        final_url="https://example.com/a",
        http_status=200,
        content_type="text/html",
        response_size_bytes=512,
        duration_ms=30,
        safe_response_headers={"content-type": "text/html"},
        error=None,
    )


def _fail(category: ErrorCategory, *, retryable: bool) -> ExecutionResult:
    return ExecutionResult(
        success=False,
        engine="HTTP",
        final_url=None,
        http_status=None,
        content_type=None,
        response_size_bytes=None,
        duration_ms=5,
        safe_response_headers={},
        error=ExecutionError(category=category, message="failed", retryable=retryable),
    )


@pytest.mark.asyncio
async def test_full_lifecycle_round_trip_persists_across_sessions() -> None:
    t = await _new_tenant()
    org = t.organization_id

    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=t.user_id
        )
        assert job.status == "PENDING"
        assert job.project_id == t.project_id  # derived, never caller-supplied
        assert job.scraper_version == 1
        job_id = job.id

        # Scraper edited after job creation: the job keeps its snapshot.
        scraper = await db.get(Scraper, t.scraper_id)
        assert scraper is not None
        scraper.version = 2

        await svc.start_job(db, organization_id=org, job_id=job_id)
        run_a = await svc.start_run(
            db, organization_id=org, job_id=job_id, target_id=t.target_ids[0]
        )
        run_b1 = await svc.start_run(
            db, organization_id=org, job_id=job_id, target_id=t.target_ids[1]
        )
        assert run_a.engine == "HTTP"
        assert run_a.target_url == "https://example.com/a"

        await svc.record_result(db, organization_id=org, run_id=run_a.id, result=_ok())
        await svc.record_result(
            db,
            organization_id=org,
            run_id=run_b1.id,
            result=_fail(ErrorCategory.CONNECTION_TIMEOUT, retryable=True),
        )
        # Target B retried (attempt 2) and succeeded.
        run_b2 = await svc.start_run(
            db, organization_id=org, job_id=job_id, target_id=t.target_ids[1], attempt_number=2
        )
        await svc.record_result(db, organization_id=org, run_id=run_b2.id, result=_ok())

        finished = await svc.finalize_job(db, organization_id=org, job_id=job_id)
        assert finished.status == "SUCCEEDED"
        assert finished.finished_at is not None
        await db.commit()

    # Fresh session: proves it was really persisted, not just in-memory.
    async with AsyncSessionLocal() as db:
        fetched = await svc.get_job(db, organization_id=org, job_id=job_id)
        assert fetched is not None
        assert fetched.status == "SUCCEEDED"
        assert fetched.scraper_version == 1  # snapshot survived the scraper edit
        assert fetched.requested_by == t.user_id

        runs = await svc.list_runs_for_job(db, organization_id=org, job_id=job_id)
        assert len(runs) == 3
        by_attempt = {(r.target_id, r.attempt_number): r for r in runs}
        failed = by_attempt[(t.target_ids[1], 1)]
        assert failed.status == "FAILED"
        assert failed.error_category == "CONNECTION_TIMEOUT"
        assert failed.error_retryable is True
        succeeded = by_attempt[(t.target_ids[0], 1)]
        assert succeeded.http_status == 200
        assert succeeded.safe_response_headers == {"content-type": "text/html"}

        listed = await svc.list_jobs_for_scraper(db, organization_id=org, scraper_id=t.scraper_id)
        assert [j.id for j in listed] == [job_id]


@pytest.mark.asyncio
async def test_job_fails_when_a_target_never_succeeds() -> None:
    t = await _new_tenant()
    org = t.organization_id
    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=None
        )
        await svc.start_job(db, organization_id=org, job_id=job.id)
        run = await svc.start_run(db, organization_id=org, job_id=job.id, target_id=t.target_ids[0])
        # Finalizing with an unfinished run is refused.
        with pytest.raises(svc.JobHasUnfinishedRuns):
            await svc.finalize_job(db, organization_id=org, job_id=job.id)
        await svc.record_result(
            db,
            organization_id=org,
            run_id=run.id,
            result=_fail(ErrorCategory.SSRF_BLOCKED, retryable=False),
        )
        finished = await svc.finalize_job(db, organization_id=org, job_id=job.id)
        assert finished.status == "FAILED"
        await db.commit()


@pytest.mark.asyncio
async def test_cross_tenant_access_is_denied() -> None:
    a = await _new_tenant()
    b = await _new_tenant()

    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=a.organization_id, scraper_id=a.scraper_id, requested_by=None
        )
        await svc.start_job(db, organization_id=a.organization_id, job_id=job.id)
        run = await svc.start_run(
            db, organization_id=a.organization_id, job_id=job.id, target_id=a.target_ids[0]
        )
        await db.commit()
        job_id, run_id = job.id, run.id

    async with AsyncSessionLocal() as db:
        # Org B using org A's ids: reads return nothing...
        assert await svc.get_job(db, organization_id=b.organization_id, job_id=job_id) is None
        assert await svc.get_run(db, organization_id=b.organization_id, run_id=run_id) is None
        assert (
            await svc.list_jobs_for_scraper(
                db, organization_id=b.organization_id, scraper_id=a.scraper_id
            )
            == []
        )
        assert (
            await svc.list_runs_for_job(db, organization_id=b.organization_id, job_id=job_id) == []
        )

        # ...and every mutation behaves as if the object does not exist.
        with pytest.raises(svc.ScraperNotFound):
            await svc.create_job(
                db,
                organization_id=b.organization_id,
                scraper_id=a.scraper_id,
                requested_by=None,
            )
        with pytest.raises(svc.JobNotFound):
            await svc.start_job(db, organization_id=b.organization_id, job_id=job_id)
        with pytest.raises(svc.JobNotFound):
            await svc.start_run(
                db, organization_id=b.organization_id, job_id=job_id, target_id=a.target_ids[1]
            )
        with pytest.raises(svc.RunNotFound):
            await svc.record_result(
                db, organization_id=b.organization_id, run_id=run_id, result=_ok()
            )
        with pytest.raises(svc.JobNotFound):
            await svc.finalize_job(db, organization_id=b.organization_id, job_id=job_id)

    # Org A's data is untouched by all of the above.
    async with AsyncSessionLocal() as db:
        run_row = await svc.get_run(db, organization_id=a.organization_id, run_id=run_id)
        assert run_row is not None
        assert run_row.status == "RUNNING"


@pytest.mark.asyncio
async def test_idor_target_from_another_scraper_or_tenant_is_denied() -> None:
    a = await _new_tenant()
    b = await _new_tenant()

    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=a.organization_id, scraper_id=a.scraper_id, requested_by=None
        )
        await svc.start_job(db, organization_id=a.organization_id, job_id=job.id)
        # Org B's target id inside org A's own (legitimate) job.
        with pytest.raises(svc.TargetNotFound):
            await svc.start_run(
                db,
                organization_id=a.organization_id,
                job_id=job.id,
                target_id=b.target_ids[0],
            )
        # A nonexistent target behaves identically.
        with pytest.raises(svc.TargetNotFound):
            await svc.start_run(
                db, organization_id=a.organization_id, job_id=job.id, target_id=uuid.uuid4()
            )
        await db.commit()


@pytest.mark.asyncio
async def test_duplicate_attempt_rejected_by_service_and_database() -> None:
    t = await _new_tenant()
    org = t.organization_id
    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=None
        )
        await svc.start_job(db, organization_id=org, job_id=job.id)
        await svc.start_run(db, organization_id=org, job_id=job.id, target_id=t.target_ids[0])
        with pytest.raises(svc.DuplicateAttempt):
            await svc.start_run(db, organization_id=org, job_id=job.id, target_id=t.target_ids[0])

        # The DB constraint is the backstop if the service check is bypassed.
        db.add(
            ScrapeRun(
                id=uuid.uuid4(),
                job_id=job.id,
                organization_id=org,
                target_id=t.target_ids[0],
                target_url="https://example.com/a",
                attempt_number=1,
                status="RUNNING",
                engine="HTTP",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_database_rejects_inconsistent_run_rows() -> None:
    t = await _new_tenant()
    org = t.organization_id
    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=None
        )
        await db.flush()
        job_id = job.id
        await db.commit()

    bad_rows = [
        # SUCCEEDED must not carry an error.
        {
            "status": "SUCCEEDED",
            "error_category": "DNS_FAILURE",
            "error_message": "x",
            "error_retryable": True,
            "finished_at": datetime.now(UTC),
        },
        # FAILED must carry the full error.
        {"status": "FAILED", "finished_at": datetime.now(UTC)},
        # RUNNING must not have finished.
        {"status": "RUNNING", "finished_at": datetime.now(UTC)},
        # Unknown error category.
        {
            "status": "FAILED",
            "error_category": "MADE_UP",
            "error_message": "x",
            "error_retryable": False,
            "finished_at": datetime.now(UTC),
        },
        # Out-of-range HTTP status.
        {"status": "SUCCEEDED", "http_status": 99, "finished_at": datetime.now(UTC)},
    ]
    for fields in bad_rows:
        async with AsyncSessionLocal() as db:
            db.add(
                ScrapeRun(
                    id=uuid.uuid4(),
                    job_id=job_id,
                    organization_id=org,
                    target_id=None,
                    target_url="https://example.com/a",
                    attempt_number=1,
                    engine="HTTP",
                    **fields,
                )
            )
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()


@pytest.mark.asyncio
async def test_run_history_survives_target_deletion() -> None:
    t = await _new_tenant()
    org = t.organization_id
    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=None
        )
        await svc.start_job(db, organization_id=org, job_id=job.id)
        run = await svc.start_run(db, organization_id=org, job_id=job.id, target_id=t.target_ids[0])
        await svc.record_result(db, organization_id=org, run_id=run.id, result=_ok())
        await db.commit()
        run_id = run.id

    async with AsyncSessionLocal() as db:
        target = await db.scalar(select(Target).where(Target.id == t.target_ids[0]))
        assert target is not None
        await db.delete(target)
        await db.commit()

    async with AsyncSessionLocal() as db:
        kept = await svc.get_run(db, organization_id=org, run_id=run_id)
        assert kept is not None
        assert kept.target_id is None  # ON DELETE SET NULL
        assert kept.target_url == "https://example.com/a"  # snapshot preserved
        assert kept.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_start_run_requires_running_job() -> None:
    t = await _new_tenant()
    org = t.organization_id
    async with AsyncSessionLocal() as db:
        job = await svc.create_job(
            db, organization_id=org, scraper_id=t.scraper_id, requested_by=None
        )
        # PENDING job: runs may not start yet.
        with pytest.raises(svc.JobNotRunning):
            await svc.start_run(db, organization_id=org, job_id=job.id, target_id=t.target_ids[0])
        # Terminal jobs cannot be restarted.
        await svc.start_job(db, organization_id=org, job_id=job.id)
        await svc.finalize_job(db, organization_id=org, job_id=job.id)  # no runs -> FAILED
        with pytest.raises(svc.InvalidStatusTransition):
            await svc.start_job(db, organization_id=org, job_id=job.id)
        await db.commit()
