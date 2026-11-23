"""Execution data model (Phase 3).

`ExecutionContext` is a SNAPSHOT, not a live view of the database: it
carries plain values only (uuid, str, int, dict, datetime), never an
ORM model or a database session. An `EngineAdapter` must be able to
execute given nothing but a `ExecutionContext` instance — no import
of app.*, no AsyncSession, no query. This is what keeps the worker
independent of FastAPI/SQLAlchemy (Section 5 of the Phase 3 spec):
whatever assembles an `ExecutionContext` from real Scraper/Target
rows is Phase 4/5's job (the `jobs` table + dispatch), not this
module's.

`ExecutionResult`/`ExecutionError` are the *normal* return contract
for a classified, expected execution outcome (SSRF blocked, timed
out, oversized response, ...) — engines return these instead of
raising for anything in `ErrorCategory`. An engine may still raise
for a genuine programming bug; that is not something this contract
tries to catch or convert.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from worker.core.errors import ErrorCategory


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable snapshot of everything an engine needs to execute
    one target fetch. Frozen so that no engine can (accidentally or
    otherwise) mutate the context that other code — logging,
    retries, later phases — still holds a reference to.

    Field list is the Phase 3 spec's minimum plus one addition:
    `credential_reference`, a snapshot of `Scraper.credential_reference`
    (Phase 2) — kept as an explicit field rather than folded into
    `configuration`, since it is not an engine-config concern but a
    fail-closed precondition every engine must check the same way
    (see `worker.core.credentials`).
    """

    execution_id: UUID
    organization_id: UUID
    project_id: UUID
    scraper_id: UUID
    target_id: UUID
    scraper_version: int
    engine: str
    configuration: dict
    url: str
    requested_at: datetime
    timeout_seconds: int
    credential_reference: str | None = None


@dataclass(frozen=True)
class ExecutionError:
    category: ErrorCategory
    message: str
    retryable: bool


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    engine: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    response_size_bytes: int | None
    duration_ms: int
    safe_response_headers: dict[str, str]
    error: ExecutionError | None

    def __post_init__(self) -> None:
        # Fail loudly on an internally-inconsistent result rather
        # than let a caller trust `success` and `error` separately —
        # this contract only means something if the two fields can
        # never disagree.
        if self.success and self.error is not None:
            raise ValueError("a successful ExecutionResult must not carry an error")
        if not self.success and self.error is None:
            raise ValueError("a failed ExecutionResult must carry an error")
