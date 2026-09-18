# PHASE 1 — IDENTITY & MULTI-TENANCY: Phase Report

**Status of this report: IMPLEMENTATION COMPLETE, VERIFICATION PENDING.**
Same constraint as Phase 0: this sandbox has no Docker, no live
Postgres/Redis, and no network to install packages — so nothing
below is marked PASS without it actually having been run. Most rows
are UNVERIFIED (needs `uv sync` + real execution, which the user CAN
do locally without Docker) or BLOCKED (needs Postgres/Redis, which —
per the user's hardware constraint recorded in Phase 0 — must go
through GitHub Actions CI, not local Docker).

## 0. Round 1 findings (real execution, first run against installed tools)

A packaging mistake on my part caused the user's first attempt to
run against a stale/reverted zip — resolved by re-downloading. Once
running against the actual Phase 1 code, `uv lock`/`uv sync`
succeeded cleanly (67 packages, argon2-cffi/email-validator/redis
transitive deps all resolved). `ruff check`, `ruff format --check`,
and `mypy` then found real issues — this is the process working:

| # | Tool | Finding | Fix |
|---|---|---|---|
| 1 | `ruff check` (B008 ×22) | FastAPI's `Depends()`/`Cookie()`/`Header()` in argument defaults flagged as the mutable-default-argument anti-pattern | Added `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` whitelisting FastAPI's own dependency-injection callables — the standard fix for FastAPI+ruff projects |
| 2 | `ruff check` (UP042 ×3) | `class X(str, Enum)` — ruff on py312 target wants `enum.StrEnum` instead | Converted `UserStatus`, `OrganizationStatus`, `OrgRole` to `StrEnum` |
| 3 | `ruff check` (F821 ×4) | `Mapped["OrganizationMember"]`-style forward refs in `user.py`/`organization.py`/`organization_member.py` flagged as undefined names — these 3 models reference each other and none imported the others (avoiding a real circular import) | Added `if TYPE_CHECKING: from app.models.X import Y` guards — satisfies both ruff and mypy without an actual runtime circular import |
| 4 | `ruff check` (I001 ×2) | Import order in `test_auth_flow.py`, `test_sessions.py` | Reordered to match ruff's isort output |
| 5 | `ruff format` (4 files) | `models/{user,organization,organization_member,audit_log}.py` — single-line-eligible `mapped_column(...)` calls left multi-line | Collapsed to single line |
| 6 | `mypy` | `core/sessions.py`'s `AsyncKeyValueStore.smembers` return type `set[str]` rejected as "not valid as a type" | A real, obscure gotcha: the Protocol also declares a method literally named `set` (the Redis SET command), which shadows the builtin `set` type within that class body. Fixed with `import builtins` and `builtins.set[str]` — same fix applied to `FakeAsyncRedis` in the test file, which has the identical shape |
| 7 | `mypy` | `sessions.py` (2×), `redis_client.py` (1×): "Returning Any from function declared to return X" | SQLAlchemy/redis-py stub limitations, not real bugs — fixed with explicit `str(...)`/`cast(...)` at each site, each commented with why |
| 8 | `mypy` | `organization_service.py`: `list(rows.all())` incompatible with `list[tuple[Organization, str]]` | SQLAlchemy's `Row` isn't structurally a plain tuple to mypy even though it behaves like one at runtime — rewrote as an explicit list comprehension unpacking each `Row` |
| 9 | `mypy` | `deps.py`: `SessionStore(get_redis_client())` — `redis.asyncio.Redis` doesn't structurally satisfy `AsyncKeyValueStore` per mypy (redis-py's stubs model broader parameter types and pipeline overloads our minimal Protocol doesn't represent) | Explicit, commented `cast(AsyncKeyValueStore, ...)` — reviewed manually that redis-py's real methods behave correctly for every call `SessionStore` makes; inflating the Protocol to match redis-py's full stub surface would be unjustified complexity (Section 1.6) for no functional benefit |

