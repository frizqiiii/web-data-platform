# Phase 4.5 Report — Model/Migration Drift Cleanup

Status: **IMPLEMENTED; verified locally** (`alembic check` clean on a
fresh database at head, ruff, mypy, 185 tests). GitHub Actions on the
PR is still pending; see section 4.

## 1. Why

`alembic check`, run for the first time during Phase 4 verification,
reported 15 differences between the Phase 1-2 models and what
migrations 0002/0003 actually created. None involved Phase 4 tables.
CI never ran `alembic check`, so the drift was invisible.

## 2. Decision

Align the **models** to the migrations, not the other way around:
migrations 0001-0003 are applied history and must not be edited, and
the real database schema is already what they describe. **No database
change, no new migration.** Only model-side declarations change.

## 3. Changes

| Table | Drift found | Model change |
|---|---|---|
| `organization_members` | indexes named `ix_org_members_*` in the DB; `index=True` auto-named them `ix_organization_members_*` | removed `index=True`; declared `Index("ix_org_members_user_id")` and `Index("ix_org_members_organization_id")` |
| `organizations.slug` | DB has unique CONSTRAINT `uq_organizations_slug` + non-unique index `ix_organizations_slug`; model had one unique index | `UniqueConstraint("slug", name="uq_organizations_slug")` + `Index("ix_organizations_slug")` |
| `users.email` | same pattern (`uq_users_email` + `ix_users_email`) | same fix |
| `projects` | `ix_projects_organization_id`, `ix_projects_status` existed only in the migration | declared in `__table_args__` |
| `scrapers` | `ix_scrapers_project_id`, `ix_scrapers_status` existed only in the migration | declared |
| `targets` | `ix_targets_scraper_id` existed only in the migration | declared |

Also: `.github/workflows/ci.yml` gains a step
`alembic check` (after the up/down/up steps, before tests), so any
future model/migration drift fails CI.

Behavior is unchanged: uniqueness on `users.email` and
`organizations.slug` is still enforced (now by the named constraint),
and the same columns are indexed.

## 4. Verification

Local run (maintainer, Kali, Python 3.14.7, fresh PostgreSQL 16
container, migrations applied from empty 0001 -> 0004), taken from
pasted logs; not re-run by the author.

| Check | Status | Evidence |
|---|---|---|
| `alembic check` after `upgrade head` | **PASS** (local) | "No new upgrade operations detected." (previously 15 operations) |
| `ruff check .` / `ruff format --check .` | **PASS** (local) | "All checks passed!", "126 files already formatted" |
| `mypy apps/` | **PASS** (local) | "Success: no issues found in 98 source files" |
| Full test suite | **PASS** (local) | `185 passed, 1 warning` (same count as before; the warning is the pre-existing Starlette 422 deprecation) |
| GitHub Actions incl. the new `alembic check` step (Python 3.12) | **PENDING** | |

Note: an earlier local run showed 19 integration failures with
"Connection refused ... 55432"; that was the test Postgres container
not running (it had been removed after the Phase 4 PR), not a code
problem. They passed once the container was recreated.

## 5. Commands (repo root, with the test DB from Phase 4 running)

```bash
export DATABASE_URL=postgresql+asyncpg://platform:platform@localhost:55432/platform_test
export REDIS_URL=redis://localhost:56379/0
export ENVIRONMENT=test
uv run alembic -c migrations/alembic.ini upgrade head
uv run alembic -c migrations/alembic.ini check      # expect: No new upgrade operations detected
uv run ruff check . && uv run ruff format --check . && uv run mypy apps/
uv run pytest -q                                   # expect 185 passed
```

If `check` still lists an operation, send it; the fix is another
declaration in the models, never an edit to migrations 0001-0004.
