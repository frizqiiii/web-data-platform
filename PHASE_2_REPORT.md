# PHASE 2 — PROJECT & SCRAPER MANAGEMENT: Phase Report

**Status of this report: IMPLEMENTATION COMPLETE, VERIFICATION NOT
YET STARTED.** Identical constraint to Phase 0/1: this authoring
sandbox has no Docker, no live Postgres/Redis, no network to install
packages, and no ruff/mypy/pytest installed. Every status below is
UNVERIFIED unless stated otherwise — nothing here is claimed PASS
without real execution evidence, per the explicit implementation rule
in the Phase 2 approval message.

## 1. Files Changed

**New:**
```
apps/api/app/core/url_safety.py
apps/api/app/models/{project,scraper,target}.py
apps/api/app/schemas/{project,scraper,target,scraper_configuration}.py
apps/api/app/services/{project_service,scraper_service,target_service}.py
apps/api/app/modules/projects/router.py
apps/api/app/modules/scrapers/router.py
apps/api/app/modules/targets/router.py
apps/api/tests/unit/{test_url_safety,test_lifecycle_state_machines,test_scraper_configuration}.py
apps/api/tests/integration/test_project_scraper_security.py
migrations/versions/0003_phase2_projects_scrapers.py
docs/decisions/{ADR-005-scraper-configuration-jsonb,ADR-006-ssrf-validation-strategy,ADR-007-response-format-deviation}.md
docs/architecture/execution-command-contract.md
```

**Modified:**
```
apps/api/app/models/__init__.py   (registers Project/Scraper/Target for Alembic)
apps/api/app/api/deps.py          (added require_project(_role), require_scraper(_role), require_target(_role))
apps/api/app/main.py              (wired 5 new routers)
README.md                          (Known Limitations updated through Phase 2)
```

**Untouched, per explicit rule:** `migrations/versions/0001_*.py`,
`migrations/versions/0002_*.py`. Migration `0003` has
`down_revision = "0002"`.

## 2. Architecture Implemented

- **Domain model**: `Project` (org-scoped) -> `Scraper` (project-scoped,
  `engine` + JSONB `configuration`) -> `Target` (scraper-scoped, URL).
  No `organization_id` on `Scraper`/`Target` — tenant ownership is
  always derived by walking the ownership chain, never read from a
  column trusted in isolation.
- **Lifecycle**: `Project` DRAFT/ACTIVE/PAUSED/ARCHIVED,
  `Scraper` DRAFT/ACTIVE/DISABLED/ARCHIVED (deliberately simpler, no
  PAUSED — see ADR reasoning in the model docstrings). Both enforced
  via an explicit transition-graph dict, never inferred.
- **Tenant isolation**: `require_project`, `require_scraper`,
  `require_target` in `app/api/deps.py` — each resolves organization
  membership by walking the resource's ownership chain and returns
  404 for both "doesn't exist" and "exists but you're not a member",
  identical to Phase 1's IDOR mitigation pattern.
- **RBAC**: reused Phase 1's `role_satisfies` unchanged — no new role
  system, matrix as planned (MANAGER+ for writes, ADMIN+ for
  archive, VIEWER+ for reads, OPERATOR+ for enable/disable).
- **SSRF**: `app/core/url_safety.py`, injectable-resolver design so
  the blocking logic is unit-testable without real DNS.
- **Configuration validation**: discriminated-union Pydantic schema
  per engine, `extra="forbid"` (untrusted external input, unlike
  Phase 1's `.env`-derived Settings which needed `extra="ignore"` —
  different trust boundary, different rule, deliberately).

## 3. Migration

`0003_phase2_projects_scrapers`, depends on `0002`. Creates `projects`,
`scrapers`, `targets` with FKs (CASCADE on parent delete), unique
constraints per-org/per-project slug, CheckConstraints for
status/engine enums (String + CheckConstraint per Decision #3, not
native Postgres ENUM), and indexes on every foreign key column plus
`status`. `downgrade()` reverses in dependency order (targets ->
scrapers -> projects), does not touch `0001`/`0002`'s tables.

**Never run against a real database in this sandbox** — same as every
migration in this repo before CI actually runs it.

