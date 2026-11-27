# Phase 4 Report — Execution History Persistence

Status: **IMPLEMENTED; verified locally on the maintainer's machine
(logs pasted into the Phase 4 chat): ruff, format, mypy, migrations
up/down/up, 185 tests. GitHub Actions CI on the PR is still pending.**
Nothing below is claimed PASS unless it says what was
actually executed.

## 1. Scope (as approved)

Persist execution history: `jobs` and `scrape_runs` tables (migration
0004), models, and a tenant-scoped service that records an engine's
`ExecutionResult` / `ExecutionError`. Decisions and reasoning: see
`docs/decisions/ADR-010-execution-history-persistence.md`.

Explicitly NOT built: retry orchestration, queue dispatch / Celery
scraping task, scheduler, `POST /execute` or any endpoint, real
`CredentialProvider`, Browser/Scrapy engines, response-body storage,
URL redaction, `audit_logs` rows for runs.

## 2. Repository audit findings (start of phase)

- `execution-command-contract.md` reserved `jobs`/`scrape_runs` but
  specified neither schema; job-vs-run granularity and the
  persistence home (worker must not import `app.*`; worker image has
  no SQLAlchemy) were unresolved. Resolved in ADR-010.
- Doc drift found and fixed: README §16 and the contract-doc title
  still described Phase 2/3 state; `PHASE_3_REPORT.md` listed docker
  build as UNVERIFIED although the maintainer later verified it.

## 3. What changed

New:
- `migrations/versions/0004_phase4_execution_history.py`
- `apps/api/app/models/job.py`, `apps/api/app/models/scrape_run.py`
- `apps/api/app/services/execution_history_service.py`
- `apps/api/tests/unit/test_execution_history.py`
- `apps/api/tests/integration/test_execution_history_db.py`
- `docs/decisions/ADR-010-execution-history-persistence.md`
- `PHASE_4_REPORT.md`

Modified (small, additive): `apps/api/app/models/__init__.py`
(registers the two models for Alembic), `README.md` (§16),
`docs/architecture/execution-command-contract.md`,
`docs/architecture/engine-capability-matrix.md`, `PHASE_3_REPORT.md`
(docker row only).

Untouched: migrations 0001-0003, all Phase 1-3 behavior, the worker,
`pyproject.toml`, `uv.lock` (no new dependencies).

## 4. Verification — what was and was not run

Environment of the local run: Kali, Python 3.14.7, PostgreSQL 16
(docker `postgres:16-alpine`), Redis 7, `ENVIRONMENT=test`. CI uses
Python 3.12, so CI remains a separate, still-pending confirmation.
Local results below are taken from logs the maintainer pasted; they
were not re-run by the author.

| Check | Status | Evidence |
|---|---|---|
| `ruff check` / `ruff format --check` on the new/changed files | **PASS** (authoring sandbox, ruff 0.16.9) | "All checks passed" |
| `ruff check .` / `ruff format --check .` whole repo, maintainer's ruff 0.16.8 | **PASS** (local) | "All checks passed!", "125 files already formatted" |
| `mypy apps/` | **PASS** (local) | "Success: no issues found in 98 source files" after fixing 4 real errors (2x `no-any-return` in the service, 1 variable re-typed in an integration test, 1 `ModuleType` attribute assignment in a unit test). Protocol-vs-dataclass typing passed |
| Migrations from empty DB: `upgrade head` (0001→0004), `downgrade -1` (0004→0003), `upgrade head` | **PASS** (local) | alembic log shows each step, no errors |
| Unit tests incl. `test_execution_history.py` | **PASS** (local) | 185 passed in the full run; that file measured 100% executed, no failures listed |
| Integration tests `test_execution_history_db.py` against real Postgres | **PASS** (local) | 8 passed: round trip across sessions, job-fails path, cross-tenant denied, IDOR denied, duplicate attempt (service + DB), inconsistent rows rejected by DB, history survives target deletion, start_run needs RUNNING job |
| Full regression (Phase 0-3 + Phase 4) | **PASS** (local) | `185 passed, 1 warning` (warning is a pre-existing Starlette 422 deprecation) |
| `alembic check` (model vs DB drift) | **FAIL — pre-existing, not caused by Phase 4** | see below |
| GitHub Actions on the PR | **PENDING** | not yet pushed/observed |

