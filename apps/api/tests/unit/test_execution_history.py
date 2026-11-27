"""Unit tests for Phase 4 execution history — no database needed.

Covers: state machines, model <-> migration 0004 sync (including
drift against worker.core.errors.ErrorCategory), the pure
`derive_job_status` rule, header/length sanitization, and
`record_result` mapping using a fake session (the real-database
behavior is covered by tests/integration/test_execution_history_db.py).
"""

import importlib.util
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from app.models.job import JOB_STATUS_TRANSITIONS, Job, JobStatus
from app.models.scrape_run import (
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_URL_LENGTH,
    RUN_ENGINES,
    RUN_ERROR_CATEGORIES,
    SCRAPE_RUN_STATUS_TRANSITIONS,
    ScrapeRun,
    ScrapeRunStatus,
)
from app.models.scraper import ScraperEngine
from app.services import execution_history_service as svc
from app.services.execution_history_service import (
    ExecutionResultLike,
    InvalidExecutionResult,
    InvalidStatusTransition,
    RunSummary,
    derive_job_status,
    sanitize_headers,
)
from sqlalchemy.ext.asyncio import AsyncSession
from worker.core.errors import ErrorCategory
from worker.core.execution import ExecutionError, ExecutionResult
from worker.engines.http.engine import _SAFE_RESPONSE_HEADERS

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0004_phase4_execution_history.py"


# --- drift guards ---------------------------------------------------------


def test_run_error_categories_match_worker_error_category() -> None:
    assert set(RUN_ERROR_CATEGORIES) == {c.value for c in ErrorCategory}
    assert len(RUN_ERROR_CATEGORIES) == len(set(RUN_ERROR_CATEGORIES))


def test_run_engines_match_scraper_engine() -> None:
    assert set(RUN_ENGINES) == {e.value for e in ScraperEngine}


def test_safe_header_allowlist_matches_http_engine() -> None:
    assert frozenset(_SAFE_RESPONSE_HEADERS) == svc.SAFE_RESPONSE_HEADER_NAMES


class _OpRecorder:
    """Stands in for `alembic.op` so upgrade() can be executed with no
    database, capturing the schema objects it would create."""

    def __init__(self) -> None:
        self.tables: dict[str, tuple[Any, ...]] = {}
        self.indexes: dict[str, tuple[str, list[str]]] = {}
        self.uniques: dict[str, tuple[str, list[str]]] = {}

    def create_table(self, name: str, *items: Any, **_: Any) -> None:
        self.tables[name] = items

    def create_index(self, name: str, table: str, cols: list[str], **_: Any) -> None:
        self.indexes[name] = (table, cols)

    def create_unique_constraint(self, name: str, table: str, cols: list[str]) -> None:
        self.uniques[name] = (table, cols)


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("migration_0004", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recorded_upgrade() -> _OpRecorder:
    module = _load_migration()
    recorder = _OpRecorder()
    module.op = recorder
    module.upgrade()
    return recorder


@pytest.mark.parametrize(("table_name", "model"), [("jobs", Job), ("scrape_runs", ScrapeRun)])
def test_migration_0004_matches_models(table_name: str, model: Any) -> None:
    recorder = _recorded_upgrade()
    items = recorder.tables[table_name]
    table = model.__table__

    migration_columns = {i.name for i in items if isinstance(i, sa.Column)}
    assert migration_columns == {c.name for c in table.columns}

    migration_checks = {i.name: str(i.sqltext) for i in items if isinstance(i, sa.CheckConstraint)}
    model_checks = {
        c.name: str(c.sqltext) for c in table.constraints if isinstance(c, sa.CheckConstraint)
    }
    assert migration_checks == model_checks

    migration_fks = {
        (tuple(i.column_keys), i.elements[0].target_fullname, i.ondelete)
        for i in items
        if isinstance(i, sa.ForeignKeyConstraint)
    }
    model_fks = {
        (tuple(c.column_keys), c.elements[0].target_fullname, c.ondelete)
        for c in table.constraints
        if isinstance(c, sa.ForeignKeyConstraint)
    }
    assert migration_fks == model_fks

    migration_indexes = {n for n, (t, _) in recorder.indexes.items() if t == table_name}
    assert migration_indexes == {i.name for i in table.indexes}

    migration_uniques = {n for n, (t, _) in recorder.uniques.items() if t == table_name}
    model_uniques = {c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint)}
    assert migration_uniques == model_uniques


def test_migration_0004_chain_and_downgrade_defined() -> None:
    module = _load_migration()
    assert module.revision == "0004"
    assert module.down_revision == "0003"
    assert callable(module.downgrade)


