# Execution Command Contract (design only — not implemented)

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

## Explicit non-goals of this document

- Not a Celery task signature.
- Not a database schema (that's Phase 4's `jobs`/`scrape_runs`
  tables).
- Not a guarantee this shape survives unchanged into Phase 4/5 — it's
  a starting point informed by what Phase 2's domain model actually
  contains, subject to revision when Phase 4 is actually planned.