### `alembic check` finding (pre-existing drift)

`alembic check` reports differences, but every one concerns tables from
migrations 0002/0003, and none mention `jobs` or `scrape_runs`:
index names `ix_org_members_*` (migration) vs `ix_organization_members_*`
(model), `organizations.slug` and `users.email` unique CONSTRAINT +
non-unique index (migration) vs unique INDEX (model), and indexes that
migration 0003 creates but the models do not declare
(`ix_projects_*`, `ix_scrapers_*`, `ix_targets_scraper_id`).
So Phase 4 introduces no drift, but the Phase 1-2 models and
migrations were never reconciled (CI does not run `alembic check`, so
this was invisible). Migrations 0001-0003 must not be edited; the fix
(align models, or add a corrective migration) is a separate, explicitly
approved change and is NOT part of Phase 4.

**Follow-up:** addressed in Phase 4.5 (`PHASE_4_5_REPORT.md`) by
aligning the models to the migrations and adding `alembic check` to CI.

The unit test `test_migration_0004_matches_models` executes the
migration's `upgrade()` against a recording stand-in for `alembic.op`
and compares columns, CHECK text, foreign keys + ON DELETE, indexes
and unique constraints with the models. It is the main guard against
model/migration drift, but it has itself never been run.

## 5. Security tests included

Cross-tenant-denied (`test_cross_tenant_access_is_denied`): org B
using org A's job/run/scraper ids cannot read, list, create, start,
record into or finalize anything, and org A's data is unchanged
afterwards. IDOR-denied
(`test_idor_target_from_another_scraper_or_tenant_is_denied`): a
target id from another tenant, or a nonexistent one, is rejected
identically inside a legitimate job. Plus DB-level rejection of
inconsistent/out-of-range rows, duplicate attempts, and history
surviving target deletion.

There are no endpoints, so there is no HTTP-level IDOR test; the
service is the only tenant boundary until Phase 5 adds endpoints.

## 6. Known limitations / residual risks

- Nothing in the running system calls the service yet.
- URLs are stored as-is: a token in a target URL's query string is
  stored in plaintext (ADR-010 §4). No redaction was invented.
- Hard-deleting a scraper/project/organization deletes its history.
- `create_job` does not require the scraper to be `ACTIVE`
  (dispatch policy, Phase 5).
- An engine raising an unclassified exception is not recorded; a run
  would stay `RUNNING`. Needs a decision when dispatch exists.
- No unique guard prevents two concurrent `start_run` calls racing on
  the same attempt other than the DB unique constraint (which does
  catch it as `IntegrityError`, not `DuplicateAttempt`).
- Pre-existing model/migration drift for Phase 1-2 tables (see
  section 4) is unresolved and out of Phase 4 scope.
- Phase 1 backlog unchanged: refresh-token reuse detection not
  integration-tested against real Redis; no `audit_logs` content test.
- Browser/Scrapy engines and a real `CredentialProvider` still absent.

## 7. Commands to run (Kali, repo root)

```bash
uv sync --group api --group worker --group scheduler --group dev
uv run ruff check . && uv run ruff format --check .
uv run mypy apps/
docker compose up -d postgres redis   # use your port override if 5432 is taken
export DATABASE_URL=postgresql+asyncpg://platform:platform@localhost:5432/platform
uv run alembic -c migrations/alembic.ini upgrade head
uv run alembic -c migrations/alembic.ini downgrade -1
uv run alembic -c migrations/alembic.ini upgrade head
uv run alembic -c migrations/alembic.ini check      # currently FAILS on pre-existing Phase 1-2 drift only (section 4)
uv run pytest apps/api/tests/unit/test_execution_history.py -v
uv run pytest apps/api/tests/integration/test_execution_history_db.py -m integration -v
uv run pytest --cov --cov-report=term-missing       # full regression
```

Remaining before merge: confirm GitHub Actions is green on the PR
(Python 3.12) and update the PENDING row in section 4.

## 8. Phase 5 handoff

See ADR-010 "Phase 5 handoff": decide how the worker reaches the DB,
build `ExecutionContext` from a `scrape_runs` row, add
`idempotency_key` / `retry_count` (migration 0005), add tenant-scoped
endpoints with cross-tenant and IDOR tests, and decide how an
unclassified engine exception is recorded.