## 4. Endpoints Implemented

```
POST   /api/v1/projects?organization_id={id}
GET    /api/v1/projects?organization_id={id}
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}                    (name/description/status)
DELETE /api/v1/projects/{id}                    (soft: -> ARCHIVED)

POST   /api/v1/projects/{project_id}/scrapers
GET    /api/v1/projects/{project_id}/scrapers
GET    /api/v1/scrapers/{id}
PATCH  /api/v1/scrapers/{id}                    (name/configuration/credential_reference/status)
DELETE /api/v1/scrapers/{id}                    (soft: -> ARCHIVED)

POST   /api/v1/scrapers/{scraper_id}/targets
GET    /api/v1/scrapers/{scraper_id}/targets
PATCH  /api/v1/targets/{id}
DELETE /api/v1/targets/{id}                     (hard delete)
```

**Design note not in the original plan, decided during implementation:**
`organization_id` for `POST`/`GET /projects` is a **query parameter**,
not a request-body field — this let `require_membership`/`require_role`
(Phase 1, completely unmodified) be reused directly, since FastAPI
treats a dependency's plain-typed parameter as a query parameter
automatically when absent from the route's path template. No new
"read org from body" mechanism was built. This is a smaller-than-
planned implementation, which is the right direction of surprise.

## 5. Tests Written

**Unit (no infra):**
- `test_url_safety.py` — scheme rejection, literal dangerous IPs
  (loopback/private/link-local/metadata/multicast), hostname
  resolution via a fake resolver (safe and unsafe), fail-closed on
  no-resolution and mixed-safety multi-IP results
- `test_lifecycle_state_machines.py` — valid/invalid transitions for
  both Project and Scraper, explicit regression guard that Scraper's
  graph has no PAUSED state
- `test_scraper_configuration.py` — per-engine defaults, `extra="forbid"`
  rejection, numeric bounds, discriminated-union dispatch by `engine`

**Integration (`pytest.mark.integration`, needs real Postgres+Redis):**
- `test_full_project_scraper_target_flow` — full CRUD + lifecycle
  transitions (including a deliberately invalid one, expecting 409)
  for Project, Scraper, and Target end to end
- `test_ssrf_target_creation_rejected` — real HTTP-layer rejection of
  a cloud-metadata URL and a loopback URL (422)
- `test_cross_tenant_project_and_scraper_access_denied` (**mandatory**)
- `test_idor_non_member_denied_for_project_and_scraper` (**mandatory**)
- `test_viewer_role_cannot_create_project` (**mandatory** — see honest
  caveat below)
- `test_suspended_user_denied_on_project_endpoint` (**mandatory**)

**Honest caveat on the RBAC test**: there is no API endpoint (Phase 1
or Phase 2) to invite an organization member with a specific
non-OWNER role. `test_viewer_role_cannot_create_project` creates the
VIEWER membership by writing directly to the database via the app's
own `AsyncSessionLocal`, not through the API. This is legitimate test
setup (every other piece of state in that test IS created through the
API), but it's worth being explicit that the "invite a member"
feature itself remains untested because it doesn't exist yet.

## 6. Security Review (threats from the Phase 2 plan, mapped to evidence)

| Threat | Mitigation | Test |
|---|---|---|
| IDOR | `require_project`/`require_scraper`/`require_target`, 404 for non-members | `test_idor_non_member_denied_for_project_and_scraper` |
| Tenant escape | organization_id always derived server-side via ownership-chain walk | `test_cross_tenant_project_and_scraper_access_denied` |
| SSRF | `url_safety.validate_target_url`, literal + resolved IP blocking | `test_url_safety.py` (unit) + `test_ssrf_target_creation_rejected` (integration) |
| Privilege escalation | `require_*_role` on every write endpoint | `test_viewer_role_cannot_create_project` |
| Malicious configuration | `extra="forbid"` + numeric bounds per engine schema | `test_scraper_configuration.py` |
| Secret exposure | `credential_reference` is a bare string, never resolved; `configuration` payloads never written to audit metadata wholesale | code review (see Section 9 below — no dedicated log-scraping test was written for this one, an honest gap) |
| Suspended account | `get_current_user` (Phase 1, unmodified) already checks `is_active` | `test_suspended_user_denied_on_project_endpoint` |