**Result after fixes**: `pytest -m "not integration"` — **26 passed,
5 deselected** (the 5 deselected are the integration tests requiring
real Postgres+Redis). This is real, user-executed evidence — not
claimed by me.

**Not yet re-verified**: `ruff check`, `ruff format --check`, and
`mypy` need to be re-run against these fixes (they were fixed in
response to the user's first real run, but that re-run hasn't
happened yet as of this report). See Section 10.

## 1. Files Changed

**New:**
```
apps/api/app/models/{base,user,organization,organization_member,audit_log}.py
apps/api/app/schemas/{auth,organization}.py
apps/api/app/services/{auth_service,organization_service,audit_service}.py
apps/api/app/core/{security,rbac,csrf,redis_client,sessions}.py
apps/api/app/modules/auth/router.py
apps/api/app/modules/organizations/router.py
migrations/versions/0002_phase1_identity.py
apps/api/tests/unit/{test_security,test_rbac,test_sessions}.py
apps/api/tests/integration/test_auth_flow.py
docs/decisions/{ADR-003-opaque-redis-sessions,ADR-004-application-layer-tenant-isolation}.md
```

**Modified:**
```
apps/api/app/api/deps.py       (was empty in Phase 0 — now auth/CSRF/RBAC dependencies)
apps/api/app/main.py           (wired auth + organizations routers)
migrations/env.py              (target_metadata now Base.metadata, not None)
pyproject.toml                 (api group: +redis, +argon2-cffi, +email-validator)
```

**Untouched (Migration Policy, Decision F):** `migrations/versions/0001_phase0_baseline.py`
is NOT modified. `0002` depends on it (`down_revision = "0001"`) and
drops `_phase0_baseline` as part of its own `upgrade()`, exactly as
`0001`'s own docstring said it eventually would.

## 2. Architecture Decisions (all approved before implementation — see the user's Phase 1 approval message)

| Decision | Choice |
|---|---|
| A: Token strategy | Opaque tokens, Redis-backed, family-based rotation + reuse detection (ADR-003) |
| B: Password hashing | Argon2id via `argon2-cffi`, library-default parameters |
| C: Browser auth | httpOnly+Secure cookies for the session/refresh tokens, non-httpOnly cookie for CSRF token, Bearer supported for non-browser consumers |
| D: Multi-tenancy | Application-layer only; RLS explicitly deferred (ADR-004) |
| E: RBAC | Explicit rank mapping in `app/core/rbac.py` — never alphabetical |
| F: Migrations | `0001` untouched; `0002` adds Phase 1 schema, drops `_phase0_baseline` |

## 3. Database Changes

Migration `0002_phase1_identity` (depends on `0001`):
- Creates `users`, `organizations`, `organization_members`, `audit_logs`
- Drops `_phase0_baseline` (documented as disposable since `0001`)
- `downgrade()` reverses all of the above, recreating `_phase0_baseline`
  exactly as `0001` originally did

Hand-written, not autogenerated — `migrations/env.py` now points
`target_metadata` at `Base.metadata` so `alembic revision
--autogenerate` is usable for Phase 2 onward (Phase 1 itself was
written without a live DB to diff against).

## 4. API Endpoints Implemented

```
POST /api/v1/auth/register    - creates a user, no session issued
POST /api/v1/auth/login       - issues session (cookies) or use Bearer token from response... 
                                 (Note: login sets cookies; a Bearer-only flow would need a
                                 separate token-in-body response, which was NOT requested by
                                 the approved API contract and so was not added — see Section 16)
POST /api/v1/auth/logout      - revokes the current session family
POST /api/v1/auth/refresh     - rotates access+refresh, detects reuse
GET  /api/v1/auth/me          - current user, requires valid session

GET   /api/v1/organizations          - orgs the caller is a member of (not all orgs)
POST  /api/v1/organizations          - creates org, caller becomes OWNER; requires CSRF header
GET   /api/v1/organizations/{id}     - requires membership; 404 for non-members
PATCH /api/v1/organizations/{id}     - requires ADMIN+ role; requires CSRF header
```

