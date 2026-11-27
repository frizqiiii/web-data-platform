# Execution Command Contract (dispatch: design only; persistence: Phase 4)

This documents the shape of the message that will eventually flow
`API -> Domain -> Execution Command -> Queue -> Worker`, per Master
Prompt Section 15's request to design this interface in Phase 2
without building it. **No code in this repository constructs, sends,
or consumes this payload yet** — there is no `jobs` table (Phase 4),
no queue dispatch (Phase 5), and no worker consuming it (Phase 5/3).
Writing the DTO as real code now, with nothing on either end of it,
would just be dead code — this document exists so Phase 4/5 don't
have to guess at the shape Phase 2's data model implies.

## Payload shape

```python
{
    "job_id": "uuid",  # Phase 4: primary key of a `jobs` row
    "organization_id": "uuid",  # for worker-side logging/isolation,
    # NOT an authorization source — the
    # worker trusts the job row, not this
    # field, exactly like Phase 1/2's rule
    # for client-supplied organization_id
    "project_id": "uuid",
    "scraper_id": "uuid",
    "scraper_version": 3,  # snapshot of Scraper.version at
    # dispatch time — NOT "current version"
    # — for reproducibility, so a
    # configuration edit after dispatch
    # doesn't change what already-queued
    # work executes
    "idempotency_key": "uuid",  # Phase 5: prevents duplicate dispatch
    # of the same logical job
    "retry_count": 0,
}
```

## Why `scraper_version` matters

`Scraper.configuration` can be edited while `status=ACTIVE` (Phase 2
does not freeze configuration on activation — see ADR-005). Without
snapshotting the version at dispatch time, a job could run against a
configuration that was edited mid-flight. Phase 4's `jobs` table
should record `scraper_version`, not just `scraper_id`, so a run's
result can always be traced back to the exact configuration that
produced it.

## Phase 3 update: the worker-side counterpart now exists

This document is still design-only for the *dispatch* side — there is
still no `jobs` table, no queue, and nothing in this repository
constructs or sends the payload above. What changed in Phase 3 is
that the *worker* side of the eventual pipeline now exists and is
real code: `worker.core.execution.ExecutionContext` (see
`apps/worker/worker/core/execution.py`).

`ExecutionContext` is deliberately a different, narrower shape than
the command payload above — it is NOT this document's payload with a
different name:

- It carries `target_id` and `url` (the specific target being
  fetched), `configuration` (the resolved engine configuration dict),
  `requested_at`, and `timeout_seconds` — none of which belong in a
  queue dispatch message, since they're either derived from
  `target_id` or are execution-mechanics, not job-identity.
- It does NOT carry `idempotency_key` or `retry_count` — those are
  dispatch/queue concerns (Phase 5), not execution concerns; an
  `EngineAdapter` neither knows nor cares how many times this
  execution has been attempted before.
- It DOES carry `scraper_version`, for the same reproducibility reason
  this document already gives for the command payload.

The expected relationship, once Phase 4/5 exist: whatever consumes
the command payload above (a Celery task) is responsible for loading
the real `Scraper`/`Target` rows it identifies and constructing an
`ExecutionContext` snapshot from them — the command payload is "which
job", `ExecutionContext` is "what to actually do, self-contained." An
`EngineAdapter` (Phase 3, `worker/engines/`) never sees the command
payload at all.

## Phase 4 update: persistence now exists, dispatch still does not

Phase 4 (ADR-010, migration 0004) added the `jobs` and `scrape_runs`
tables and `app/services/execution_history_service.py`. What this
changes about the payload above:

- `job_id` is now a real primary key of `jobs`. A job is
  **scraper-level** (as this payload implies: `scraper_id`, no
  `target_id`) and records `scraper_version` as the snapshot this
  document asked for.
- Per-target execution lives in `scrape_runs`, one row per attempt.
  `scrape_runs.id` is intended to become `ExecutionContext.
  execution_id`, so a worker's context traces back to exactly one
  persisted attempt.
- `idempotency_key` and `retry_count` are **still not implemented**:
  they are dispatch concerns and are left to Phase 5 (migration 0005).
- Still true: nothing constructs, sends or consumes this payload.
  The persistence service is only called by tests until Phase 5.

## Explicit non-goals of this document

- Not a Celery task signature.
- Not a database schema (the real schema is migration 0004 and
  ADR-010; see "Phase 4 update" below).
- Not a guarantee this shape survives unchanged into Phase 4/5 — it's
  a starting point informed by what Phase 2's domain model actually
  contains, subject to revision when Phase 4 is actually planned.