## 7. Audit Events Implemented

`PROJECT_CREATED`, `PROJECT_UPDATED`, `PROJECT_ACTIVATED`,
`PROJECT_PAUSED`, `PROJECT_ARCHIVED`, `SCRAPER_CREATED`,
`SCRAPER_UPDATED`, `SCRAPER_CONFIGURATION_CHANGED`,
`SCRAPER_ENABLED`, `SCRAPER_DISABLED`, `SCRAPER_ARCHIVED`,
`TARGET_CREATED`, `TARGET_UPDATED`, `TARGET_DELETED`. None include
plaintext `configuration` or credential material.

## 7a. Round 1 findings (real execution, first run against installed tools)

`uv sync` succeeded cleanly. `ruff check`, `ruff format --check`, and
`mypy` then found real issues:

| # | Tool | Finding | Fix |
|---|---|---|---|
| 1 | `ruff check` (I001 ×3) | Import order in `main.py`, `test_scraper_configuration.py`, `test_url_safety.py` | Reordered to match ruff's isort output (established Phase 0/1 pattern) |
| 2 | `ruff check` (B008 ×14) | `require_project_role(...)`/`require_scraper_role(...)`/`require_target_role(...)` called inside `Depends(...)` — same false-positive class as Phase 1's `require_role` | Added all three to `extend-immutable-calls` in `pyproject.toml` |
| 3 | `ruff check` (UP007) | `Union[...]` instead of `X \| Y` in `scraper_configuration.py` | Converted to `HttpEngineConfig \| BrowserEngineConfig \| ScrapyEngineConfig` |
| 4 | `ruff format` (4 files, incl. an `.md`) | Multi-line calls that fit on one line; a markdown code block's comment alignment | Collapsed/reformatted to match |
| 5 | `mypy` | `url_safety.py`: `socket.getaddrinfo`'s sockaddr tuple typed as `str \| int` across IPv4/IPv6 stub variants, breaking a `list[str]` comprehension | Wrapped with explicit `str(...)` |
| 6 | `mypy` | `scrapers/router.py`: `created_by=project.created_by` (`UUID \| None`) passed where `create_scraper` expected non-optional `UUID` | **This surfaced a real logic bug, not just a type mismatch**: the scraper's `created_by` was being set to the *project's* original creator, not the user actually creating the scraper. Fixed by adding `current_user: User = Depends(get_current_user)` to the endpoint and using `current_user.id` instead — the type error was mypy correctly catching a wrong value, not just a wrong annotation |
| 7 | `mypy` (×3) | `test_project_scraper_security.py`: `resp.json()["id"]` returning `Any` from functions declared to return `str` | Wrapped with explicit `str(...)` at each of the 3 call sites |

**Result after fixes**: `pytest -m "not integration"` — **65 passed,
11 deselected** (integration tests). This is real, user-executed
evidence. Item #6 above is the most important finding of this round:
mypy's type check caught an actual audit-trail correctness bug
(wrong `created_by` attribution) that no test had been written to
catch, before it reached CI.

**Not yet re-verified**: `ruff check`, `ruff format --check`, and
`mypy` need to be re-run against these fixes.