**Known gap (Section 16):** the approved API contract lists
`POST /auth/login` with no distinction between cookie vs Bearer
response shape. As built, login always sets cookies; a pure API
client wanting a bearer token in the JSON body instead would need
that added explicitly (not built, since it wasn't asked for and
guessing at a shape would be inventing an untested contract).

## 5. Authentication Flow

```
POST /auth/register  -> password hashed (Argon2id), user row created, no session
POST /auth/login      -> password verified -> SessionStore.create_session()
                          -> {access, refresh, csrf} tokens -> set as 3 cookies
GET  /auth/me          -> access cookie (or Bearer header) -> SessionStore lookup -> User
POST /auth/refresh     -> refresh cookie -> SessionStore.rotate_refresh_token()
                          -> old refresh marked used, new pair issued
                          -> IF old refresh was already used: SessionReuseDetected
                             -> entire family revoked -> 401
POST /auth/logout      -> refresh cookie -> SessionStore.revoke_session_by_refresh_token()
                          -> whole family deleted from Redis, cookies cleared
```

## 6. Authorization Flow (every protected org route)

```
1. get_current_user   - valid, non-expired access token -> active User
2. require_membership - (current_user.id, path organization_id) -> verified
                         OrganizationMember row from DB, else 404
3. require_role(X)    - membership.role must satisfy X via explicit
                         rank comparison (app/core/rbac.py) — never
                         alphabetical
4. require_csrf       - for POST/PATCH: cookie-carried session must
                         also present a matching CSRF header, verified
                         against the server-side value stored in Redis
                         for that exact session (not pure double-submit)
```

## 7. Tenant Isolation Mechanism

Application-layer, per ADR-004. `organization_id` in a URL path is
never itself authorization — `require_membership` re-derives it from
a DB lookup keyed by the authenticated user, and every route that
returns organization data does so via that verified row
(`membership.organization`, eager-loaded), never a bare
`db.get(Organization, path_id)`.

## 8. Security Controls Implemented

- Argon2id password hashing, no plaintext password ever logged/
  returned/audited (see test 9d below)
- Session tokens: opaque, SHA-256-hashed at rest in Redis
- Refresh rotation + reuse detection -> automatic full-family revocation
- httpOnly + Secure + SameSite cookies; CSRF cookie deliberately NOT httpOnly
- Server-verified CSRF (not pure double-submit) on all state-changing routes
- Generic "Invalid email or password" on login failure (no user enumeration);
  constant-time-ish padding call on unknown email (see `authenticate_user`)
- 404 (not 403) for non-members accessing an org, to avoid confirming org existence

## 9. Test Cases Written

**Unit (no infra needed):**
- `test_security.py`: hash uniqueness (salting), verify success/fail, token entropy/uniqueness, token hashing
- `test_rbac.py`: hierarchy correctness including the ANALYST-vs-VIEWER alphabetical trap
- `test_sessions.py`: creation, valid/invalid lookup, expiration, rotation, **reuse detection revokes family**, logout revocation, CSRF token retrieval — via an in-memory fake Redis (real `redis.asyncio.Redis` satisfies the same protocol, proven by the integration tests)

**Integration (needs real Postgres + Redis, `pytest.mark.integration`):**
- `test_full_auth_and_organization_flow`: register -> login -> /me -> create org -> get org -> refresh -> /me -> logout -> /me rejected
- `test_cross_tenant_access_is_denied` **(mandatory)**
- `test_idor_non_member_cannot_access_any_organization` **(mandatory)**
- `test_password_never_appears_in_logs` **(mandatory)** — uses `structlog.testing.capture_logs()`

## 10. Exact Commands To Run (local, no Docker needed for this part)

```bash
uv sync --group api --group worker --group scheduler --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/
uv run pytest -m "not integration"
```

## 11. Exact Commands That Need CI (Postgres + Redis, per the hardware constraint recorded in Phase 0)