# --- state machines ---------------------------------------------------------


def test_job_state_machine_shape() -> None:
    assert JOB_STATUS_TRANSITIONS[JobStatus.PENDING] == {JobStatus.RUNNING, JobStatus.FAILED}
    assert JOB_STATUS_TRANSITIONS[JobStatus.RUNNING] == {JobStatus.SUCCEEDED, JobStatus.FAILED}
    assert JOB_STATUS_TRANSITIONS[JobStatus.SUCCEEDED] == set()
    assert JOB_STATUS_TRANSITIONS[JobStatus.FAILED] == set()
    assert set(JOB_STATUS_TRANSITIONS) == {s.value for s in JobStatus}


def test_run_state_machine_shape() -> None:
    assert SCRAPE_RUN_STATUS_TRANSITIONS[ScrapeRunStatus.RUNNING] == {
        ScrapeRunStatus.SUCCEEDED,
        ScrapeRunStatus.FAILED,
    }
    assert SCRAPE_RUN_STATUS_TRANSITIONS[ScrapeRunStatus.SUCCEEDED] == set()
    assert SCRAPE_RUN_STATUS_TRANSITIONS[ScrapeRunStatus.FAILED] == set()
    assert set(SCRAPE_RUN_STATUS_TRANSITIONS) == {s.value for s in ScrapeRunStatus}


# --- derive_job_status -------------------------------------------------------


def _run(target: uuid.UUID | None, attempt: int, status: str) -> RunSummary:
    return RunSummary(run_id=uuid.uuid4(), target_id=target, attempt_number=attempt, status=status)


def test_job_with_no_runs_is_failed() -> None:
    assert derive_job_status([]) == JobStatus.FAILED.value


def test_job_succeeds_when_every_target_succeeded() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    runs = [_run(a, 1, "SUCCEEDED"), _run(b, 1, "SUCCEEDED")]
    assert derive_job_status(runs) == JobStatus.SUCCEEDED.value


def test_job_fails_when_any_target_failed() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    runs = [_run(a, 1, "SUCCEEDED"), _run(b, 1, "FAILED")]
    assert derive_job_status(runs) == JobStatus.FAILED.value


def test_retry_that_succeeds_makes_target_succeed() -> None:
    a = uuid.uuid4()
    runs = [_run(a, 1, "FAILED"), _run(a, 2, "SUCCEEDED")]
    assert derive_job_status(runs) == JobStatus.SUCCEEDED.value


def test_latest_attempt_wins_even_if_earlier_succeeded() -> None:
    a = uuid.uuid4()
    runs = [_run(a, 1, "SUCCEEDED"), _run(a, 2, "FAILED")]
    assert derive_job_status(runs) == JobStatus.FAILED.value


def test_runs_with_deleted_target_are_grouped_individually() -> None:
    runs = [_run(None, 1, "SUCCEEDED"), _run(None, 1, "FAILED")]
    assert derive_job_status(runs) == JobStatus.FAILED.value


def test_derive_refuses_unfinished_runs() -> None:
    with pytest.raises(ValueError, match="RUNNING"):
        derive_job_status([_run(uuid.uuid4(), 1, "RUNNING")])


# --- sanitization -------------------------------------------------------------


def test_sanitize_headers_keeps_only_allowlist_and_lowercases() -> None:
    cleaned = sanitize_headers(
        {
            "Content-Type": "text/html",
            "Set-Cookie": "session=secret",
            "Authorization": "Bearer x",
            "ETag": "abc",
        }
    )
    assert cleaned == {"content-type": "text/html", "etag": "abc"}


def test_sanitize_headers_caps_value_length() -> None:
    cleaned = sanitize_headers({"etag": "x" * 5000})
    assert len(cleaned["etag"]) == svc.MAX_HEADER_VALUE_LENGTH


# --- record_result with a fake session ---------------------------------------


class _FakeSession:
    """Just enough of AsyncSession for record_result: `scalar` returns
    the pre-loaded run, `flush` is a no-op."""

    def __init__(self, run: ScrapeRun | None) -> None:
        self._run = run
        self.flushed = 0

    async def scalar(self, _statement: Any) -> ScrapeRun | None:
        return self._run

    async def flush(self) -> None:
        self.flushed += 1


def _db(run: ScrapeRun | None) -> AsyncSession:
    return cast(AsyncSession, _FakeSession(run))


