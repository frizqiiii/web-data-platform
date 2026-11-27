# ADR-010: Execution History Persistence (jobs / scrape_runs)

## Status

Accepted (Phase 4). Decisions below were proposed in the Phase 4 plan
and approved before implementation.

## Context

Phase 3 produced the worker-side execution pipeline
(`ExecutionContext -> EngineResolver -> EngineAdapter ->
ExecutionResult/ExecutionError`) but nothing records what happened.
`docs/architecture/execution-command-contract.md` reserved a `jobs`
table and `scrape_runs` (execution history) for Phase 4 without
specifying either schema. Four things had to be settled:

1. Where persistence code lives, given the worker must not import
   `app.*` (ADR-008) and the API must not import `worker.*`.
2. How a job relates to a run (the contract's payload has
   `scraper_id` but no `target_id`; `ExecutionContext` is per-target).
3. How tenant isolation applies to rows that have no direct tenant
   column in the existing hierarchy.
4. What exactly of an `ExecutionResult` may be stored.

## Decisions

### 1. Persistence is API-side, structurally typed (no cross-imports)

`apps/api/app/services/execution_history_service.py` owns all writes
and reads, using new models in `apps/api/app/models/`. It accepts the
engine outcome through structural `Protocol`s (`ExecutionResultLike`,
`ExecutionErrorLike`) so the API never imports `worker.*`; the real
`ExecutionResult` dataclasses satisfy them (checked by mypy and by
unit tests that pass real instances).

**How the worker reaches the database (direct access vs an internal
API) is deliberately NOT decided here.** Nothing calls this service
yet, so any answer would be speculative; it is a Phase 5 decision.

Rejected: moving models into `packages/` (large refactor touching
Phase 1-3 imports and Alembic, for no Phase 4 benefit) and giving the
worker its own duplicate models (two sources of truth for one schema).

### 2. A job is scraper-level; a run is one attempt against one target

- `jobs`: one requested execution of a scraper. Carries
  `scraper_version`, a snapshot of `Scraper.version` at creation (the
  contract's reproducibility rule), plus `organization_id`,
  `project_id`, `scraper_id`, `status`, `requested_by`, timestamps.
- `scrape_runs`: one attempt against one target. `id` is intended to
  be used as `ExecutionContext.execution_id`. Retries (Phase 5) are
  additional rows with a higher `attempt_number`, never overwrites.
  `UNIQUE(job_id, target_id, attempt_number)`.

Statuses (String + CheckConstraint, hand-synced with migration 0004,
matching Phase 1-2 convention; a unit test executes the migration's
`upgrade()` against a recorder and fails if the schema drifts from
the models):

- Job: `PENDING -> RUNNING -> SUCCEEDED | FAILED`, plus
  `PENDING -> FAILED`. Terminal states are final.
- Run: `RUNNING -> SUCCEEDED | FAILED`. Terminal states are final.

A job's final status is derived, not asserted by the caller: SUCCEEDED
iff it has at least one run and the **latest attempt of every target**
succeeded; otherwise FAILED. A job that executed nothing did not
succeed. Finalizing a job with an unfinished run is refused.

Not included on purpose: `idempotency_key`, `retry_count`, `QUEUED`,
`CANCELLED` — those are dispatch/queue concerns (Phase 5) and would
be speculative now. Phase 5 adds them in migration 0005.

### 3. Tenant isolation: denormalized `organization_id`, filtered everywhere

Both tables carry `organization_id` (NOT NULL, FK to organizations,
CASCADE). The service takes it from a caller-verified source (ADR-004
pattern) and **every query filters on it**. `project_id` is never
accepted from callers: it is derived from the scraper's real project,
and `create_job` joins scraper -> project and filters by organization,
so a scraper from another tenant is "not found". A target must belong
to the job's own scraper. A job/run/scraper/target from another
tenant behaves identically to a nonexistent one (same exception /
`None`), the service-level equivalent of the 404-not-403 IDOR rule.
No RLS (ADR-004 still stands).

Consequence of ADR-004's accepted risk: isolation is only as strong as
every path through this service. Reads and writes were kept to a
small set of functions that all take `organization_id`; any future
query added here must do the same, and must ship its own cross-tenant
test.

### 4. What is stored

Exactly the classified outcome the engine returned: `final_url`,
`http_status`, `content_type`, `response_size_bytes`, `duration_ms`,
allowlisted headers, and `error_category` / `error_message` /
`error_retryable`. Nothing else:

- No response body (the Phase 3 engine does not return one).
- No scraper `configuration`, no `credential_reference` value.
- Response headers re-filtered in the service against the same
  4-name allowlist as the HTTP engine (defense in depth; a unit test
  asserts the two lists stay equal).
- `target_url` is a snapshot, so history stays readable after the
  target is edited or deleted (`target_id` is ON DELETE SET NULL).
- Strings are truncated to column size (URLs 2048, error message 500,
  content type 255, header values 500) rather than failing the write.

Accepted risk: `target_url` / `final_url` are stored as-is. A URL
containing a token in its query string is therefore stored in
plaintext. No redaction mechanism is invented in this phase; if
required, it needs its own decision.

### 5. Integrity enforced in the database as well

CheckConstraints mirror `ExecutionResult.__post_init__`: a SUCCEEDED
run has no error fields; a FAILED run has category, message and
retryable; a RUNNING run has no outcome and no `finished_at`; terminal
runs have `finished_at`. `error_category` is constrained to the
`ErrorCategory` set, and a unit test fails if it drifts from
`worker.core.errors.ErrorCategory`.

### 6. No endpoints, no audit-log rows

No HTTP endpoints in Phase 4 (read endpoints belong with `POST
/execute` in Phase 5, with RBAC and IDOR tests). Runs do not write
`audit_logs` rows: the tables are themselves the history, and
user-attributed audit events belong with the action that creates a job
on a user's behalf. `jobs.requested_by` already records who.

### 7. Delete behavior

CASCADE through scraper / project / organization (consistent with the
existing hierarchy); SET NULL for `target_id` and `requested_by`.
Trade-off: hard-deleting a scraper, project or organization deletes its
execution history. Archiving (the normal lifecycle) does not.

### 8. Migration 0004

Adds two tables and their indexes only; alters nothing from
0001-0003. `downgrade()` is a pure drop in reverse order with no
earlier-phase data at risk, so CI's up / down / up check applies
unchanged.

## Out of scope (not built, by design)

Retry orchestration, queue dispatch / Celery scraping task, scheduler,
`POST /execute` and any new endpoint, a real `CredentialProvider`,
Browser/Scrapy engines, response-body storage, URL redaction, enforcing
that a scraper is `ACTIVE` before a job may be created (a dispatch
policy, Phase 5), and recording a job when the engine raises an
unclassified exception (a programming bug, not an `ExecutionResult`).

## Known limitations

- Nothing in the running system calls the service yet; only tests do.
- Run history is lost on hard delete of a scraper/project/organization.
- Unverified until CI/local runs: see `PHASE_4_REPORT.md`.

## Phase 5 handoff

Phase 5 must decide how the worker reaches the database, build
`ExecutionContext` from a `scrape_runs` row (`id` -> `execution_id`),
add dispatch fields (`idempotency_key`, `retry_count`) in 0005, and
add tenant-scoped endpoints with cross-tenant and IDOR tests.