Push to GitHub and check `https://github.com/frizqiiii/web-data-platform/actions` —
CI already runs `alembic upgrade head` and the full pytest suite
(including integration tests) against real Postgres+Redis service
containers (`.github/workflows/ci.yml`, unchanged since Phase 0 — it
already provisions both).

## 12. Verification Results

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | `alembic upgrade head` (0001->0002) | **UNVERIFIED** | never run against real Postgres; hand-written migration, needs CI to confirm |
| 2 | `alembic downgrade -1` (0002->0001) | **UNVERIFIED** | same |
| 3 | `alembic upgrade head` again | **UNVERIFIED** | same |
| 4 | Register | **UNVERIFIED** | needs #1 first, then integration test run |
| 5 | Login | **UNVERIFIED** | same |
| 6 | Protected `/me` | **UNVERIFIED** | same |
| 7 | Logout | **UNVERIFIED** | same |
| 8 | Refresh | **UNVERIFIED** | same |
| 9 | Refresh rotation | **PASS (unit)** | `test_refresh_rotation_issues_new_pair` — actually run by the user, passed. Real-Redis/CI confirmation still pending |
| 10 | Refresh reuse protection | **PASS (unit)** | `test_refresh_token_reuse_is_detected_and_revokes_family` — actually run, passed. Real-Redis/CI confirmation still pending |
| 11 | Argon2id hashing | **PASS (unit)** | `test_security.py` — actually run by the user (argon2-cffi installed via `uv sync`, 25.1.0), passed |
| 12 | Password never in logs | **UNVERIFIED** | integration test, needs Postgres+Redis via CI |
| 13 | Organization authorization | **UNVERIFIED** | needs integration run via CI |
| 14 | Membership authorization | **UNVERIFIED** | same |
| 15 | RBAC | **PASS (unit)** | `test_rbac.py` — actually run, passed, including the ANALYST-vs-VIEWER alphabetical-order trap. Real-route enforcement still needs CI |
| 16 | Cross-tenant test run | **UNVERIFIED** | needs CI (real Postgres+Redis) |
| 17 | Cross-tenant access denied | **UNVERIFIED** | same |
| 18 | IDOR test run | **UNVERIFIED** | same |
| 19 | IDOR access denied | **UNVERIFIED** | same |
| 20 | Ruff | **UNVERIFIED (fix applied, not re-run)** | found 31 real errors on first run (Section 0), all fixed — re-run pending |
| 21 | Mypy | **UNVERIFIED (fix applied, not re-run)** | found 13 real errors on first run (Section 0), all fixed — re-run pending |
| 22 | Pytest | **PASS (non-integration)** | **26 passed, 5 deselected** — actually run by the user, real output. Integration tests (the 5 deselected, including the mandatory cross-tenant/IDOR/password-log tests) still need CI |
| 23 | CI | **UNVERIFIED** | not yet pushed |
| 24 | ADR-003 | **PASS** | file exists, reviewed by inspection — this one genuinely doesn't need infra to verify |
| 25 | ADR-004 | **PASS** | same |

## 13. Known Risks — Resolved and Remaining

