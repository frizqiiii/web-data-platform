# Phase 4.5 Report — Model/Migration Drift Cleanup

Status: **IMPLEMENTED; NOT YET VERIFIED.** The decisive check
(`alembic check` reporting no drift) has not been run yet; see
section 4.

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

| Check | Status | Evidence |
|---|---|---|
| `ruff check` / `ruff format --check` on the six models | **PASS** (authoring sandbox) | all checks passed, files formatted |
| Syntax of changed files | **PASS** | `py_compile` |
| `alembic check` reports "No new upgrade operations detected" | **UNVERIFIED** | must be run against a DB at head; the 15 reported operations map one-to-one to the changes above, but an unlisted difference could surface only when run |
| mypy, full pytest (185 expected) | **UNVERIFIED** | not run by the author (dependencies unavailable in the sandbox) |
| GitHub Actions (incl. the new `alembic check` step) | **PENDING** | |

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