## 8. Verification Results

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | `ruff check` | **UNVERIFIED (fix applied, not re-run)** | found 16 real errors round 1 (Section 7a), all fixed — re-run pending |
| 2 | `ruff format --check` | **UNVERIFIED (fix applied, not re-run)** | found 4 files round 1, fixed — re-run pending |
| 3 | `mypy apps/` | **UNVERIFIED (fix applied, not re-run)** | found 5 real errors round 1 including one real logic bug (Section 7a #6) — re-run pending |
| 4 | `pytest -m "not integration"` (new unit tests) | **PASS** | **65 passed, 11 deselected** — actually run by the user, real output |
| 5 | `alembic upgrade head` (0002->0003) | **UNVERIFIED** | needs real Postgres, hand-written migration |
| 6 | `alembic downgrade -1` / `upgrade head` again | **UNVERIFIED** | same |
| 7 | Full CRUD flow (integration) | **UNVERIFIED** | needs CI |
| 8 | SSRF rejection (integration) | **UNVERIFIED** | needs CI |
| 9 | Cross-tenant test | **UNVERIFIED** | needs CI — this is the most important row, same as it was for Phase 1 before real verification |
| 10 | IDOR test | **UNVERIFIED** | needs CI |
| 11 | Unauthorized role test | **UNVERIFIED** | needs CI |
| 12 | Suspended user test | **UNVERIFIED** | needs CI |
| 13 | CI (full pipeline) | **UNVERIFIED** | not yet pushed |
| 14 | ADR-005, ADR-006, ADR-007 | **PASS** | files exist, reviewed by inspection — genuinely doesn't need infra |

## 9. Known Risks Flagged Honestly (found by reasoning, not by running)

- **mypy on `apply_status_transition(_FakeProject(...), ...)` in
  `test_lifecycle_state_machines.py`**: this passes a duck-typed fake
  object where the function signature expects a real `Project`/
  `Scraper` ORM instance. Added `# type: ignore[arg-type]` at each
  call site rather than restructuring the function to accept a
  Protocol — could not confirm this is the exact error mypy will
  raise (or that the ignore code is precisely right) without actually
  running mypy.
- **`ScraperConfiguration` discriminated union + `TypeAdapter`**:
  Pydantic's discriminated unions require the discriminator field to
  have a consistent literal type across all union members
  (`Literal[ScraperEngine.HTTP]` etc.) — believed correct by
  following Pydantic v2's documented pattern, but never actually
  exercised against the installed Pydantic version (2.13.x per
  Phase 1's `uv.lock`).
- **`db.scalars(select(Project).where(...))` return type** in
  `project_service.list_projects_for_organization` and the analogous
  scraper/target functions: Phase 1 hit a real mypy "Any-return" issue
  on a similar SQLAlchemy pattern (`organization_service.py`) —  the
  same class of warning may reappear here and wasn't preemptively
  fixed, to avoid guessing at a fix for an error that might not even
  occur with this exact query shape.
- **Nested router path parameter naming**: `project_scrapers_router`
  uses `{project_id}` and is included via `app.include_router(...,
  prefix="/api/v1")` — FastAPI's automatic path-parameter-to-function-
  parameter binding for `require_project`'s `project_id: uuid.UUID`
  argument depends on the outer path template's parameter name
  matching exactly. Believed correct (both are literally named
  `project_id`) but never executed.

## 10. Known Limitations

- No endpoint exists to invite an organization member with a specific
  role (affects both Phase 1 and Phase 2 — noted here because Phase
  2's RBAC test had to work around it).
- `Scraper.configuration` is not frozen on activation — it can be
  edited while `ACTIVE`; only `version` increments, no snapshot
  history (deliberate scope cut, ADR-005 and Section 3 of the
  Phase 2 plan).
- `credential_reference` has no backing store (Decision #2 — this is
  intentional, not a bug).
- SSRF validation happens once, at Target create/update — Phase 3
  re-validation is a recorded, unenforced-by-code dependency (ADR-006).

## 11. Final Phase 2 Status

**UNVERIFIED.**

Not PASS — nothing in Sections 8's table has been executed. Not FAIL
— nothing has failed either, because nothing has run. This is the
identical starting position Phase 0 and Phase 1 were in before the
user ran real commands and found real bugs (Phase 0: 2 bugs; Phase 1:
6 bugs across 5 rounds). Expect the same here — do not be surprised
by a multi-round fix cycle; that is the process working.

**Next required steps (same loop as Phase 0/1):**
1. Sync the delta package, run `uv sync`, `ruff check`, `ruff format
   --check`, `mypy apps/`, `pytest -m "not integration"` locally.
2. Fix whatever those find, report results back.
3. Push, confirm CI green including every mandatory security test in
   Section 5.
4. Only then does this report's status change to PASS — and per the
   Phase 2 approval's explicit instruction, Phase 3 does not start
   until that happens and is explicitly reviewed.