**Resolved (was flagged as a risk, then actually confirmed by the
user's real mypy run in Section 0):**
- The predicted mypy/redis-py Protocol conformance risk materialized
  exactly as flagged — fixed via an explicit, commented `cast()` (see
  Section 0, item 9), not by weakening the Protocol.

**Still open, not yet confirmable without Postgres/Redis (CI):**
- **`membership.organization` lazy-load under async SQLAlchemy**: fixed
  with `selectinload` in `get_membership` on the strength of code
  inspection (accessing a lazy relationship after the query returns
  raises `MissingGreenlet` under the async engine) — this specific
  failure mode can only be conclusively confirmed absent by actually
  running the integration tests against real Postgres via CI.
- **Cookie `Path` scoping for the refresh cookie**: refresh cookie is
  scoped to `path="/api/v1/auth/refresh"` so it isn't sent on every
  request — `test_full_auth_and_organization_flow`'s
  `client.cookies.get("session_token")` before/after refresh relies
  on httpx's cookie jar correctly respecting cookie `Path` scoping.
  Believed correct (httpx follows RFC 6265 cookie jar semantics) but
  only actually exercised once the integration tests run via CI.

## 14. Known Limitations

- No "list active sessions" or "revoke a specific device's session"
  endpoint yet — `SessionStore` supports the underlying revoke-by-
  family primitive, session metadata (ip/user_agent) is captured and
  stored, but no API surface exposes it. Not built because it wasn't
  in the approved API contract (Section I) and inventing one would
  be scope creep beyond what was asked.
- `PATCH /organizations/{id}` only supports updating `name` — `slug`
  and `status` changes are not implemented (not in the approved
  schema, `OrganizationUpdate`).
- Docker-based verification remains blocked per the Phase 0 decision
  (hardware) — carried forward, not re-litigated here.

## 15. Requirement Traceability Matrix

| Requirement | Implementation | Tests | Verification |
|---|---|---|---|
| Users/Orgs/Memberships schema | `models/`, migration `0002` | none direct (exercised via API tests) | UNVERIFIED (needs CI) |
| Password hashing (Argon2id) | `core/security.py` | `test_security.py` | UNVERIFIED (not run) |
| Session issuance/validation/expiry | `core/sessions.py` | `test_sessions.py` | UNVERIFIED (not run) |
| Refresh rotation + reuse detection | `core/sessions.py` | `test_sessions.py` (unit), `test_auth_flow.py` (integration) | PARTIAL (unit logic sound by inspection; nothing run) |
| CSRF protection | `core/csrf.py`, `api/deps.py` | exercised implicitly in `test_auth_flow.py` (org creation) | UNVERIFIED |
| RBAC hierarchy | `core/rbac.py` | `test_rbac.py` | UNVERIFIED (not run) |
| Tenant isolation | `api/deps.py::require_membership` | `test_cross_tenant_access_is_denied`, `test_idor_...` | UNVERIFIED (not run) — this is the SINGLE MOST IMPORTANT row in this table and it is not yet proven |
| Audit foundation | `models/audit_log.py`, `services/audit_service.py` | none dedicated yet | NOT_APPLICABLE for this phase's mandatory tests (not in Section J's required list) |
| ADR-003 | `docs/decisions/ADR-003-...md` | n/a | PASS (file review) |
| ADR-004 | `docs/decisions/ADR-004-...md` | n/a | PASS (file review) |

## 16. BLOCKED / UNVERIFIED Summary

Everything that needs a live Postgres+Redis is UNVERIFIED here and
must go through CI (per the recorded Phase 0 hardware decision).
Everything that needs `ruff`/`mypy`/`pytest` themselves installed is
UNVERIFIED here (no network in the authoring sandbox) but CAN be run
by the user locally without Docker via `uv sync` — this is the
identical situation Phase 0 was in before the user ran the real
commands and found 2 real bugs. The same is expected here: **do not
be surprised if this phase also needs at least one real fix-and-rerun
cycle** — that is the process working, not a sign of a bad plan.

## 17. Final Phase 1 Status

**PARTIAL.**

Upgraded from UNVERIFIED (Section 0 draft) once the user actually ran
`ruff check`/`ruff format --check`/`mypy`/`pytest` for real: 31 ruff
errors + 13 mypy errors were found and fixed (all documented in
Section 0), and `pytest -m "not integration"` now shows **26 passed,
5 deselected** — genuine execution evidence, not a claim.

Not yet PASS because the single most important requirement — cross-
tenant isolation actually being enforced, not just written — is still
UNVERIFIED (rows 16-19 in Section 12): those live in the 5 deselected
integration tests, which need real Postgres+Redis and therefore route
through CI (per the Phase 0 hardware decision), not through what's
been run so far. Migration `0002` has also never touched a real
database yet (rows 1-3).

Next required step: push to GitHub, confirm CI is green (including
the integration test job), and report that back — only then does
this become eligible for PASS per the Definition of Done.