def _running_run(org: uuid.UUID) -> ScrapeRun:
    return ScrapeRun(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        organization_id=org,
        target_id=uuid.uuid4(),
        target_url="https://example.com/",
        attempt_number=1,
        status=ScrapeRunStatus.RUNNING.value,
        engine="HTTP",
    )


def _success_result() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        engine="HTTP",
        final_url="https://example.com/",
        http_status=200,
        content_type="text/html",
        response_size_bytes=1256,
        duration_ms=42,
        safe_response_headers={"content-type": "text/html", "set-cookie": "leak"},
        error=None,
    )


def _failure_result(category: ErrorCategory, message: str = "boom") -> ExecutionResult:
    return ExecutionResult(
        success=False,
        engine="HTTP",
        final_url=None,
        http_status=None,
        content_type=None,
        response_size_bytes=None,
        duration_ms=7,
        safe_response_headers={},
        error=ExecutionError(category=category, message=message, retryable=False),
    )


def test_real_execution_result_satisfies_protocol() -> None:
    # mypy proves the structural fit; at runtime we just use it.
    result: ExecutionResultLike = _success_result()
    assert result.success is True


async def test_record_result_maps_success() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    out = await svc.record_result(
        _db(run), organization_id=org, run_id=run.id, result=_success_result()
    )
    assert out.status == "SUCCEEDED"
    assert out.http_status == 200
    assert out.response_size_bytes == 1256
    assert out.duration_ms == 42
    assert out.safe_response_headers == {"content-type": "text/html"}
    assert out.error_category is None and out.error_message is None
    assert out.finished_at is not None


async def test_record_result_maps_failure_category_enum_to_string() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    out = await svc.record_result(
        _db(run),
        organization_id=org,
        run_id=run.id,
        result=_failure_result(ErrorCategory.SSRF_BLOCKED, "blocked"),
    )
    assert out.status == "FAILED"
    assert out.error_category == "SSRF_BLOCKED"
    assert out.error_message == "blocked"
    assert out.error_retryable is False
    assert out.finished_at is not None


async def test_record_result_truncates_long_message_and_url() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    long_result = ExecutionResult(
        success=False,
        engine="HTTP",
        final_url="https://example.com/" + "a" * 5000,
        http_status=500,
        content_type=None,
        response_size_bytes=None,
        duration_ms=1,
        safe_response_headers={},
        error=ExecutionError(category=ErrorCategory.HTTP_ERROR, message="m" * 5000, retryable=True),
    )
    out = await svc.record_result(_db(run), organization_id=org, run_id=run.id, result=long_result)
    assert out.error_message is not None and len(out.error_message) == MAX_ERROR_MESSAGE_LENGTH
    assert out.final_url is not None and len(out.final_url) == MAX_URL_LENGTH


async def test_record_result_twice_is_rejected() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    db = _db(run)
    await svc.record_result(db, organization_id=org, run_id=run.id, result=_success_result())
    with pytest.raises(InvalidStatusTransition):
        await svc.record_result(db, organization_id=org, run_id=run.id, result=_success_result())


async def test_record_result_unknown_run_raises_not_found() -> None:
    with pytest.raises(svc.RunNotFound):
        await svc.record_result(
            _db(None),
            organization_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            result=_success_result(),
        )


class _InconsistentResult:
    """success=True but carrying an error — the real ExecutionResult
    refuses to exist in this state, so a fake is needed."""

    success = True
    final_url = None
    http_status = None
    content_type = None
    response_size_bytes = None
    duration_ms = 1
    safe_response_headers: dict[str, str] = {}
    error = ExecutionError(category=ErrorCategory.DNS_FAILURE, message="x", retryable=True)


async def test_record_result_rejects_inconsistent_result() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    with pytest.raises(InvalidExecutionResult):
        await svc.record_result(
            _db(run), organization_id=org, run_id=run.id, result=_InconsistentResult()
        )
    assert run.status == "RUNNING"  # nothing was written


class _BadCategoryError:
    category = "NOT_A_REAL_CATEGORY"
    message = "x"
    retryable = False


class _BadCategoryResult:
    success = False
    final_url = None
    http_status = None
    content_type = None
    response_size_bytes = None
    duration_ms = 1
    safe_response_headers: dict[str, str] = {}
    error = _BadCategoryError()


async def test_record_result_rejects_unknown_error_category() -> None:
    org = uuid.uuid4()
    run = _running_run(org)
    with pytest.raises(InvalidExecutionResult, match="unknown error category"):
        await svc.record_result(
            _db(run), organization_id=org, run_id=run.id, result=_BadCategoryResult()
        )
    assert run.status == "RUNNING"  # rejected before any mutation
    assert run.finished_at is None
